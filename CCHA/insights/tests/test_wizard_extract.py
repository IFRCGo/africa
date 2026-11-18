"""Progress is read off the job and its log file, and a failure says so."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from insights.models import ExtractionJob


class ExtractProgressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        self.job = ExtractionJob.objects.create(
            status="running", documents_total=4, documents_done=1,
            insights_proposed=7, insights_rejected_unverifiable=2)

    def progress(self):
        with override_settings(API_CACHE_DIR=self.cache.name):
            return self.client.get(
                reverse("admin:insights_wizard_progress", args=[self.job.id])).json()

    def test_the_counters_come_from_the_job(self):
        body = self.progress()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["done"], 1)
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["proposed"], 7)
        self.assertEqual(body["unverifiable"], 2)

    def test_a_missing_log_is_not_an_error(self):
        body = self.progress()
        self.assertEqual(body["log_tail"], "")
        self.assertIsNone(body["last_change"])

    def test_the_log_is_tailed_from_the_end(self):
        folder = Path(self.cache.name) / "insights"
        folder.mkdir(parents=True)
        (folder / f"job-{self.job.id}.log").write_text(
            "x" * 9000 + "\nthe last line\n", encoding="utf-8")
        body = self.progress()
        self.assertIn("the last line", body["log_tail"])
        self.assertLess(len(body["log_tail"]), 9000)
        self.assertIsNotNone(body["last_change"])

    def test_launching_refuses_a_job_that_is_already_running(self):
        # A double click must not run two extractions of one job: the second
        # pass would double every insight the first one wrote.
        with patch("insights.wizard.subprocess.Popen") as popen:
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.assertFalse(body["started"])
        popen.assert_not_called()

    def test_launching_says_so_when_no_extractor_is_configured(self):
        # The normal state for the route CLAUDE.md documents first: extraction
        # run by an agent on the host, loaded from api_cache/insights/.
        self.job.status = "queued"
        self.job.save(update_fields=["status"])
        with patch("insights.wizard.get_extractor",
                   side_effect=ValueError("LLM_PROVIDER is not set")):
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.assertFalse(body["started"])
        self.assertIn("LLM_PROVIDER is not set", body["message"])

    def test_the_stall_notices_reset_button_actually_resets(self):
        """The only way out of a run whose process was killed.

        The button posts the existing changelist action rather than a second
        implementation of it, and ExtractionJobAdmin is hidden from the index
        by get_model_perms returning {} - so this proves the action still runs
        for a model that no longer appears in the app list. Without it the
        stall path has no exit at all: run_extraction_now and the wizard's own
        extract() both refuse to relaunch a job sitting at "running".
        """
        response = self.client.post(
            reverse("admin:insights_extractionjob_changelist"),
            {"action": "reset_stuck_job",
             "_selected_action": [str(self.job.id)],
             "index": "0"},
            follow=True)
        self.job.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.job.status, "queued")

    def test_the_reset_button_is_on_the_stall_notice(self):
        """The page has to carry the form, not just describe the way out."""
        body = self.client.get(
            reverse("admin:insights_wizard_job", args=[self.job.id])).content.decode()
        self.assertIn('value="reset_stuck_job"', body)
        self.assertIn(f'name="_selected_action" value="{self.job.id}"', body)

    def test_launching_marks_the_job_running_before_it_returns(self):
        self.job.status = "queued"
        self.job.save(update_fields=["status"])
        with override_settings(API_CACHE_DIR=self.cache.name), \
             patch("insights.wizard.get_extractor"), \
             patch("insights.wizard.subprocess.Popen") as popen:
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.job.refresh_from_db()
        self.assertTrue(body["started"])
        self.assertEqual(self.job.status, "running")
        # Detached, so a gunicorn worker recycling does not kill it.
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
