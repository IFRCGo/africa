"""Files arrive one request at a time, and one bad file does not stop a batch."""
import tempfile
from pathlib import Path

import fitz
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob


def a_pdf(text="The market has been closed for three weeks."):
    """A real one-page PDF, because catalogue_file actually opens it."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


class BatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def open_batch(self, label="3 files"):
        response = self.client.post(
            reverse("admin:insights_wizard_batch"), {"label": label})
        return response.json()["job_id"]

    def send(self, job_id, name, payload, relative_path=""):
        return self.client.post(
            reverse("admin:insights_wizard_batch_file", args=[job_id]),
            {"file": SimpleUploadedFile(name, payload, content_type="application/pdf"),
             "relative_path": relative_path},
        )

    def test_opening_a_batch_creates_a_collecting_job(self):
        job = ExtractionJob.objects.get(id=self.open_batch("folder: DTM Round 12"))
        self.assertEqual(job.status, "collecting")
        self.assertEqual(job.label, "folder: DTM Round 12")

    def test_a_pdf_is_catalogued_and_attached(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            body = self.send(job_id, "report.pdf", a_pdf()).json()
        self.assertEqual(body["outcome"], "catalogued")
        self.assertEqual(body["pages"], 1)
        job = ExtractionJob.objects.get(id=job_id)
        self.assertEqual(job.documents.count(), 1)

    def test_the_same_content_under_another_name_is_a_duplicate(self):
        # Matched on Document.sha1, NOT on rel_path. An upload's rel_path is
        # built from the name storage settled on, and storage uniquifies a
        # collision - so the same report sent twice would otherwise be
        # catalogued twice, and the model paid for twice to read it.
        payload = a_pdf()
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", payload)
            body = self.send(job_id, "report-copy.pdf", payload).json()
        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(Document.objects.filter(source_collection="insights").count(), 1)
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 1)

    def test_the_identical_file_twice_is_also_a_duplicate(self):
        payload = a_pdf()
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", payload)
            body = self.send(job_id, "report.pdf", payload).json()
        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(Document.objects.filter(source_collection="insights").count(), 1)

    def test_a_file_that_is_not_a_document_is_skipped(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            body = self.send(job_id, "notes.txt", b"hello").json()
        self.assertEqual(body["outcome"], "skipped")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_corrupt_pdf_fails_its_own_row_and_the_batch_continues(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            bad = self.send(job_id, "broken.pdf", b"%PDF-1.4 not really")
            good = self.send(job_id, "fine.pdf", a_pdf())
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(bad.json()["outcome"], "failed")
        self.assertEqual(good.json()["outcome"], "catalogued")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 1)

    def test_the_relative_path_is_kept_as_a_label_only(self):
        # It is client-controlled. It must never reach a filesystem path.
        #
        # Asserted INSIDE the override: FileField.path is resolved against
        # whatever MEDIA_ROOT is when it is read, not when the file was saved,
        # so checking it afterwards would test the real media folder instead.
        from insights.models import InsightUpload

        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", a_pdf(),
                      relative_path="../../etc/DTM Round 12/report.pdf")

            upload = InsightUpload.objects.get()
            stored = Path(upload.file.path).resolve()
            self.assertTrue(stored.is_relative_to(Path(self.media.name).resolve()))

        # The folder structure survives, for the preview and the review page.
        self.assertIn("DTM Round 12", upload.label)
        # ...but only as a label. The name on disk carries no directory part of
        # the client's at all, so there is nothing to traverse with.
        self.assertNotIn("..", upload.file.name)
        self.assertEqual(upload.file.name.count("/"), 1)   # "insights/<name>"

    def test_ready_queues_the_batch(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", a_pdf())
            body = self.client.post(
                reverse("admin:insights_wizard_batch_ready", args=[job_id])).json()
        job = ExtractionJob.objects.get(id=job_id)
        self.assertEqual(body["documents_total"], 1)
        self.assertEqual(job.documents_total, 1)
        self.assertEqual(job.status, "collected")
