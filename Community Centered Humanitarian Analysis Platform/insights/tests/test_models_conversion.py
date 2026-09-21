"""One document, one current state of having been read."""
from data_track.models import Document
from django.db import IntegrityError, transaction
from django.test import TestCase

from insights.models import Conversion, ExtractionJob


class ConversionTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(
            file_name="r.pdf", rel_path="media/abc-r.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40)

    def test_one_conversion_per_document(self):
        Conversion.objects.create(document=self.document, engine="docling", ok=True, pages=3)
        # Wrapped so the broken transaction does not poison the rest of the test
        # case - a TestCase runs inside one atomic block.
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Conversion.objects.create(document=self.document, engine="pymupdf", ok=False)

    def test_deleting_the_job_keeps_the_record(self):
        # How a document was read is evidence about the text now in the
        # database. Deleting the batch it arrived in must not erase it.
        job = ExtractionJob.objects.create(status="collected")
        Conversion.objects.create(document=self.document, job=job, engine="docling",
                                  ok=True, pages=3)
        job.delete()
        row = Conversion.objects.get(document=self.document)
        self.assertEqual(row.engine, "docling")
        self.assertIsNone(row.job_id)

    def test_str_names_the_engine(self):
        row = Conversion.objects.create(document=self.document, engine="pymupdf",
                                        ok=False, pages=2)
        self.assertIn("pymupdf", str(row))
