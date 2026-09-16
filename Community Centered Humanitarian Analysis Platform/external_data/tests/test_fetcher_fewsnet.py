"""FEWS NET: no key, one call, and the ISO2 trap.

source_sync keys countries on ISO3. FEWS NET's API takes ISO 3166-1 alpha-2. The
map already exists in the seasonal loader and is imported, not re-typed.
"""
from pathlib import Path

from django.test import TestCase

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync


class SeasonsFetcherTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")
        self.fetcher = fetcher_for("fewsnet", "seasonal_calendar", "")()

    def test_it_is_registered_for_the_row(self):
        self.assertIsNotNone(fetcher_for("fewsnet", "seasonal_calendar", ""))

    def test_it_needs_no_key(self):
        self.assertEqual(missing_keys(type(self.fetcher)), [])

    def test_one_call_is_planned(self):
        self.assertEqual(len(list(self.fetcher.plan(self.sync))), 1)

    def test_the_call_asks_fdw_for_the_iso2_country(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.url, "https://fdw.fews.net/api/season/")
        self.assertEqual(call.params["country_code"], "TD")
        self.assertEqual(call.params["page_size"], 50)

    def test_the_payload_is_cached_per_country(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.cache_path, Path("fewsnet_seasons/TCD.json"))

    def test_it_names_the_seasonal_calendar_loader(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.loader_dataset, "seasonal_calendar")

    def test_an_unmapped_country_raises_rather_than_guessing(self):
        """A two-letter code is not derivable from a three-letter one. Guessing
        would send a valid-looking request for the wrong country."""
        self.sync.iso3 = "ZZZ"
        with self.assertRaises(KeyError):
            list(self.fetcher.plan(self.sync))


class PhasesFetcherTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="food_security", iso3="ETH",
            variant="fewsnet-phases")
        self.fetcher = fetcher_for("fewsnet", "food_security", "fewsnet-phases")()

    def test_the_variant_is_part_of_the_registry_key(self):
        """Without the variant in the key this row resolves to nothing, because
        its dataset is 'food_security' while its loader's is 'fewsnet_phases'."""
        self.assertIsNotNone(fetcher_for("fewsnet", "food_security", "fewsnet-phases"))
        self.assertIsNone(fetcher_for("fewsnet", "food_security", ""))

    def test_it_names_the_fewsnet_phases_loader_not_its_own_dataset(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.loader_dataset, "fewsnet_phases")

    def test_it_asks_for_phases_from_the_crisis_start(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.url, "https://fdw.fews.net/api/ipcphase/")
        self.assertEqual(call.params["country_code"], "ET")
        self.assertEqual(call.params["start_date"], "2023-04-15")
