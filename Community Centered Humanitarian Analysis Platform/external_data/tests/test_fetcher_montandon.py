"""Montandon: the keyed source that POSTs, and whose window never narrows.

THE WINDOW IS FIXED, 15 Apr 2023 to today, on every pull. That is what the
office asked for, so since() is overridden to return None and `narrowed` is
always False - which means an empty answer stays a fault rather than becoming
"nothing new", exactly as loaders/base documents.
"""
from datetime import date
from pathlib import Path

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync

STAC = "https://montandon-eoapi-stage.ifrc.org/stac"


class RegistrationTests(TestCase):
    def test_montandon_is_registered(self):
        self.assertIsNotNone(fetcher_for("montandon", "hazard_events", ""))

    @override_settings(IFRC_API_TOKEN="")
    def test_without_the_token_nothing_is_called(self):
        self.assertEqual(
            missing_keys(fetcher_for("montandon", "hazard_events", "")),
            ["IFRC_API_TOKEN"])


@override_settings(IFRC_API_TOKEN="TESTTOKEN", MONTANDON_STAC_URL=STAC,
                   CRISIS_START="2023-04-15")
class CallShapeTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        self.calls = list(fetcher_for("montandon", "hazard_events", "")().plan(self.sync))

    def test_three_calls_events_then_severity_then_impacts(self):
        """Order is load-bearing: severity is applied onto rows that must
        already exist, and significance needs severity AND impacts."""
        self.assertEqual([c.loader_dataset for c in self.calls],
                         ["montandon_events", "montandon_severity", "montandon_impacts"])

    def test_every_call_is_a_paginated_post_to_search(self):
        for call in self.calls:
            self.assertEqual(call.url, f"{STAC}/search")
            self.assertEqual(call.method, "POST")
            self.assertTrue(call.paginated)

    def test_the_token_is_sent_as_a_header_not_a_query_parameter(self):
        for call in self.calls:
            self.assertIn("TESTTOKEN", call.headers["Authorization"])
            self.assertNotIn("TESTTOKEN", str(call.params))
            self.assertNotIn("TESTTOKEN", str(call.body))

    def test_the_window_starts_at_the_crisis_and_ends_today(self):
        for call in self.calls:
            start, end = call.body["datetime"].split("/")
            self.assertTrue(start.startswith("2023-04-15"))
            self.assertTrue(end.startswith(date.today().isoformat()))

    def test_the_filter_names_this_rows_country(self):
        for call in self.calls:
            self.assertEqual(call.body["filter"],
                             {"op": "a_contains",
                              "args": [{"property": "monty:country_codes"}, ["SDN"]]})

    def test_the_three_calls_name_the_three_collection_families(self):
        events, severity, impacts = self.calls
        self.assertEqual(events.body["collections"],
                         ["gdacs-events", "pdc-events", "idmc-idu-events"])
        self.assertEqual(severity.body["collections"], ["gdacs-hazards", "pdc-hazards"])
        self.assertEqual(impacts.body["collections"],
                         ["gdacs-impacts", "pdc-impacts", "idmc-idu-impacts"])

    def test_idmc_idu_hazards_is_never_requested_because_it_does_not_exist(self):
        self.assertNotIn("idmc-idu-hazards", self.calls[1].body["collections"])

    def test_the_severity_and_impact_calls_ask_for_their_detail_blocks(self):
        self.assertIn("properties.monty:hazard_detail",
                      self.calls[1].body["fields"]["include"])
        self.assertIn("properties.monty:impact_detail",
                      self.calls[2].body["fields"]["include"])

    def test_the_html_description_is_excluded_from_every_call(self):
        """One item carries kilobytes of Word-exported HTML. Excluding it is
        what keeps a pull a sane size on disk and in mcp_cache/."""
        for call in self.calls:
            self.assertIn("properties.description", call.body["fields"]["exclude"])

    def test_each_call_caches_under_its_own_name(self):
        self.assertEqual(self.calls[0].cache_path, Path("montandon/SDN-events.json"))
        self.assertEqual(self.calls[1].cache_path, Path("montandon/SDN-hazards.json"))
        self.assertEqual(self.calls[2].cache_path, Path("montandon/SDN-impacts.json"))


@override_settings(IFRC_API_TOKEN="TESTTOKEN", MONTANDON_STAC_URL=STAC,
                   CRISIS_START="2023-04-15")
class WindowNeverNarrowsTests(TestCase):
    def test_a_watermark_does_not_shorten_the_window(self):
        """The office asked for the whole window on every pull, so the
        inherited 90-day-lookback behaviour is deliberately switched off."""
        sync = SourceSync.objects.create(
            source="montandon", dataset="hazard_events", iso3="TCD", variant="",
            high_water_date=date(2026, 8, 1))
        calls = list(fetcher_for("montandon", "hazard_events", "")().plan(sync))
        for call in calls:
            self.assertFalse(call.narrowed)
            self.assertTrue(call.body["datetime"].startswith("2023-04-15"))

    def test_since_returns_none_so_an_empty_answer_stays_a_fault(self):
        sync = SourceSync.objects.create(
            source="montandon", dataset="hazard_events", iso3="EGY", variant="",
            high_water_date=date(2026, 8, 1))
        self.assertIsNone(fetcher_for("montandon", "hazard_events", "")().since(sync))
