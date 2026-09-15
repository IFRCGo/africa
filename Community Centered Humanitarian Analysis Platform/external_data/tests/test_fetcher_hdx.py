"""HDX HAPI: the keyed source, and the one that paginates.

HAPI's `limit` defaults to 100. Sudan's IDP series is 5,686 rows. A fetcher that
takes the first page loads 100 rows over the top of 5,686 and calls it a refresh.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.fetchers.hdx import PAGE_SIZE, fetch_all_pages
from external_data.models import SourceSync


class RegistrationTests(TestCase):
    def test_idps_is_registered_under_its_variant(self):
        self.assertIsNotNone(fetcher_for("hdx", "idps", "admin2-overview"))

    def test_refugees_is_registered_under_source_unhcr(self):
        """The figures are UNHCR's and the row says so; the API is HDX HAPI's."""
        self.assertIsNotNone(fetcher_for("unhcr", "refugees", ""))

    @override_settings(HDX_API_TOKEN="")
    def test_both_need_the_hdx_token_even_the_unhcr_one(self):
        self.assertEqual(missing_keys(fetcher_for("hdx", "idps", "admin2-overview")),
                         ["HDX_API_TOKEN"])
        self.assertEqual(missing_keys(fetcher_for("unhcr", "refugees", "")),
                         ["HDX_API_TOKEN"])


@override_settings(HDX_API_TOKEN="TESTTOKEN")
class CallShapeTests(TestCase):
    def test_idps_asks_for_admin_level_2(self):
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.url,
                         "https://hapi.humdata.org/api/v1/affected-people/idps")
        self.assertEqual(call.params["location_code"], "SDN")
        self.assertEqual(call.params["admin_level"], 2)
        self.assertEqual(call.cache_path, Path("hdx_idps/SDN-admin2-overview.json"))

    def test_idps_asks_only_for_baseline_assessments(self):
        """Every one of the 5,686 rows already held is a Baseline assessment.
        Without this filter a refresh also pulls DTM's ETT and SA rounds, which
        the loader would ADD to the series - silently inflating the figures."""
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.params["assessment_type"], "BA")

    def test_refugees_asks_for_sudanese_origin(self):
        """RefugeeLoader files these as population_group 'sudanese_refugees'. The
        request must actually be for people originating in Sudan, or the label
        is a lie about someone else's figures."""
        sync = SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        call = next(iter(fetcher_for("unhcr", "refugees", "")().plan(sync)))
        self.assertEqual(call.params["origin_location_code"], "SDN")
        self.assertEqual(call.params["asylum_location_code"], "TCD")

    def test_the_token_travels_with_the_request(self):
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.params["app_identifier"], "TESTTOKEN")

    def test_both_calls_are_marked_paginated(self):
        """The flag is what makes the runner follow the pages at all."""
        idps = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        refs = SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        self.assertTrue(
            next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(idps))).paginated)
        self.assertTrue(
            next(iter(fetcher_for("unhcr", "refugees", "")().plan(refs))).paginated)


class PaginationTests(TestCase):
    def test_pages_are_followed_until_a_short_one(self):
        pages = [
            {"data": [{"n": i} for i in range(PAGE_SIZE)]},
            {"data": [{"n": i} for i in range(PAGE_SIZE)]},
            {"data": [{"n": 1}, {"n": 2}]},
        ]
        with patch("external_data.fetchers.hdx.http_get_json", side_effect=pages) as http:
            result = fetch_all_pages("https://example.org", {"a": 1})
        self.assertEqual(len(result["data"]), PAGE_SIZE * 2 + 2)
        self.assertEqual(http.call_count, 3)

    def test_the_offset_advances_by_a_page_each_time(self):
        pages = [{"data": [{"n": i} for i in range(PAGE_SIZE)]}, {"data": []}]
        with patch("external_data.fetchers.hdx.http_get_json", side_effect=pages) as http:
            fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_args_list[0].args[1]["offset"], 0)
        self.assertEqual(http.call_args_list[1].args[1]["offset"], PAGE_SIZE)

    def test_one_short_page_is_a_single_call(self):
        with patch("external_data.fetchers.hdx.http_get_json",
                   return_value={"data": [{"n": 1}]}) as http:
            result = fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_count, 1)
        self.assertEqual(len(result["data"]), 1)

    def test_an_empty_first_page_returns_empty_rather_than_looping(self):
        """Empty is the loader's business - it must reach EmptyPayload, not spin."""
        with patch("external_data.fetchers.hdx.http_get_json",
                   return_value={"data": []}) as http:
            result = fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["data"], [])
