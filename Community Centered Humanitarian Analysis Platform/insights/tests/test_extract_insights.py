"""The command that runs an in-container extraction and loads its result.

The extractor is always mocked here - no network call, no real model, no real
anthropic/openai_compatible adapter. What is worth testing at this layer is
the wiring: that a job extracts ONLY its own documents (R13a - without this a
job for one folder would silently re-extract every other folder's documents
too), and that a refusal or a parse failure the adapter recorded lands in the
job's own log, not dropped and not raised (task-13-rulings.md §2-4).
"""
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from data_track.models import Document, DocumentText
from insights.models import ExtractionJob, Insight

# Patching where the name is looked up (extract_insights.py does
# `from insights.extractors import get_extractor`), not where it is defined.
GET_EXTRACTOR = "insights.management.commands.extract_insights.get_extractor"

QUOTE = (
    "When it rains we get flash floods, and with the fighting around us the "
    "hospitals are gone — we have cholera now and nowhere to take the sick."
)


class FakeExtractor:
    """Stands in for AnthropicExtractor/OpenAICompatibleExtractor: same shape
    (name, model, problems, extract()), no HTTP call."""

    name = "fake"
    model = "fake-model"

    def __init__(self, payload_by_document_id, problems_by_document_id=None):
        self._payload_by_document_id = payload_by_document_id
        self._problems_by_document_id = problems_by_document_id or {}
        self.problems = []
        self.extracted_document_ids = []

    def extract(self, document, pages):
        self.extracted_document_ids.append(document.id)
        self.problems = self._problems_by_document_id.get(document.id, [])
        return self._payload_by_document_id[document.id]


def _document(name):
    return Document.objects.create(
        file_name=name, rel_path=f"insights/{name}", report_date="2026-03-14")


def _payload(document, quote):
    return {
        "source": {"rel_path": document.rel_path, "sha1": document.sha1, "report_date": "2026-03-14"},
        "producer": {"agent": "fake", "model": "fake-model"},
        "insights": [{
            "quote": quote,
            "page": 1,
            "voice_type": "community",
            "iso3": "TCD",
            "codings": [],
        }],
    }


def _empty_payload(document):
    return {
        "source": {"rel_path": document.rel_path, "sha1": document.sha1, "report_date": None},
        "producer": {"agent": "fake", "model": "fake-model"},
        "insights": [],
    }


class ExtractOnlyTheJobsOwnDocumentsTests(TestCase):
    def setUp(self):
        self.in_job = _document("in.pdf")
        DocumentText.objects.create(document=self.in_job, page=1, text=f"Witnesses said: {QUOTE}")
        self.not_in_job = _document("out.pdf")
        DocumentText.objects.create(document=self.not_in_job, page=1, text=f"Witnesses said: {QUOTE}")

        self.job = ExtractionJob.objects.create(producer="external", status="queued")
        self.job.documents.add(self.in_job)

    def test_a_document_not_attached_to_the_job_is_never_extracted(self):
        extractor = FakeExtractor({self.in_job.id: _payload(self.in_job, QUOTE)})

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MCP_CACHE_DIR=tmp), patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(self.job.id))

        self.assertEqual(extractor.extracted_document_ids, [self.in_job.id])
        self.job.refresh_from_db()
        self.assertEqual(self.job.documents_total, 1)
        self.assertEqual(self.job.documents_done, 1)
        self.assertEqual(self.job.status, "loaded")
        self.assertEqual(Insight.objects.filter(document=self.in_job).count(), 1)
        self.assertEqual(Insight.objects.filter(document=self.not_in_job).count(), 0)


class RefusalsAndParseFailuresReachTheJobLogTests(TestCase):
    def setUp(self):
        self.document = _document("report.pdf")
        DocumentText.objects.create(document=self.document, page=1, text=f"Witnesses said: {QUOTE}")
        self.job = ExtractionJob.objects.create(producer="external", status="queued")
        self.job.documents.add(self.document)

    def test_a_refusal_is_written_to_the_job_log_not_dropped(self):
        extractor = FakeExtractor(
            {self.document.id: _empty_payload(self.document)},
            {self.document.id: ["report.pdf page 4: refused by the model (category: sexual_content)"]},
        )

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MCP_CACHE_DIR=tmp), patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(self.job.id))

        self.job.refresh_from_db()
        self.assertIn("refused by the model", self.job.log)
        self.assertIn("sexual_content", self.job.log)

    def test_a_parse_failure_is_written_to_the_job_log_not_dropped(self):
        extractor = FakeExtractor(
            {self.document.id: _empty_payload(self.document)},
            {self.document.id: ["report.pdf page 4: the model's output was not valid JSON"]},
        )

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MCP_CACHE_DIR=tmp), patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(self.job.id))

        self.job.refresh_from_db()
        self.assertIn("not valid JSON", self.job.log)
