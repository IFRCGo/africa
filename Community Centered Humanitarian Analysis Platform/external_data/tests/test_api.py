"""The endpoints an analyst points Power BI at.

Same conventions as data_track/views.py: GET only, plain JsonResponse, filters as
query parameters, and a capped result set.

The test that matters most is the provenance one. The same country can be served
by providers who disagree, so every seasonal and food-security row carries the
source it came from; a response that omitted it would be telling the reader less
than the database knows.
"""
from datetime import date

from django.test import TestCase

from external_data.models import (FoodSecurityArea, MovementPattern,
                                  SeasonalCalendar, SourceSync)


class SeasonalApiTests(TestCase):
    def setUp(self):
        SeasonalCalendar.objects.create(
            iso3="TCD", country_name="Chad", source="fewsnet", label="Lean",
            season_type="Lean", purpose="NutritionIndicator",
            start_month=4, end_month=9, source_ref="TD",
        )
        SeasonalCalendar.objects.create(
            iso3="SDN", country_name="Sudan", source="fewsnet",
            label="Cold off-season harvest", season_type="Harvest",
            purpose="CropProductionIndicator",
            start_month=11, end_month=2, source_ref="SD2014A0",
        )

    def test_filtering_by_country_returns_only_that_country(self):
        data = self.client.get("/api/seasonal/?iso3=TCD").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["start_month"], 4)

    def test_every_row_says_which_provider_it_came_from(self):
        row = self.client.get("/api/seasonal/?iso3=TCD").json()["results"][0]
        self.assertEqual(row["source"], "fewsnet")
        self.assertEqual(row["source_ref"], "TD")

    def test_a_season_that_wraps_the_year_end_is_served_as_published(self):
        row = self.client.get("/api/seasonal/?iso3=SDN").json()["results"][0]
        self.assertEqual((row["start_month"], row["end_month"]), (11, 2))

    def test_a_country_with_no_calendar_returns_an_empty_list_not_a_404(self):
        """Absence is a real answer: Libya has one placeholder band, Egypt no lean."""
        resp = self.client.get("/api/seasonal/?iso3=LBY")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])


class FoodSecurityApiTests(TestCase):
    def setUp(self):
        FoodSecurityArea.objects.create(
            source="ch", analysis_id="a1", iso3="TCD", period_date=date(2025, 11, 1),
            period_type="current", area_id="1", area_title="Assoungha", phase=3,
        )
        FoodSecurityArea.objects.create(
            source="fewsnet", analysis_id="f1", iso3="ETH", period_date=date(2026, 6, 1),
            period_type="current", area_id="ET2023C1", area_title="Abaala", phase=4,
        )

    def test_the_source_distinguishes_products_that_must_not_be_pooled(self):
        """Chad's is Cadre Harmonise, Ethiopia's is FEWS NET's own judgement."""
        rows = self.client.get("/api/food-security/").json()["results"]
        by_country = {r["iso3"]: r["source"] for r in rows}
        self.assertEqual(by_country["TCD"], "ch")
        self.assertEqual(by_country["ETH"], "fewsnet")

    def test_filtering_by_source_separates_them(self):
        data = self.client.get("/api/food-security/?source=fewsnet").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["iso3"], "ETH")

    def test_min_phase_filters_to_the_areas_in_crisis_or_worse(self):
        data = self.client.get("/api/food-security/?min_phase=4").json()
        self.assertEqual([r["area"] for r in data["results"]], ["Abaala"])

    def test_geometry_is_not_returned_here(self):
        row = self.client.get("/api/food-security/").json()["results"][0]
        self.assertNotIn("geometry", row)
        self.assertNotIn("geom", row)


class MovementApiTests(TestCase):
    def setUp(self):
        for day, value in [(date(2024, 3, 1), 10), (date(2024, 1, 1), 5)]:
            MovementPattern.objects.create(
                date=day, iso3="SDN", metric="idps", value=value,
                source="hdx", population_group="idps", place_name=f"P{value}",
                admin_pcode=f"X{value}",
            )

    def test_the_series_comes_back_in_date_order(self):
        rows = self.client.get("/api/movement/?iso3=SDN&metric=idps").json()["results"]
        self.assertEqual([r["value"] for r in rows], [5, 10])

    def test_a_date_window_narrows_the_series(self):
        rows = self.client.get("/api/movement/?iso3=SDN&from=2024-02-01").json()["results"]
        self.assertEqual([r["value"] for r in rows], [10])


class SyncApiTests(TestCase):
    def test_sync_reports_the_notes_that_explain_a_gap(self):
        SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="ETH", variant="",
            notes="NO IPC analysis since May 2021 - real absence in the source.",
        )
        data = self.client.get("/api/sync/").json()
        self.assertEqual(data["count"], 1)
        self.assertIn("May 2021", data["results"][0]["notes"])


class ApiIndexTests(TestCase):
    def test_the_index_lists_the_endpoints(self):
        data = self.client.get("/api/external/").json()
        self.assertIn("food_security", data["endpoints"])
        self.assertIn("sync", data["endpoints"])

    def test_the_data_track_api_still_works(self):
        """external_data is matched first; it must not swallow the older paths."""
        self.assertEqual(self.client.get("/api/meta/").status_code, 200)
        self.assertEqual(self.client.get("/api/").status_code, 200)
