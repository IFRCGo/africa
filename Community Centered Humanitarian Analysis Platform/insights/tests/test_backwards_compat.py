"""A payload written before the extraction was widened must keep working.

This file is a tripwire, not a feature test. Everything the comprehensive
extraction adds - codings[].role, figures[], movements[] - is optional, and the
day one of them stops being optional is the day every payload already sitting in
data_pipeline/mcp_cache/insights/ becomes unloadable. That failure would be
silent: a re-run would simply write fewer rows.

payload_legacy.json is frozen on purpose. Do not add new fields to it.
"""
import json
from pathlib import Path

from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.loader import load
from insights.models import Insight

FIXTURES = Path(__file__).parent / "fixtures"
QUOTE = ("When it rains we get flash floods, and with the fighting around us the "
         "hospitals are gone — we have cholera now and nowhere to take the sick.")


class LegacyPayloadTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="x.pdf", rel_path="insights/x.pdf", report_date="2026-03-14")
        DocumentText.objects.create(
            document=self.doc, page=7, text=f"Participants said: “{QUOTE}”")
        self.payload = json.loads(
            (FIXTURES / "payload_legacy.json").read_text(encoding="utf-8"))

    def test_a_payload_with_no_new_blocks_still_loads(self):
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(report.rejected_unverifiable, 0)

    def test_every_pre_existing_column_is_unchanged(self):
        load(self.payload, self.doc)
        row = Insight.objects.get()
        self.assertEqual(row.quote, QUOTE)
        self.assertEqual(row.quote_language, "en")
        self.assertEqual(row.voice_type, "community")
        self.assertEqual(row.channel, "document_ai")
        self.assertEqual(row.page, 7)
        self.assertEqual(row.iso3, "ETH")
        self.assertEqual(row.place_name_as_written, "Afar")
        self.assertEqual(row.severity, 4)
        self.assertEqual(row.confidence, "high")
        self.assertIsNone(row.people_affected)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.stated_on.isoformat(), "2026-03-14")

    def test_the_codings_are_unchanged(self):
        load(self.payload, self.doc)
        codings = set(Insight.objects.get().codings.values_list("dimension", "tag"))
        self.assertEqual(
            codings,
            {("hazard", "flooding"), ("hazard", "disease_outbreak"),
             ("need", "health"), ("need", "other")},
        )
