"""The four gates, and the one rule that protects a reviewer.

Gate 4 is where this loader deliberately parts company with
external_data/loaders/base.py. That one overwrites on conflict, which is right
for API data and wrong here: it would discard a reviewer's corrections on every
re-run.
"""
import json
from pathlib import Path

from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.loader import load
from insights.models import ExtractionJob, Insight

FIXTURES = Path(__file__).parent / "fixtures"
QUOTE = ("When it rains we get flash floods, and with the fighting around us the "
         "hospitals are gone — we have cholera now and nowhere to take the sick.")


class LoaderTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="x.pdf", rel_path="insights/x.pdf", report_date="2026-03-14")
        DocumentText.objects.create(document=self.doc, page=7, text=f"Participants said: “{QUOTE}”")
        self.payload = json.loads((FIXTURES / "payload_ok.json").read_text(encoding="utf-8"))

    def test_a_verifiable_insight_is_written_as_pending(self):
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        row = Insight.objects.get()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.document_id, self.doc.id)
        self.assertEqual(row.page, 7)
        self.assertEqual(row.stated_on.isoformat(), "2026-03-14")

    def test_the_codings_are_written(self):
        load(self.payload, self.doc)
        codings = set(Insight.objects.get().codings.values_list("dimension", "tag"))
        self.assertIn(("hazard", "flooding"), codings)
        self.assertIn(("need", "other"), codings)

    def test_an_invented_quote_is_rejected_and_counted(self):
        self.payload["insights"][0]["quote"] = "We were promised boreholes and none came."
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 0)
        self.assertEqual(report.rejected_unverifiable, 1)
        self.assertEqual(Insight.objects.count(), 0)

    def test_loading_twice_writes_one_row(self):
        load(self.payload, self.doc)
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.count(), 1)

    def test_a_pending_row_is_updated_by_a_rerun(self):
        """The loader still owns a row no human has touched."""
        load(self.payload, self.doc)
        self.payload["insights"][0]["severity"] = 2
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.get().severity, 2)

    def test_a_published_row_is_never_overwritten(self):
        load(self.payload, self.doc)
        Insight.objects.update(status="published", severity=5)
        self.payload["insights"][0]["severity"] = 1
        report = load(self.payload, self.doc)
        self.assertEqual(report.skipped_reviewed, 1)
        row = Insight.objects.get()
        self.assertEqual(row.severity, 5)
        self.assertEqual(row.status, "published")

    def test_the_place_is_resolved_or_left_unmatched(self):
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.get().match_method, "unmatched")

    def test_job_counters_are_written(self):
        job = ExtractionJob.objects.create(producer="external")
        self.payload["insights"].append(dict(self.payload["insights"][0],
                                             quote="An invented sentence."))
        load(self.payload, self.doc, job=job)
        job.refresh_from_db()
        self.assertEqual(job.insights_proposed, 2)
        self.assertEqual(job.insights_rejected_unverifiable, 1)
