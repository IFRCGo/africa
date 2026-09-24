"""Replacing a document's text, and refusing to when something depends on it."""
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import fitz
from data_track.models import Document, DocumentText
from django.test import TestCase, override_settings

from insights import convert, docling_reader
from insights.models import Conversion, ExtractionJob, Insight


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


class ConvertDocumentTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

        self.path = Path(self.tmp.name) / "report.pdf"
        write_pdf(self.path, ["raw page one", "raw page two"])

        self.document = Document.objects.create(
            file_name="report.pdf", rel_path="media/abc-report.pdf",
            source_collection="insights", family="insight_source",
            sha1="a" * 40, pages=2, report_date=date(2026, 3, 1))
        for number, text in ((1, "raw page one"), (2, "raw page two")):
            DocumentText.objects.create(document=self.document, page=number, text=text)

    def settings_override(self):
        return override_settings(API_CACHE_DIR=Path(self.cache.name))

    def fake_read(self, pages=None, version="2.129.0"):
        pages = pages or [(1, "## One\n\nmarkdown page one"), (2, "markdown page two")]
        return mock.patch.object(docling_reader, "read", return_value=(pages, version))

    def test_rows_are_replaced_with_the_markdown(self):
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        stored = list(DocumentText.objects.filter(document=self.document)
                      .order_by("page").values_list("page", "text"))
        self.assertEqual(stored, [(1, "## One\n\nmarkdown page one"), (2, "markdown page two")])
        self.assertEqual((row.engine, row.ok, row.pages), ("docling", True, 2))
        self.assertEqual(row.docling_version, "2.129.0")

    def test_the_markdown_is_written_to_disk_before_it_is_loaded(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
            # Inside the override: cache_paths reads API_CACHE_DIR, so asking
            # for the paths outside it points at the real cache directory and
            # the file is looked for in the wrong place.
            json_path, md_path = convert.cache_paths(self.document)
        self.assertTrue(md_path.exists())
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["pages"][0]["page"], 1)
        self.assertEqual(payload["engine"], "docling")

    def test_a_failure_leaves_the_pymupdf_rows_alone(self):
        with self.settings_override(), \
             mock.patch.object(docling_reader, "read", side_effect=RuntimeError("boom")):
            row = convert.convert_document(self.document, self.path)
        stored = list(DocumentText.objects.filter(document=self.document)
                      .order_by("page").values_list("page", "text"))
        self.assertEqual(stored, [(1, "raw page one"), (2, "raw page two")])
        self.assertEqual((row.engine, row.ok), ("pymupdf", False))
        self.assertIn("RuntimeError: boom", row.message)

    def make_insight(self, status):
        # stated_on and iso3 are NOT NULL with no default - omitting them fails
        # on an IntegrityError long before the assertion is reached.
        return Insight.objects.create(
            document=self.document, page=1, iso3="SDN", stated_on=date(2026, 3, 1),
            status=status, quote="a quote that is long enough")

    def test_a_document_with_a_pending_insight_is_refused(self):
        # Not just published: a pending row is one a reviewer is about to judge
        # against a quote, and moving the page text under it makes that
        # judgement meaningless.
        self.make_insight("pending")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "skipped")
        self.assertEqual(DocumentText.objects.get(document=self.document, page=1).text,
                         "raw page one")

    def test_a_document_whose_insights_were_all_rejected_is_converted(self):
        self.make_insight("rejected")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "docling")

    def test_a_missing_date_is_inferred_from_the_converted_text(self):
        # The payoff for OCR: intake could not read a date out of an empty
        # string, and now there is text to read one out of.
        #
        # pdf_metadata is stubbed out because it OUTRANKS text, and a PDF
        # written by fitz a moment ago carries today's creation date - which
        # would disagree with the text by months and correctly leave the date
        # null. A scanned report, which is the case this serves, generally has
        # no usable creation date either.
        self.document.report_date = None
        self.document.save(update_fields=["report_date"])
        pages = [(1, "Situation report, 14 June 2026"), (2, "more")]
        with self.settings_override(), self.fake_read(pages=pages), \
             mock.patch.object(convert, "pdf_metadata", return_value={}):
            convert.convert_document(self.document, self.path)
        self.document.refresh_from_db()
        self.assertEqual(self.document.report_date, date(2026, 6, 14))
        self.assertEqual(self.document.date_source, "text")

    def test_disagreeing_sources_still_leave_the_date_null(self):
        # The guarantee document_date exists for, and conversion must not
        # quietly undo it: metadata says today, the text says June.
        self.document.report_date = None
        self.document.save(update_fields=["report_date"])
        pages = [(1, "Situation report, 14 June 2026"), (2, "more")]
        with self.settings_override(), self.fake_read(pages=pages), \
             mock.patch.object(convert, "pdf_metadata",
                               return_value={"creationDate": "D:20260921120000"}):
            convert.convert_document(self.document, self.path)
        self.document.refresh_from_db()
        self.assertIsNone(self.document.report_date)

    def test_an_existing_date_is_not_overwritten(self):
        pages = [(1, "Situation report, 14 June 2026"), (2, "more")]
        with self.settings_override(), self.fake_read(pages=pages):
            convert.convert_document(self.document, self.path)
        self.document.refresh_from_db()
        self.assertEqual(self.document.report_date, date(2026, 3, 1))

    def test_reload_only_does_not_call_docling(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
        DocumentText.objects.filter(document=self.document).delete()
        with self.settings_override(), \
             mock.patch.object(docling_reader, "read",
                               side_effect=AssertionError("Docling was called")) as spy:
            row = convert.convert_document(self.document, self.path, reload_only=True)
        spy.assert_not_called()
        self.assertTrue(row.ok)
        self.assertEqual(DocumentText.objects.filter(document=self.document).count(), 2)

    def test_reload_only_with_no_cache_is_a_failure_not_a_crash(self):
        with self.settings_override():
            row = convert.convert_document(self.document, self.path, reload_only=True)
        self.assertFalse(row.ok)
        self.assertEqual(row.engine, "pymupdf")

    @override_settings(DOCLING_ENABLED=False)
    def test_disabled_leaves_the_rows_and_says_so(self):
        with self.settings_override():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "pymupdf")
        self.assertIn("disabled", row.message.lower())
        self.assertEqual(DocumentText.objects.count(), 2)

    def test_the_job_is_recorded_on_the_conversion(self):
        job = ExtractionJob.objects.create(status="converting")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path, job=job)
        self.assertEqual(row.job_id, job.id)

    def test_converting_twice_keeps_one_row(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
            convert.convert_document(self.document, self.path)
        self.assertEqual(Conversion.objects.filter(document=self.document).count(), 1)


class SourcePathTests(TestCase):
    """Finding the file again, wherever MEDIA_ROOT happens to point.

    This is the quiet failure mode: convert_document turns a missing file into
    a per-document failure, so getting it wrong badges every upload "Docling
    failed" and silently keeps the PyMuPDF text, with nothing saying why.
    """

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.document = Document.objects.create(
            file_name="report.pdf", rel_path="media/abc123456789-report.pdf",
            source_collection="insights", family="insight_source",
            sha1="c" * 40, pages=1)

    def test_an_upload_is_found_through_its_own_filefield(self):
        from django.core.files.base import ContentFile

        from insights.models import InsightUpload

        with override_settings(MEDIA_ROOT=Path(self.media.name)):
            upload = InsightUpload.objects.create(label="report.pdf", document=self.document)
            upload.file.save("report.pdf", ContentFile(b"%PDF-1.4 stub"), save=True)
            self.assertEqual(convert.source_path(self.document),
                             Path(upload.file.path))

    def test_a_folder_document_resolves_under_source_root(self):
        with tempfile.TemporaryDirectory() as root:
            on_disk = Path(root) / "sub" / "r.pdf"
            on_disk.parent.mkdir(parents=True)
            write_pdf(on_disk, ["text"])
            document = Document.objects.create(
                file_name="r.pdf", rel_path="sub/r.pdf", source_collection="insights",
                family="insight_source", sha1="d" * 40, pages=1)
            with override_settings(SOURCE_ROOT=Path(root)):
                self.assertEqual(convert.source_path(document), on_disk)
