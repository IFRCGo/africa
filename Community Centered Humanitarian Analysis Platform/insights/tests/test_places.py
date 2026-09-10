"""Placing a statement, and being honest when we cannot.

Unmatched is a NORMAL outcome, not a failure: camps, informal settlements and
neighbourhoods are not in the boundary library and never will be. Those insights
stay off the map and keep their place name as the source wrote it.
"""
from django.test import TestCase

from boundaries.models import AdminArea, BoundarySource
from insights.places import resolve


class ResolveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # BoundarySource has exactly one required field: `path`, which is unique.
        # It has no `name` and no `kind` - `kind` lives on AdminArea.
        source = BoundarySource.objects.create(path="tests/insights-fixture")
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="ETH", country_name="Ethiopia",
            level=1, pcode="ET02", name="Afar", name_alt=["Afar Region", "Afaar"],
            center_lat=11.75, center_lon=40.95,
        )
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN", country_name="Sudan",
            level=1, pcode="SD08", name="North Darfur", name_alt=[],
            center_lat=15.5, center_lon=25.0,
        )

    def test_an_exact_name_matches_and_copies_the_label_point(self):
        self.assertEqual(resolve("ETH", "Afar"), {
            "admin_pcode": "ET02", "admin_level": 1, "match_method": "name",
            "lat": 11.75, "lon": 40.95,
        })

    def test_matching_ignores_case_and_spacing(self):
        self.assertEqual(resolve("SDN", "  north darfur ")["admin_pcode"], "SD08")

    def test_an_alternate_spelling_matches(self):
        self.assertEqual(resolve("ETH", "Afaar")["admin_pcode"], "ET02")

    def test_a_pcode_given_instead_of_a_name_matches_as_pcode(self):
        self.assertEqual(resolve("ETH", "ET02"), {
            "admin_pcode": "ET02", "admin_level": 1, "match_method": "pcode",
            "lat": 11.75, "lon": 40.95,
        })

    def test_an_unknown_place_is_unmatched_with_no_coordinates(self):
        self.assertEqual(resolve("ETH", "Kebribeyah camp"), {
            "admin_pcode": None, "admin_level": None, "match_method": "unmatched",
            "lat": None, "lon": None,
        })

    def test_the_right_name_in_the_wrong_country_does_not_match(self):
        self.assertEqual(resolve("SDN", "Afar")["match_method"], "unmatched")

    def test_no_place_name_is_unmatched(self):
        self.assertEqual(resolve("ETH", None)["match_method"], "unmatched")
