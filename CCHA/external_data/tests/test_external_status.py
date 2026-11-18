"""The command an analyst runs before asking for a refresh.

It is the first command of any refresh, so its job is to be readable and to be
honest about the difference between 'pulled recently' and 'holds recent data'.
"""
import json
from datetime import date, datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from external_data.models import SourceSync


class ExternalStatusTests(TestCase):
    def setUp(self):
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview",
            last_pulled_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
            high_water_date=date(2025, 12, 31), row_count=4210,
            notes="source has published nothing for 2026 yet",
        )
        SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="TCD", variant="",
            last_pulled_at=None, high_water_date=None, row_count=0,
        )

    def test_json_output_reports_every_row(self):
        out = StringIO()
        call_command("external_status", "--json", stdout=out)
        rows = json.loads(out.getvalue())
        # The two this test created. Migration 0015 seeds eight montandon rows,
        # which external_status rightly also reports.
        rows = [r for r in rows if r["source"] in ("hdx", "ipc")]
        self.assertEqual(len(rows), 2)
        by_key = {(r["source"], r["iso3"]): r for r in rows}
        self.assertEqual(by_key[("hdx", "SDN")]["high_water_date"], "2025-12-31")
        self.assertEqual(by_key[("hdx", "SDN")]["row_count"], 4210)

    def test_never_pulled_is_shown_as_never_not_as_blank(self):
        """A row that has never been pulled is the most important thing to see."""
        out = StringIO()
        call_command("external_status", stdout=out)
        text = out.getvalue()
        self.assertIn("TCD", text)
        self.assertIn("never", text.lower())

    def test_notes_are_shown_so_a_no_op_refresh_explains_itself(self):
        out = StringIO()
        call_command("external_status", stdout=out)
        self.assertIn("nothing for 2026", out.getvalue())
