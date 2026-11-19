"""ACAPS: a keyed, paged API whose records the existing loader already reads."""
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from external_data.fetchers import base, fetcher_for
from external_data.fetchers.base import missing_keys, redact
from external_data.loaders.acaps_seasonal import AcapsSeasonalLoader
from external_data.models import SourceSync

RECORD = {
    "id": "4686", "iso": ["SDN"], "country": ["Sudan"], "country_wide": False,
    "adm1": "SDN.18_1, SDN.14_1", "adm1_eng_name": ["White Nile", "South Darfur"],
    "months": ["July", "August", "September"], "event": ["Floods"],
    "event_type": ["Seasonal hazard"], "label": ["Floods"],
    "comment": "Flood prone states", "source": "OCHA",
    "source_date": "2022-02-26", "source_link": "https://reliefweb.int/x",
}


@override_settings(ACAPS_TOKEN="secret-acaps", ACAPS_URL="https://api.acaps.org/api/v1")
class SeasonalCalendarFetcherTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="acaps", dataset="seasonal_calendar", iso3="SDN",
            variant="acaps-events")
        self.fetcher = fetcher_for("acaps", "seasonal_calendar", "acaps-events")()

    def test_it_is_registered_under_the_rows_variant(self):
        """The loader's sync_key writes variant 'acaps-events'; the fetcher must
        be found under the same key or the row never gets a button."""
        self.assertEqual(
            AcapsSeasonalLoader().sync_key("SDN")["variant"], self.fetcher.variant)

    @override_settings(ACAPS_TOKEN="")
    def test_it_refuses_without_the_token(self):
        self.assertEqual(missing_keys(type(self.fetcher)), ["ACAPS_TOKEN"])

    def test_one_paged_call_filtered_by_country(self):
        calls = list(self.fetcher.plan(self.sync))
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(
            call.url,
            "https://api.acaps.org/api/v1/seasonal-events-calendar/seasonal-calendar/")
        self.assertEqual(call.params, {"iso": "SDN"})
        self.assertTrue(call.paginated)
        self.assertEqual(call.pager, "next_url")
        self.assertFalse(call.narrowed)
        self.assertEqual(call.loader_dataset, "acaps_seasonal")
        self.assertEqual(call.cache_path, Path("acaps_seasonal/SDN.json"))

    def test_the_token_is_in_the_header_not_the_url(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.headers, {"Authorization": "Token secret-acaps"})
        self.assertNotIn("secret-acaps", call.url + str(call.params))

    def test_the_regional_row_asks_for_everything(self):
        self.sync.iso3 = None
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.params, {})
        self.assertEqual(call.cache_path, Path("acaps_seasonal/all.json"))

    def test_the_token_is_redacted_from_errors(self):
        self.assertNotIn("secret-acaps", redact("401 for Token secret-acaps"))

    def test_pages_are_followed_and_the_loader_reads_the_result(self):
        pages = [
            {"count": 2, "next": "https://api.acaps.org/next?page=2", "results": [RECORD]},
            {"count": 2, "next": None, "results": [dict(RECORD, id="4687")]},
        ]
        call = next(iter(self.fetcher.plan(self.sync)))
        with mock.patch.object(base, "http_get_json", side_effect=pages) as get:
            payload = base.fetch(call)
        self.assertEqual(get.call_count, 2)
        for args in get.call_args_list:
            self.assertEqual(args.kwargs["headers"]["Authorization"], "Token secret-acaps")
        rows = AcapsSeasonalLoader().parse(payload, "SDN")
        self.assertEqual([r["source_ref"] for r in rows], ["4686", "4687"])
        self.assertEqual(rows[0]["season_type"], "Hazard")
        self.assertEqual(rows[0]["months"], [7, 8, 9])
