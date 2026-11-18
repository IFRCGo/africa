"""Where a batch goes when its files are in, and how a stuck read is recovered.

"queued" used to mean "files are in". It now means CONVERTED and ready to
extract, and everything that used to open a job at "queued" opens it at
"collected" instead - otherwise a batch would march straight past the read
step with intake's PyMuPDF text still in the database.
"""
import tempfile
from pathlib import Path

import fitz
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob, InsightFolder


class BatchReadyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_closing_a_batch_leaves_it_ready_to_read_not_to_extract(self):
        job = ExtractionJob.objects.create(status="collecting")
        # It needs a document to close at all - an empty batch is refused and
        # stays "collecting" - and what this asserts is the destination.
        job.documents.add(Document.objects.create(
            file_name="r.pdf", rel_path="media/abc123456789-r.pdf",
            source_collection="insights", family="insight_source",
            pages=1, file_size=1, sha1="a" * 40))
        self.client.post(reverse("admin:insights_wizard_batch_ready", args=[job.id]))
        job.refresh_from_db()
        self.assertEqual(job.status, "collected")


class CatalogueFolderTests(TestCase):
    def test_a_registered_folder_opens_at_collected(self):
        from insights.intake import catalogue_folder

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "text")
        doc.save(str(Path(tmp.name) / "r.pdf"))
        doc.close()

        folder = InsightFolder.objects.create(label="f", path=tmp.name)
        job = catalogue_folder(folder)
        self.assertEqual(job.status, "collected")


class ResetStuckJobTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def reset(self, job):
        self.client.post(reverse("admin:insights_extractionjob_changelist"), {
            "action": "reset_stuck_job", "_selected_action": [job.id], "index": "0"})
        job.refresh_from_db()
        return job

    def test_a_stuck_extraction_goes_back_to_queued(self):
        job = ExtractionJob.objects.create(status="running")
        self.assertEqual(self.reset(job).status, "queued")

    def test_a_stuck_read_goes_back_to_collected(self):
        # Back to where the read is launched from, not to where extraction is:
        # a killed conversion has converted nothing.
        job = ExtractionJob.objects.create(status="converting")
        self.assertEqual(self.reset(job).status, "collected")

    def test_a_finished_job_is_left_alone(self):
        job = ExtractionJob.objects.create(status="loaded")
        self.assertEqual(self.reset(job).status, "loaded")
