"""Step 2: the page that shows what the model will actually read.

MCP_CACHE_DIR IS OVERRIDDEN, AND IT HAS TO BE. log_path() resolves under it,
so a test that writes a job log without this writes into the REAL cache
directory beside the actual extraction logs - and a cleanup that deletes the
file afterwards deletes a real one, because job ids in the test database
collide with job ids in the live one.
"""
import tempfile
from pathlib import Path
from unittest import mock

from data_track.models import Document, DocumentText
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from insights import wizard
from insights.models import Conversion, ExtractionJob


class WizardReadTests(TestCase):
    def setUp(self):
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        override = override_settings(MCP_CACHE_DIR=Path(self.cache.name))
        override.enable()
        self.addCleanup(override.disable)

        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.job = ExtractionJob.objects.create(status="collected", documents_total=1)
        self.document = Document.objects.create(
            file_name="report.pdf", rel_path="media/abc-report.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40, pages=1)
        self.job.documents.add(self.document)

    def job_url(self):
        return reverse("admin:insights_wizard_job", args=[self.job.id])

    def set_status(self, status):
        self.job.status = status
        self.job.save(update_fields=["status"])

    def test_a_collected_job_lands_on_the_read_page(self):
        response = self.client.get(self.job_url())
        self.assertTemplateUsed(response, "insights/wizard_read.html")

    def test_the_read_button_launches_the_command(self):
        with mock.patch("insights.wizard.subprocess.Popen") as popen:
            response = self.client.post(
                reverse("admin:insights_wizard_read", args=[self.job.id]))
        self.assertTrue(response.json()["started"])
        self.assertIn("convert_documents", popen.call_args.args[0])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "converting")

    def test_a_second_click_does_not_launch_a_second_read(self):
        # Both runs would delete and rebuild the same DocumentText rows, and
        # the loser could commit its delete after the winner's insert.
        self.set_status("converting")
        with mock.patch("insights.wizard.subprocess.Popen") as popen:
            response = self.client.post(
                reverse("admin:insights_wizard_read", args=[self.job.id]))
        self.assertFalse(response.json()["started"])
        popen.assert_not_called()

    def test_the_converted_page_shows_the_text_and_the_engine(self):
        DocumentText.objects.create(document=self.document, page=1,
                                    text="## Displacement\n\nthe converted text")
        Conversion.objects.create(document=self.document, job=self.job,
                                  engine="docling", ok=True, pages=1)
        self.set_status("converted")
        body = self.client.get(self.job_url()).content.decode()
        self.assertIn("the converted text", body)
        self.assertIn("Docling", body)

    def test_a_fallback_is_badged_with_its_reason(self):
        DocumentText.objects.create(document=self.document, page=1, text="raw text")
        Conversion.objects.create(document=self.document, job=self.job, engine="pymupdf",
                                  ok=False, pages=1, message="RuntimeError: boom")
        self.set_status("converted")
        body = self.client.get(self.job_url()).content.decode()
        self.assertIn("Docling failed", body)
        self.assertIn("RuntimeError: boom", body)

    def test_continue_moves_the_job_to_queued(self):
        self.set_status("converted")
        self.client.post(reverse("admin:insights_wizard_read_done", args=[self.job.id]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "queued")

    def test_continue_is_refused_from_any_other_state(self):
        self.client.post(reverse("admin:insights_wizard_read_done", args=[self.job.id]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "collected")

    def test_progress_reads_the_convert_log_while_converting(self):
        self.set_status("converting")
        path = wizard.log_path(self.job, "convert")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reading report.pdf", encoding="utf-8")
        payload = self.client.get(
            reverse("admin:insights_wizard_progress", args=[self.job.id])).json()
        self.assertIn("reading report.pdf", payload["log_tail"])

    def test_progress_reads_the_extract_log_while_extracting(self):
        # The two stages have separate log files, and one polling endpoint
        # serves both - so it has to pick by status, not by job id alone.
        self.set_status("running")
        path = wizard.log_path(self.job, "extract")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("extracting report.pdf", encoding="utf-8")
        payload = self.client.get(
            reverse("admin:insights_wizard_progress", args=[self.job.id])).json()
        self.assertIn("extracting report.pdf", payload["log_tail"])


class WizardStepTwoLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_step_two_links_to_the_job_once_it_is_collected(self):
        job = ExtractionJob.objects.create(status="collected")
        links = wizard.step_links(job, current=2)
        self.assertIsNone(links[1]["url"])  # the current step is never a link
        links = wizard.step_links(job, current=1)
        self.assertEqual(links[1]["url"],
                         reverse("admin:insights_wizard_job", args=[job.id]))

    def test_step_two_is_inert_once_the_batch_has_moved_on(self):
        # Going "back" to the read step from a batch that is extracting would
        # offer to replace the text under insights already written against it.
        job = ExtractionJob.objects.create(status="loaded")
        self.assertIsNone(wizard.step_links(job, current=4)[1]["url"])

    def test_step_two_is_inert_with_no_job_at_all(self):
        self.assertIsNone(wizard.step_links(None, current=1)[1]["url"])
