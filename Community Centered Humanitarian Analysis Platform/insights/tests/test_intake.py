"""Getting a document in, and staying out of the pipeline's way.

The pipeline-invisibility test is the important one. s02_extract_text selects
documents that have NO page rows; because intake writes DocumentText itself,
these documents are never selected, so s02 never tries to reopen a file at a
path it cannot resolve.
"""
import tempfile
from pathlib import Path

import fitz
from django.conf import settings
from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.intake import catalogue_file, catalogue_folder, relative_path
from insights.models import InsightFolder


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def write_docx(path, paragraphs):
    from docx import Document as Docx

    doc = Docx()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(path))


class CatalogueFileTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_pdf_becomes_a_document_with_its_pages(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["First page words.", "Second page words."])
        document = catalogue_file(pdf, iso3="TCD", report_date="2026-03-14")
        self.assertEqual(document.file_name, "assessment.pdf")
        self.assertEqual(document.source_collection, "insights")
        self.assertEqual(document.family, "insight_source")
        self.assertEqual(document.date_source, "intake")
        self.assertEqual(document.texts.count(), 2)
        self.assertIn("First page", DocumentText.objects.get(document=document, page=1).text)

    def test_the_same_file_is_not_catalogued_twice(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words."])
        first = catalogue_file(pdf)
        second = catalogue_file(pdf)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Document.objects.count(), 1)

    def test_a_sha1_and_page_count_are_recorded(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words.", "More."])
        document = catalogue_file(pdf)
        self.assertEqual(len(document.sha1), 40)
        self.assertEqual(document.pages, 2)

    def test_the_pipeline_will_not_select_it_for_text_extraction(self):
        """s02 selects documents with no page rows. These have them already."""
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words."])
        catalogue_file(pdf)
        self.assertEqual(Document.objects.filter(texts__isnull=True).count(), 0)

    def test_two_different_files_sharing_a_basename_do_not_collide(self):
        """A bare basename is not unique - two uploads could both be named
        'assessment.pdf'. Content-addressing the media path must keep them
        as two separate documents, not silently merge the second into the
        first (wrong sha1, wrong pages, wrong text, no error raised)."""
        dir_a = self.dir / "a"
        dir_b = self.dir / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        pdf_a = dir_a / "assessment.pdf"
        pdf_b = dir_b / "assessment.pdf"
        write_pdf(pdf_a, ["Alpha content."])
        write_pdf(pdf_b, ["Beta content, and different."])

        document_a = catalogue_file(pdf_a)
        document_b = catalogue_file(pdf_b)

        self.assertNotEqual(document_a.id, document_b.id)
        self.assertNotEqual(document_a.rel_path, document_b.rel_path)
        self.assertNotEqual(document_a.sha1, document_b.sha1)
        self.assertEqual(Document.objects.count(), 2)

    def test_a_file_under_source_root_keeps_a_plain_relative_path(self):
        """No sha1 prefix when the file is under SOURCE_ROOT - it must resolve
        exactly as a UNHCR PDF's rel_path does."""
        target = Path(settings.SOURCE_ROOT) / "UNHCR Regional Population Movement pdfs" / "hypothetical.pdf"
        rel = relative_path(target, "abc123abc123abc123abc123abc123abc123abcd")
        self.assertEqual(rel, "UNHCR Regional Population Movement pdfs/hypothetical.pdf")
        self.assertNotIn("abc123", rel)

    def test_a_docx_becomes_a_document_with_its_body_as_one_page(self):
        """A DOCX has no pages until rendered, so the whole body is page 1."""
        docx_path = self.dir / "notes.docx"
        write_docx(docx_path, ["First paragraph.", "Second paragraph."])
        document = catalogue_file(docx_path)
        self.assertEqual(document.pages, 1)
        text = DocumentText.objects.get(document=document, page=1).text
        self.assertIn("First paragraph", text)
        self.assertIn("Second paragraph", text)

    def test_a_blank_report_date_does_not_raise(self):
        """Task 8's Admin form submits '' for a blank optional field."""
        pdf = self.dir / "undated.pdf"
        write_pdf(pdf, ["Words."])
        document = catalogue_file(pdf, report_date="")
        self.assertIsNone(document.report_date)


class CatalogueFolderTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_every_pdf_in_the_folder_is_catalogued_and_a_job_opened(self):
        for name in ("a.pdf", "b.pdf"):
            write_pdf(self.dir / name, ["Words."])
        (self.dir / "notes.txt").write_text("ignored")
        folder = InsightFolder.objects.create(
            label="test", path=str(self.dir), default_iso3="TCD")
        job = catalogue_folder(folder)
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(job.documents_total, 2)
        self.assertEqual(job.status, "collected")
        self.assertEqual(job.folder_id, folder.id)

    def test_an_unreachable_path_raises_rather_than_opening_an_empty_job(self):
        folder = InsightFolder.objects.create(label="gone", path="/nowhere/at/all")
        with self.assertRaises(FileNotFoundError):
            catalogue_folder(folder)

    def test_every_catalogued_document_is_attached_to_the_job(self):
        """R13a: without this link the brief's `extract_insights --job N` had
        nothing to scope itself to but every document ever catalogued into
        the insights collection - a job for this folder must extract only
        this folder's documents."""
        for name in ("a.pdf", "b.pdf"):
            write_pdf(self.dir / name, ["Words."])
        folder = InsightFolder.objects.create(
            label="test", path=str(self.dir), default_iso3="TCD")
        job = catalogue_folder(folder)
        self.assertEqual(job.documents.count(), 2)
        self.assertEqual(
            set(job.documents.values_list("file_name", flat=True)), {"a.pdf", "b.pdf"})

    def test_a_document_already_catalogued_by_an_earlier_job_is_attached_again(self):
        """Re-cataloguing the same file (e.g. the folder is run a second
        time) must not skip attaching it to the new job just because
        catalogue_file() found it already existed."""
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words."])
        first_folder = InsightFolder.objects.create(label="first", path=str(self.dir))
        first_job = catalogue_folder(first_folder)
        second_job = catalogue_folder(first_folder)
        self.assertEqual(first_job.documents.count(), 1)
        self.assertEqual(second_job.documents.count(), 1)
        self.assertEqual(
            first_job.documents.first().id, second_job.documents.first().id)
