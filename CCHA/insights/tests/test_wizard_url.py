"""A document can arrive from a link, and it joins the batch the same way a file does.

NOTHING HERE TOUCHES THE NETWORK. requests.get is replaced with a fake whose
bytes the test chooses, because what this endpoint has to get right is what it
does with what comes back - the type it infers, the name it lands under, and
whether the batch already holds it.
"""
import io
import tempfile
import zipfile
from unittest.mock import patch

import fitz
import requests
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob, InsightUpload

PDF_LINK = "https://reliefweb.int/attachments/9f2/dtm-round-12.pdf"


def a_pdf(text="The market has been closed for three weeks."):
    """A real one-page PDF, because catalogue_file actually opens it."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def a_docx(text="Water is trucked in twice a week."):
    """A real DOCX, so the zip really does carry word/document.xml."""
    from docx import Document as Docx

    buffer = io.BytesIO()
    document = Docx()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


class FakeResponse:
    """Just enough of requests.Response for a streamed download."""

    def __init__(self, payload=b"", headers=None, status=200):
        self.payload = payload
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} for url")

    def iter_content(self, chunk_size):
        for start in range(0, len(self.payload), chunk_size):
            yield self.payload[start:start + chunk_size]


class LinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def open_batch(self):
        return self.client.post(
            reverse("admin:insights_wizard_batch"), {"label": "2 links"}).json()["job_id"]

    def send_link(self, job_id, url=PDF_LINK):
        return self.client.post(
            reverse("admin:insights_wizard_batch_url", args=[job_id]), {"url": url})

    def test_a_pdf_behind_a_link_is_catalogued_and_attached(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(a_pdf())):
            job_id = self.open_batch()
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "catalogued")
        self.assertEqual(body["pages"], 1)
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 1)

    def test_the_link_is_kept_as_the_label(self):
        # Where a document came from is the whole provenance story for a link,
        # and label is the column that already means "where this came from".
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(a_pdf())):
            self.send_link(self.open_batch())

        self.assertEqual(InsightUpload.objects.get().label, PDF_LINK)

    def test_the_extension_comes_from_the_bytes_not_the_url(self):
        # HDX and ReliefWeb download links routinely end in an opaque id or a
        # query string. catalogue_file dispatches _pages_of and pdf_metadata on
        # the suffix alone, so a name without one reaches the wrong reader.
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(a_pdf())):
            job_id = self.open_batch()
            body = self.send_link(
                job_id, "https://data.humdata.org/dataset/x?download=1").json()

        self.assertEqual(body["outcome"], "catalogued")
        document = Document.objects.get(id=body["document_id"])
        self.assertTrue(document.file_name.endswith(".pdf"), document.file_name)

    def test_the_server_s_own_name_for_the_file_wins_over_the_url(self):
        # And it is percent-decoded. A French or Arabic report title arrives
        # encoded in Content-Disposition, and file_name is what a reviewer reads
        # on the review page - "Rapport%20Tchad" is not a title.
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(
                          a_pdf(),
                          {"Content-Disposition":
                           "attachment; filename*=UTF-8''Rapport%20Tchad.pdf"})):
            job_id = self.open_batch()
            body = self.send_link(job_id, "https://example.org/download?id=77").json()

        self.assertEqual(body["outcome"], "catalogued")
        # An underscore, not the space: Django's storage runs get_valid_filename
        # over the name before writing it, and file_name is read back off the
        # stored path. The point here is that the "%20" is gone.
        self.assertEqual(
            Document.objects.get(id=body["document_id"]).file_name, "Rapport_Tchad.pdf")

    def test_a_word_document_behind_a_link_is_catalogued(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(a_docx())):
            job_id = self.open_batch()
            body = self.send_link(job_id, "https://example.org/notes").json()

        self.assertEqual(body["outcome"], "catalogued")
        self.assertTrue(
            Document.objects.get(id=body["document_id"]).file_name.endswith(".docx"))

    def test_a_web_page_is_skipped_rather_than_read(self):
        page = b"<!DOCTYPE html><html><body>Report page</body></html>"
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(
                          page, {"Content-Type": "text/html; charset=utf-8"})):
            job_id = self.open_batch()
            body = self.send_link(job_id, "https://reliefweb.int/report/chad/x").json()

        self.assertEqual(body["outcome"], "skipped")
        self.assertIn("web page", body["message"])
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_spreadsheet_is_skipped_although_it_is_also_a_zip(self):
        # A DOCX is a zip and so is an XLSX. Testing the magic bytes alone would
        # send a spreadsheet to python-docx, which fails with a stack trace
        # instead of a sentence.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/workbook.xml", "<workbook/>")

        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(buffer.getvalue())):
            job_id = self.open_batch()
            body = self.send_link(job_id, "https://example.org/figures.xlsx").json()

        self.assertEqual(body["outcome"], "skipped")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_the_same_bytes_from_a_link_and_a_file_are_one_document(self):
        payload = a_pdf()
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(payload)):
            job_id = self.open_batch()
            self.client.post(
                reverse("admin:insights_wizard_batch_file", args=[job_id]),
                {"file": SimpleUploadedFile("report.pdf", payload,
                                            content_type="application/pdf"),
                 "relative_path": "report.pdf"},
            )
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(Document.objects.filter(source_collection="insights").count(), 1)
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 1)

    def test_a_link_that_is_not_http_is_refused_without_fetching(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get") as fetched:
            job_id = self.open_batch()
            body = self.send_link(job_id, "file:///etc/passwd").json()

        self.assertEqual(body["outcome"], "failed")
        fetched.assert_not_called()
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_link_that_does_not_resolve_fails_its_own_row(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      side_effect=requests.ConnectionError("name not known")):
            job_id = self.open_batch()
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "failed")
        self.assertIn("name not known", body["message"])

    def test_a_link_answering_404_fails_its_own_row(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(b"", status=404)):
            job_id = self.open_batch()
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "failed")
        self.assertIn("404", body["message"])

    def test_a_download_past_the_ceiling_is_refused(self):
        # A gunicorn worker is held for the whole of this request, so the
        # ceiling is what stops one enormous link from occupying one.
        from insights import weblink

        with override_settings(MEDIA_ROOT=self.media.name), \
                patch.object(weblink, "MAX_BYTES", 1024), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(b"%PDF-" + b"x" * 4096)):
            job_id = self.open_batch()
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "failed")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_corrupt_pdf_behind_a_link_fails_its_own_row(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(b"%PDF-1.4 not really")):
            job_id = self.open_batch()
            body = self.send_link(job_id).json()

        self.assertEqual(body["outcome"], "failed")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_link_cannot_be_added_to_a_batch_that_has_closed(self):
        with override_settings(MEDIA_ROOT=self.media.name), \
                patch("insights.weblink.requests.get",
                      return_value=FakeResponse(a_pdf())):
            job_id = self.open_batch()
            # It takes a document to close: an empty batch is refused and stays
            # open, which would make this assert nothing at all.
            self.send_link(job_id)
            closed = self.client.post(
                reverse("admin:insights_wizard_batch_ready", args=[job_id])).json()
            response = self.send_link(job_id, "https://example.org/second.pdf")

        self.assertTrue(closed["closed"])
        self.assertEqual(response.status_code, 404)
