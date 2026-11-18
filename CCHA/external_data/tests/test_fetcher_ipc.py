"""IPC: the diff, the period, and the two ways a naive version goes wrong.

Every expectation is derived from the real listing in the fixture (22 CAF
analyses, 2013-2026), not from numbers typed by hand.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.ipc import period_from_title
from external_data.models import SourceSync

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSES = json.loads((FIXTURES / "ipc_analyses_CAF.json").read_text(encoding="utf-8"))


class PeriodFromTitleTests(TestCase):
    """The listing carries no period date. It is in the title or nowhere."""

    def test_a_month_and_year_are_read(self):
        self.assertEqual(
            period_from_title("Central African Republic - Acute Food Insecurity September 2025"),
            date(2025, 9, 1))

    def test_an_abbreviated_month_is_read(self):
        self.assertEqual(
            period_from_title("CAR - Acute Food Insecurity Apr 2020 (Projection update)"),
            date(2020, 4, 1))

    def test_a_trailing_country_code_does_not_confuse_it(self):
        self.assertEqual(
            period_from_title("Central African Republic - Acute Food Insecurity "
                              "Analysis Update - CF May 2026"),
            date(2026, 5, 1))

    def test_a_title_with_no_month_yields_none(self):
        """None means the job stops and says which analysis. It must NEVER guess:
        a wrong period files an analysis under the wrong month silently."""
        self.assertIsNone(period_from_title("Central African Republic - CAR AFI 2013"))

    def test_a_long_month_name_wins_over_its_abbreviation(self):
        """'September' must not parse as 'Sep' and leave 'tember 2025' behind."""
        self.assertEqual(period_from_title("Analysis September 2025"), date(2025, 9, 1))


@override_settings(IPC_API_KEY="TESTKEY")
class PlanTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="CAF", variant="")
        self.fetcher = fetcher_for("ipc", "food_security", "")()

    def _plan(self):
        with patch("external_data.fetchers.ipc.http_get_json", return_value=ANALYSES):
            return list(self.fetcher.plan(self.sync))

    def test_analyses_older_than_the_crisis_start_are_not_planned(self):
        """The listing goes back to 2013. Without a floor the first press queues
        eighteen pulls of 8-15 MB each - the load that took IPC down before."""
        planned = {c.context["analysis_id"] for c in self._plan()}
        self.assertNotIn("12640404", planned)     # CAR AFI Nov-Dec 2013
        self.assertNotIn("26546456", planned)     # September 2022

    def test_the_april_2023_analysis_is_not_planned(self):
        """Created 2023-05-09, AFTER the crisis start, but it describes April
        2023, before it. The floor is applied to the PERIOD, not to `created`."""
        self.assertNotIn("56657074", {c.context["analysis_id"] for c in self._plan()})

    def test_an_analysis_already_held_is_not_planned(self):
        self.sync.known_ids = ["87143397"]
        self.sync.save(update_fields=["known_ids"])
        self.assertNotIn("87143397", {c.context["analysis_id"] for c in self._plan()})

    def test_a_skipped_analysis_is_not_planned(self):
        """The empty May 2026 one. Without this it fails on every single press."""
        self.sync.skipped_ids = [{"id": "87143421", "reason": "no geometry"}]
        self.sync.save(update_fields=["skipped_ids"])
        self.assertNotIn("87143421", {c.context["analysis_id"] for c in self._plan()})

    def test_nothing_is_planned_when_held_and_skipped_cover_everything(self):
        self.sync.known_ids = ["87143397", "82028572", "72156887", "62439499"]
        self.sync.skipped_ids = [{"id": "87143421", "reason": "no geometry"}]
        self.sync.save(update_fields=["known_ids", "skipped_ids"])
        self.assertEqual(self._plan(), [])

    def test_the_call_asks_for_the_current_period(self):
        call = self._plan()[0]
        self.assertTrue(call.url.startswith("https://api.ipcinfo.org/areas/"))
        self.assertTrue(call.url.endswith("/C"))

    def test_the_period_travels_in_the_context(self):
        call = next(c for c in self._plan() if c.context["analysis_id"] == "87143397")
        self.assertEqual(call.context["period_date"], date(2025, 9, 1))

    def test_the_cache_name_matches_the_existing_files(self):
        call = next(c for c in self._plan() if c.context["analysis_id"] == "87143397")
        self.assertEqual(call.cache_path, Path("ipc/CAF-87143397-C.geojson"))

    def test_the_listing_is_asked_for_by_iso2(self):
        with patch("external_data.fetchers.ipc.http_get_json",
                   return_value=ANALYSES) as http:
            list(self.fetcher.plan(self.sync))
        self.assertEqual(http.call_args.args[1]["country"], "CF")

    def test_the_food_security_loader_is_named(self):
        self.assertEqual(self._plan()[0].loader_dataset, "food_security")

    def test_ipc_calls_are_not_paginated(self):
        """One analysis is one GeoJSON document, not a page of rows."""
        self.assertFalse(self._plan()[0].paginated)


@override_settings(IPC_API_KEY="TESTKEY")
class ChadTests(TestCase):
    def test_the_same_fetcher_serves_cadre_harmonise(self):
        """Chad's analyses come from the IPC API under source 'ch'."""
        self.assertIsNotNone(fetcher_for("ch", "food_security", ""))


@override_settings(IPC_API_KEY="TESTKEY")
class NoteEmptyTests(TestCase):
    def _call(self):
        from external_data.fetchers.base import Call
        return Call(url="x", params={}, cache_path=Path("x"),
                    loader_dataset="food_security",
                    context={"analysis_id": "87143421",
                             "analysis_title": "CAR - Analysis Update CF May 2026"})

    def test_an_empty_analysis_is_added_to_the_skip_list_with_its_title(self):
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="CAF")
        fetcher_for("ipc", "food_security", "")().note_empty(sync, self._call())
        sync.refresh_from_db()
        self.assertEqual(sync.skipped_ids[0]["id"], "87143421")
        self.assertIn("May 2026", sync.skipped_ids[0]["reason"])

    def test_noting_the_same_analysis_twice_does_not_duplicate_it(self):
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="CAF")
        fetcher = fetcher_for("ipc", "food_security", "")()
        fetcher.note_empty(sync, self._call())
        fetcher.note_empty(sync, self._call())
        sync.refresh_from_db()
        self.assertEqual(len(sync.skipped_ids), 1)
