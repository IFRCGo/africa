"""A rebuild must FINISH, and a stuck job must be releasable.

Both of these are about the same failure: a job that never leaves an active
status holds its source - or, for a rebuild, holds every source - against every
future press. The feature then does nothing at all until somebody edits a row in
a shell, which is worse than the agent path it replaces.

The first version of this shipped exactly that bug: `rebuild` launched
`run_pipeline`, which knows nothing about PullJob and was never passed --job, so
the job sat at 'queued' forever. The tests missed it because they patched Popen
and only read argv - nothing asked how a rebuild job ends.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from mcp.locks import claim
from mcp.models import PullJob


class RunRebuildCommandTests(TestCase):
    def test_a_successful_rebuild_marks_the_job_succeeded(self):
        job = PullJob.objects.create(kind="rebuild", status="queued")
        with patch("mcp.management.commands.run_rebuild.call_command") as pipeline:
            call_command("run_rebuild", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(pipeline.call_args.args[0], "run_pipeline")
        self.assertIn("s06,s07", pipeline.call_args.args)

    def test_a_failing_rebuild_marks_the_job_failed(self):
        job = PullJob.objects.create(kind="rebuild", status="queued")
        with patch("mcp.management.commands.run_rebuild.call_command",
                   side_effect=RuntimeError("s06 blew up")):
            with self.assertRaises(Exception):
                call_command("run_rebuild", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("s06 blew up", job.message)

    def test_a_finished_rebuild_releases_every_source(self):
        """THE REGRESSION. One press must not brick every Pull button."""
        job = claim("rebuild")
        with patch("mcp.management.commands.run_rebuild.call_command"):
            call_command("run_rebuild", "--job", str(job.id))
        # No JobBusy: a pull is claimable again.
        self.assertIsNotNone(
            claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD"))

    def test_a_failed_rebuild_also_releases_every_source(self):
        job = claim("rebuild")
        with patch("mcp.management.commands.run_rebuild.call_command",
                   side_effect=RuntimeError("boom")):
            with self.assertRaises(Exception):
                call_command("run_rebuild", "--job", str(job.id))
        self.assertIsNotNone(
            claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD"))


class RebuildViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)

    def test_the_view_launches_the_wrapper_not_the_pipeline_directly(self):
        """run_pipeline cannot report back; the wrapper is what closes the job."""
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post("/admin/mcp/datasource/rebuild/")
        argv = popen.call_args.args[0]
        self.assertIn("run_rebuild", argv)
        self.assertIn("--job", argv)

    def test_a_launch_failure_does_not_leave_the_job_holding_everything(self):
        """If Popen itself raises, the job must not sit queued forever."""
        with patch("mcp.views.subprocess.Popen", side_effect=OSError("no fork")):
            self.client.post("/admin/mcp/datasource/rebuild/")
        job = PullJob.objects.get()
        self.assertEqual(job.status, "failed")


class ResetTests(TestCase):
    """Spec §9: a job left running by a container restart must be resettable."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("r", "r@e.org", "pw")
        self.client.force_login(self.user)

    def test_resetting_a_stuck_job_releases_its_source(self):
        from mcp.admin import PullJobAdmin
        from mcp.models import PullJob as Model
        stuck = PullJob.objects.create(kind="pull", source="ipc",
                                       dataset="food_security", iso3="SDN",
                                       status="running")
        request = type("R", (), {"user": self.user, "_messages": None})()
        PullJobAdmin(Model, None).reset_stuck_job(
            request, PullJob.objects.filter(pk=stuck.pk))
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, "failed")
        self.assertIsNotNone(
            claim("pull", source="ipc", dataset="food_security", iso3="TCD"))

    def test_the_reset_says_who_did_it(self):
        from mcp.admin import PullJobAdmin
        from mcp.models import PullJob as Model
        stuck = PullJob.objects.create(kind="pull", source="ipc",
                                       dataset="food_security", iso3="SDN",
                                       status="running")
        request = type("R", (), {"user": self.user, "_messages": None})()
        PullJobAdmin(Model, None).reset_stuck_job(
            request, PullJob.objects.filter(pk=stuck.pk))
        stuck.refresh_from_db()
        self.assertIn("r", stuck.message)

    def test_a_finished_job_is_not_touched_by_a_reset(self):
        done = PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                                      rows_written=12)
        from mcp.admin import PullJobAdmin
        from mcp.models import PullJob as Model
        request = type("R", (), {"user": self.user, "_messages": None})()
        PullJobAdmin(Model, None).reset_stuck_job(
            request, PullJob.objects.filter(pk=done.pk))
        done.refresh_from_db()
        self.assertEqual(done.status, "succeeded")
