"""Getting a document in, and staying out of the pipeline's way.

The pipeline-invisibility test is the important one. s02_extract_text selects
documents that have NO page rows; because intake writes DocumentText itself,
these documents are never selected, so s02 never tries to reopen a file at a
path it cannot resolve.
"""
import tempfile
from pathlib import Path

import fitz
from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.intake import catalogue_file, catalogue_folder
from insights.models import InsightFolder


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


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
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.folder_id, folder.id)

    def test_an_unreachable_path_raises_rather_than_opening_an_empty_job(self):
        folder = InsightFolder.objects.create(label="gone", path="/nowhere/at/all")
        with self.assertRaises(FileNotFoundError):
            catalogue_folder(folder)
