"""The updater page and the MCP job table must share one gate.

WHY THIS FILE EXISTS. The updater used to guard its runs with a module-level
threading.Lock. gunicorn runs two workers (see the Dockerfile), so that lock only
ever covered one of them: two browsers could start two pipelines, each of which
begins by deleting every row in population_figures. Worse, the lock was invisible
to mcp/locks.py, so an Admin -> MCP rebuild and an "Update now" could rebuild the
same tables at the same time, and the status endpoint reported "idle" from
whichever worker was not holding the lock.

The rule these tests pin down: the updater claims a PullJob like every other
route that writes those tables, so one gate serialises all of them and the answer
survives the request being handled by a different worker.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from mcp.locks import JobBusy, claim
from mcp.models import ACTIVE, PullJob
from updater import views


class FakeProcess:
    """A subprocess that prints two pipeline lines and exits cleanly.

    Popen is patched out in every test here because the real call would run
    manage.py run_pipeline against the test database - deleting and rebuilding
    every table the pipeline owns. What is under test is which jobs the stream
    lets start, not the pipeline itself.
    """

    def __init__(self, lines=("=== s06_mcp_layers ===", "done"), returncode=0):
        self.stdout = iter(f"{line}\n" for line in lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def messages(generator):
    """Drain an SSE generator into the list of payload strings it yielded."""
    return list(generator)


class RebuildGateTests(TestCase):
    def test_the_updater_is_refused_while_an_mcp_pull_runs(self):
        """A rebuild reads every table a pull writes - the rule mcp/locks.py keeps."""
        held = claim("pull", source="ipc", dataset="food_security", iso3="SDN")

        with patch.object(views.subprocess, "Popen") as popen:
            out = "".join(messages(views.rebuild_external_stream()))

        self.assertIn("error", out)
        self.assertIn(str(held.id), out)
        popen.assert_not_called()

    def test_a_full_update_is_refused_while_an_mcp_pull_runs(self):
        held = claim("pull", source="ipc", dataset="food_security", iso3="SDN")

        with patch.object(views.subprocess, "Popen") as popen:
            out = "".join(messages(views.run_pipeline_stream()))

        self.assertIn("error", out)
        self.assertIn(str(held.id), out)
        popen.assert_not_called()

    def test_a_refused_update_does_not_announce_that_it_started(self):
        """The browser must not be told a run is beginning that never begins."""
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")

        with patch.object(views.subprocess, "Popen"):
            out = "".join(messages(views.run_pipeline_stream()))

        self.assertNotIn("Starting", out)

    def test_an_mcp_pull_is_refused_while_the_updater_runs(self):
        """The half a threading.Lock could never do: block the other app."""
        claimed = {}

        def capture(*args, **kwargs):
            # Popen is called while the updater's own job is still active, so
            # this is the moment a pull from the Admin would collide with it.
            with self.assertRaises(JobBusy):
                claim("pull", source="ipc", dataset="food_security", iso3="SDN")
            claimed["checked"] = True
            return FakeProcess()

        with patch.object(views.subprocess, "Popen", side_effect=capture):
            messages(views.rebuild_external_stream())

        self.assertTrue(claimed.get("checked"), "the stream never started a process")

    def test_a_finished_update_leaves_no_job_holding_the_tables(self):
        with patch.object(views.subprocess, "Popen", return_value=FakeProcess()):
            messages(views.rebuild_external_stream())

        self.assertFalse(PullJob.objects.filter(status__in=ACTIVE).exists())
        self.assertEqual(PullJob.objects.get().status, "succeeded")

    def test_a_failed_update_closes_its_job_as_failed(self):
        with patch.object(views.subprocess, "Popen",
                          return_value=FakeProcess(returncode=1)):
            messages(views.rebuild_external_stream())

        self.assertEqual(PullJob.objects.get().status, "failed")
        self.assertFalse(PullJob.objects.filter(status__in=ACTIVE).exists())

    def test_a_disconnected_browser_does_not_leave_the_gate_shut(self):
        """Closing the stream early must release the job, or every later press
        is refused by a run nobody is watching."""
        with patch.object(views.subprocess, "Popen", return_value=FakeProcess()):
            stream = views.rebuild_external_stream()
            next(stream)          # start it: the job is claimed and running
            self.assertTrue(PullJob.objects.filter(status__in=ACTIVE).exists())
            stream.close()        # what Django does when the client goes away

        self.assertFalse(PullJob.objects.filter(status__in=ACTIVE).exists())


class StatusTests(TestCase):
    def test_status_reports_a_run_started_in_another_worker(self):
        """The reported bug: _lock.locked() is False in the worker that answers."""
        claim("rebuild")

        body = self.client.get(reverse("updater-status")).json()

        self.assertTrue(body["running"])

    def test_status_is_idle_when_nothing_is_active(self):
        body = self.client.get(reverse("updater-status")).json()

        self.assertFalse(body["running"])

    def test_status_is_busy_while_a_pull_holds_the_tables(self):
        """Pressing Update now would be refused, so the page must not say idle."""
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")

        body = self.client.get(reverse("updater-status")).json()

        self.assertTrue(body["running"])
