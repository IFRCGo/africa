"""One bad document must not cost the other 199."""
import tempfile
from pathlib import Path
from unittest import mock

import fitz
from data_track.models import Document, DocumentText
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from insights import convert
from insights.models import Conversion, ExtractionJob


def make_document(tmp, name, sha1):
    path = Path(tmp) / name
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "raw text")
    doc.save(str(path))
    doc.close()
    document = Document.objects.create(
        file_name=name, rel_path=f"media/{sha1[:12]}-{name}",
        source_collection="insights", family="insight_source", sha1=sha1, pages=1)
    DocumentText.objects.create(document=document, page=1, text="raw text")
    return document, path


def fake_ok(document, path, job=None, reload_only=False):
    return Conversion.objects.create(document=document, job=job, engine="docling",
                                     ok=True, pages=1)


class ConvertCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

        self.job = ExtractionJob.objects.create(status="collected")
        self.good, _ = make_document(self.tmp.name, "good.pdf", "a" * 40)
        self.bad, _ = make_document(self.tmp.name, "bad.pdf", "b" * 40)
        self.job.documents.add(self.good, self.bad)
        self.job.documents_total = 2
        self.job.save()

    def run_command(self, **kwargs):
        with override_settings(MCP_CACHE_DIR=Path(self.cache.name)):
            call_command("convert_documents", job=self.job.id, **kwargs)
        self.job.refresh_from_db()

    def test_one_failure_does_not_stop_the_batch(self):
        def one_bad(document, path, job=None, reload_only=False):
            engine = "pymupdf" if document.sha1.startswith("b") else "docling"
            return Conversion.objects.create(
                document=document, job=job, engine=engine, ok=engine == "docling",
                pages=1, message="" if engine == "docling" else "RuntimeError: boom")

        with mock.patch.object(convert, "convert_document", side_effect=one_bad):
            self.run_command()

        self.assertEqual(self.job.status, "converted")
        self.assertEqual(self.job.documents_done, 2)
        self.assertIn("boom", self.job.log)

    def test_counts_are_reset_between_runs(self):
        self.job.documents_done = 7
        self.job.save(update_fields=["documents_done"])
        with mock.patch.object(convert, "convert_document", side_effect=fake_ok):
            self.run_command()
        self.assertEqual(self.job.documents_done, 2)

    def test_a_run_level_failure_lands_on_convert_failed(self):
        with mock.patch.object(convert, "convert_document",
                               side_effect=OSError("disk went away")):
            with self.assertRaises(CommandError):
                self.run_command()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "convert_failed")
        self.assertIn("OSError: disk went away", self.job.log)

    def test_reload_from_cache_is_passed_through(self):
        seen = {}

        def record(document, path, job=None, reload_only=False):
            seen["reload_only"] = reload_only
            return fake_ok(document, path, job=job)

        with mock.patch.object(convert, "convert_document", side_effect=record):
            self.run_command(reload_from_cache=True)
        self.assertTrue(seen["reload_only"])

    def test_an_unknown_job_is_a_command_error(self):
        with self.assertRaises(CommandError):
            call_command("convert_documents", job=99999)
