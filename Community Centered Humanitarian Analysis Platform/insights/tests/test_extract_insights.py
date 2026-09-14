"""The command that runs an in-container extraction and loads its result.

The extractor is always mocked here - no network call, no real model, no real
anthropic/openai_compatible adapter. What is worth testing at this layer is
the wiring: that a job extracts ONLY its own documents (R13a - without this a
job for one folder would silently re-extract every other folder's documents
too), that a refusal or a parse failure the adapter recorded lands in the
job's own log, not dropped and not raised (task-13-rulings.md §2-4), that a
transport/SDK failure the adapter let propagate ends the job "failed" rather
than wedging it at "running" (fix-round, 2026-09-14), and that a re-run does
not accumulate documents_done across runs (§5 sanctions re-running a job on
purpose).
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
    (name, model, problems, extract()), no HTTP call.

    `raise_by_document_id` models a transport/SDK failure the way both real
    adapters now behave: `self.problems` is set to whatever chunks had
    already been recorded BEFORE the failure (mirroring a real extract()
    call that dies partway through its chunk loop), and then the exception
    is raised - it is never turned into an ordinary problem entry.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, payload_by_document_id=None, problems_by_document_id=None,
                 raise_by_document_id=None):
        self._payload_by_document_id = payload_by_document_id or {}
        self._problems_by_document_id = problems_by_document_id or {}
        self._raise_by_document_id = raise_by_document_id or {}
        self.problems = []
        self.extracted_document_ids = []

    def extract(self, document, pages):
        self.extracted_document_ids.append(document.id)
        self.problems = self._problems_by_document_id.get(document.id, [])
        if document.id in self._raise_by_document_id:
            raise self._raise_by_document_id[document.id]
        return self._payload_by_document_id[document.id]


def _document(name):
    # source_collection and family mirror what insights.intake.catalogue_file()
    # actually writes (task-13 fix-round review) - so the R13a isolation test
    # below fails for the illustrative reason (the scoping regressed to "every
    # insights-collection document") rather than by accident (the two
    # documents happening to differ on some other attribute).
    return Document.objects.create(
        file_name=name, rel_path=f"insights/{name}", report_date="2026-03-14",
        source_collection="insights", family="insight_source")


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


class TransportFailureTests(TestCase):
    """fix-round, 2026-09-14: a transport/SDK failure that an adapter let
    propagate (rather than swallowing as a chunk problem - see the
    "TRANSPORT VS RESPONSE-SHAPE ERRORS" note in each adapter module) must
    end the job "failed", never leave it at "running" - a job stuck at
    "running" is refused forever by run_extraction_now's double-click guard.
    """

    def setUp(self):
        self.document = _document("report.pdf")
        DocumentText.objects.create(document=self.document, page=1, text=f"Witnesses said: {QUOTE}")
        self.job = ExtractionJob.objects.create(producer="external", status="queued")
        self.job.documents.add(self.document)

    def test_a_transport_failure_ends_the_job_failed_not_running(self):
        extractor = FakeExtractor(
            raise_by_document_id={self.document.id: ConnectionError("connection reset")})

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MCP_CACHE_DIR=tmp), patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "failed")
        self.assertNotEqual(self.job.status, "running")
        self.assertIsNotNone(self.job.finished_at)
        # (h): only the exception's type and message, never a raw traceback
        # or a repr of the request/response object.
        self.assertIn("ConnectionError", self.job.log)
        self.assertIn("connection reset", self.job.log)

    def test_problems_recorded_before_a_later_failure_still_reach_the_log(self):
        """The chunks that succeeded before the one that killed the call are
        not lost with it - flushed to job.log before the exception is
        allowed to end the run (task-13-rulings.md §2: never a silent loss,
        now proven across a mid-document crash too, not just a clean
        document boundary)."""
        extractor = FakeExtractor(
            problems_by_document_id={
                self.document.id: ["report.pdf page 2: refused by the model"],
            },
            raise_by_document_id={self.document.id: ConnectionError("connection reset")},
        )

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MCP_CACHE_DIR=tmp), patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(self.job.id))

        self.job.refresh_from_db()
        self.assertIn("refused by the model", self.job.log)
        self.assertIn("ConnectionError", self.job.log)


class RerunResetsDocumentsDoneTests(TestCase):
    def test_a_rerun_does_not_accumulate_progress_counters(self):
        """§5 sanctions re-running the SAME job on purpose (e.g. with a
        better model). documents_done and insights_proposed are the only
        per-run progress numbers on ExtractionJobAdmin's changelist - a
        second run of a 1-document, 1-insight job showing "2 of 1" and
        insights_proposed=2 would be actively misleading, not just untidy.
        insights_rejected_unverifiable and insights_skipped_reviewed are the
        same bug for the same reason (the model's own docstring calls
        insights_rejected_unverifiable "a direct per-run measurement")."""
        document = _document("report.pdf")
        DocumentText.objects.create(document=document, page=1, text=f"Witnesses said: {QUOTE}")
        job = ExtractionJob.objects.create(producer="external", status="queued")
        job.documents.add(document)

        extractor = FakeExtractor({document.id: _payload(document, QUOTE)})

        with tempfile.TemporaryDirectory() as tmp, override_settings(MCP_CACHE_DIR=tmp):
            with patch(GET_EXTRACTOR, return_value=extractor):
                call_command("extract_insights", "--job", str(job.id))
                job.refresh_from_db()
                self.assertEqual(job.documents_done, 1)
                self.assertEqual(job.insights_proposed, 1)

                call_command("extract_insights", "--job", str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.documents_done, 1)
        self.assertEqual(job.documents_total, 1)
        self.assertEqual(job.insights_proposed, 1)
        self.assertEqual(job.insights_rejected_unverifiable, 0)
        self.assertEqual(job.insights_skipped_reviewed, 0)
