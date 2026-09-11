"""The four gates, and the one rule that protects a reviewer.

Gate 4 is where this loader deliberately parts company with
external_data/loaders/base.py. That one overwrites on conflict, which is right
for API data and wrong here: it would discard a reviewer's corrections on every
re-run.
"""
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.contract import ContractError
from insights.loader import load
from insights.models import ExtractionJob, Insight, InsightCoding

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

    def test_a_dateless_manual_payload_is_rejected(self):
        """No document, no source.report_date: nothing to fall back to."""
        del self.payload["source"]["report_date"]
        with self.assertRaises(ContractError):
            load(self.payload, document=None)

    def test_the_date_check_happens_before_anything_is_written(self):
        """This proves check-ordering, not rollback: the ContractError fires
        before the per-row loop starts, so no row exists whether or not the
        load is transactional. See test_a_mid_loop_failure_rolls_back_every_row
        for the actual rollback proof."""
        del self.payload["source"]["report_date"]
        with self.assertRaises(ContractError):
            load(self.payload, document=None)
        self.assertEqual(Insight.objects.count(), 0)

    def test_a_mid_loop_failure_rolls_back_every_row(self):
        """The only way to force a genuine mid-loop failure: every input-level
        problem (bad quote, bad date, bad vocabulary) is caught before the loop
        runs, so proving @transaction.atomic actually rolls back requires
        breaking something inside the loop itself - here, the coding write."""
        with patch.object(InsightCoding.objects, "bulk_create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                load(self.payload, self.doc)
        self.assertEqual(Insight.objects.count(), 0)

    def test_the_documents_report_date_is_used_when_the_payload_has_none(self):
        del self.payload["source"]["report_date"]
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(Insight.objects.get().stated_on.isoformat(), "2026-03-14")

    def test_the_payloads_report_date_wins_over_the_documents(self):
        other_doc = Document.objects.create(
            file_name="y.pdf", rel_path="insights/y.pdf", report_date="2020-01-01")
        DocumentText.objects.create(document=other_doc, page=7, text=f"Participants said: “{QUOTE}”")
        # self.payload's source.report_date is 2026-03-14, other_doc's is 2020-01-01.
        report = load(self.payload, other_doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(Insight.objects.get().stated_on.isoformat(), "2026-03-14")

    def test_a_malformed_date_string_raises_contracterror_not_valueerror(self):
        self.payload["source"]["report_date"] = "14 March 2026"
        with self.assertRaises(ContractError):
            load(self.payload, self.doc)

    def test_an_iso_timestamp_string_is_accepted_and_dated_correctly(self):
        self.payload["source"]["report_date"] = "2026-03-14T09:00:00Z"
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(Insight.objects.get().stated_on.isoformat(), "2026-03-14")

    def test_a_non_string_non_date_report_date_raises_contracterror(self):
        self.payload["source"]["report_date"] = 20260314
        with self.assertRaises(ContractError):
            load(self.payload, self.doc)

    def test_a_manual_insight_with_no_document_is_written(self):
        """document=None: gate 1 is genuinely bypassed, not accidentally
        passing - the quote below appears on no stored page anywhere."""
        self.payload["source"]["report_date"] = "2026-03-14"
        self.payload["insights"][0]["quote"] = (
            "Nothing on any stored page says this, and that is the point.")
        report = load(self.payload, document=None)
        self.assertEqual(report.written, 1)
        row = Insight.objects.get()
        self.assertEqual(row.channel, "manual")
        self.assertIsNone(row.page)
        self.assertIsNone(row.document_id)
