"""The Humanitarian Service Point mapping, into one queryable table.

The parsers are pure functions over sheet rows, so these build small sheets in
memory rather than depending on the real export, which lives outside the repository
and is replaced whenever the form is re-exported.

The behaviour worth protecting is the history: date_reported is part of the natural
key, so a later export sits beside the earlier one instead of overwriting it. That
is what makes "did this district stop offering health?" answerable.
"""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from external_data.loaders.hsp import (export_date, parse_country_rows,
                                       parse_location_rows)
from external_data.management.commands.load_hsps import resolve_places
from external_data.models import HumanitarianServicePoint, PlaceCoordinate

SVC = "Services offered (applies to ALL locations)/"
DIS = "Districts where these services are offered/"
LOC = "Services offered at THIS location/"


def main_sheet(body):
    header = [
        "Country", "Are the SAME services offered across all HSP's?",
        "How many humanitarian service points (HSPs) are there?",
        SVC + "Health", SVC + "Shelter",
        DIS + "Assoungha", DIS + "Ouaddai", "_uuid",
    ]
    return [header] + body


class ExportDateTests(TestCase):
    def test_the_date_comes_from_the_export_filename(self):
        name = ("Humanitarian_Service_Points_Mapping_-_all_versions_-_labels"
                "_-_2026-09-08-11-46-14.xlsx")
        self.assertEqual(export_date(name), date(2026, 9, 8))

    def test_a_filename_with_no_timestamp_yields_none_rather_than_today(self):
        """Silently dating an import 'today' would falsify the history."""
        self.assertIsNone(export_date("HSP_mapping_final.xlsx"))


class CountryRowTests(TestCase):
    def test_services_and_districts_become_their_cross_product(self):
        rows = parse_country_rows(
            main_sheet([["Chad", "Yes", None, 1, 1, 1, 0, "u-1"]]),
            "export.xlsx", date(2026, 9, 8),
        )
        self.assertEqual(len(rows), 2)          # 2 services x 1 district
        self.assertEqual({r["service"] for r in rows}, {"Health", "Shelter"})
        self.assertEqual({r["location_name"] for r in rows}, {"Assoungha"})
        self.assertTrue(all(r["iso3"] == "TCD" for r in rows))
        self.assertTrue(all(r["scope"] == "country-wide" for r in rows))

    def test_an_unticked_service_produces_no_row(self):
        rows = parse_country_rows(
            main_sheet([["Chad", "Yes", None, 1, 0, 1, 0, "u-1"]]),
            "export.xlsx", date(2026, 9, 8),
        )
        self.assertEqual([r["service"] for r in rows], ["Health"])

    def test_a_country_answering_no_is_left_to_the_location_sheet(self):
        """Emitting both shapes would double-count South Sudan."""
        rows = parse_country_rows(
            main_sheet([["South Sudan", "No", 3, 1, 1, 1, 1, "u-2"]]),
            "export.xlsx", date(2026, 9, 8),
        )
        self.assertEqual(rows, [])


class LocationRowTests(TestCase):
    def test_a_named_location_takes_its_country_from_the_parent_submission(self):
        main = main_sheet([["South Sudan", "No", 3, 0, 0, 0, 0, "u-2"]])
        loc = [
            ["Province / Region", "District", LOC + "Health", LOC + "Shelter",
             "_parent_index", "_submission__uuid"],
            ["Upper Nile", "Renk", 1, 0, 1, "u-2"],
        ]
        rows = parse_location_rows(loc, main, "export.xlsx", date(2026, 9, 8))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["country"], "South Sudan")
        self.assertEqual(rows[0]["iso3"], "SSD")
        self.assertEqual(rows[0]["location_name"], "Renk")
        self.assertEqual(rows[0]["service"], "Health")
        self.assertEqual(rows[0]["scope"], "named-location")
        self.assertIs(rows[0]["same_services_everywhere"], False)


class HistoryTests(TestCase):
    """date_reported is in the natural key so exports accumulate, not overwrite."""

    def _row(self, reported, **kw):
        base = dict(
            date_reported=reported, country="Chad", iso3="TCD", service="Health",
            scope="country-wide", location_name="Assoungha", admin_pcode="TD1101",
            admin_level=2, match_method="name", lat=13.9, lon=22.1,
            same_services_everywhere=True, source_file="export.xlsx",
        )
        base.update(kw)
        return HumanitarianServicePoint.objects.create(**base)

    def test_a_later_export_sits_beside_the_earlier_one(self):
        self._row(date(2026, 9, 8))
        self._row(date(2026, 12, 1))
        self.assertEqual(HumanitarianServicePoint.objects.count(), 2)

    def test_the_same_export_loaded_twice_updates_in_place(self):
        self._row(date(2026, 9, 8))
        HumanitarianServicePoint.objects.update_or_create(
            date_reported=date(2026, 9, 8), iso3="TCD", service="Health",
            location_name="Assoungha", defaults={"match_method": "pcode"},
        )
        self.assertEqual(HumanitarianServicePoint.objects.count(), 1)
        self.assertEqual(HumanitarianServicePoint.objects.get().match_method, "pcode")

    def test_a_district_that_stopped_offering_a_service_is_visible_as_absence(self):
        """The question this table exists to answer."""
        self._row(date(2026, 9, 8))
        self._row(date(2026, 9, 8), service="Shelter")
        self._row(date(2026, 12, 1))            # Shelter not reported this time

        def services_on(day):
            return set(HumanitarianServicePoint.objects
                       .filter(date_reported=day, location_name="Assoungha")
                       .values_list("service", flat=True))

        self.assertEqual(services_on(date(2026, 9, 8)), {"Health", "Shelter"})
        self.assertEqual(services_on(date(2026, 12, 1)), {"Health"})


class PlaceCoordinateTests(TestCase):
    """Two of Egypt's 'districts' are border reception points, not polygons.

    Qustul and Arkeen are the Egyptian side of the two Sudan crossings. Nothing
    in the boundary library carries either name, so pcode and name lookups can
    never place them and the rows sat at lat=None - which build_hsps() excludes,
    so neither had ever been drawn.

    place_coordinates is the last fallback, and it has to be a TABLE rather than
    a coordinate on the service-point row: lat/lon are in UPDATE_FIELDS, so a
    value written onto the row would be nulled by the next load_hsps, and a
    newer export makes fresh rows under a new date_reported with nothing on them
    at all.
    """

    def setUp(self):
        PlaceCoordinate.objects.create(
            iso3="EGY", name="Qustul", lat=22.233333, lon=31.616667,
            note="Border reception point, not a district.",
        )

    def _row(self, name):
        return {
            "iso3": "EGY", "location_name": name, "admin_pcode": None,
            "admin_level": None, "match_method": "unmatched",
            "lat": None, "lon": None,
        }

    def test_a_place_with_a_coordinate_row_is_placed_from_it(self):
        rows = [self._row("Qustul")]
        unmatched = resolve_places(rows)

        self.assertEqual(unmatched, [])
        self.assertAlmostEqual(rows[0]["lat"], 22.233333, places=5)
        self.assertAlmostEqual(rows[0]["lon"], 31.616667, places=5)

    def test_the_placement_says_it_is_a_point_not_a_polygon(self):
        """match_method is what stops the popup calling these district centroids."""
        rows = [self._row("Qustul")]
        resolve_places(rows)
        self.assertEqual(rows[0]["match_method"], "manual")
        self.assertIsNone(rows[0]["admin_pcode"])
        self.assertIsNone(rows[0]["admin_level"])

    def test_the_name_matches_however_the_export_cases_it(self):
        """The form's spelling is not guaranteed to match the typed-in row's."""
        rows = [self._row("QUSTUL")]
        self.assertEqual(resolve_places(rows), [])
        self.assertAlmostEqual(rows[0]["lat"], 22.233333, places=5)

    def test_a_correction_typed_into_the_table_reaches_the_next_load(self):
        """The whole reason this is a table: the loader rewrites lat/lon every run."""
        PlaceCoordinate.objects.filter(name="Qustul").update(lat=22.5, lon=31.5)
        rows = [self._row("Qustul")]
        resolve_places(rows)
        self.assertEqual((rows[0]["lat"], rows[0]["lon"]), (22.5, 31.5))

    def test_a_place_with_no_row_is_still_reported_unmatched(self):
        """The fallback is the table's contents, not a blanket 'stop complaining'."""
        rows = [self._row("Arkeen")]
        self.assertEqual(resolve_places(rows), ["EGY:Arkeen"])
        self.assertIsNone(rows[0]["lat"])

    def test_a_coordinate_does_not_leak_across_countries(self):
        """iso3 is half the key: a Sudanese 'Qustul' is not this one."""
        rows = [dict(self._row("Qustul"), iso3="SDN")]
        self.assertEqual(resolve_places(rows), ["SDN:Qustul"])
        self.assertIsNone(rows[0]["lat"])


class PlaceCoordinateSeedTests(TestCase):
    """Re-seeding must not undo a coordinate corrected in the admin.

    The other three seeds in seed_external restore their dictionary over the
    table, which is right for rows a loader owns. This table exists so a person
    can fix a coordinate, so the dictionary cannot be allowed to win - otherwise
    it is the authority again and the table is only a cache of it.
    """

    def test_seeding_fills_an_empty_table(self):
        call_command("seed_external", stdout=StringIO())
        self.assertTrue(
            PlaceCoordinate.objects.filter(iso3="EGY", name="Qustul").exists())

    def test_seeding_again_leaves_a_corrected_coordinate_alone(self):
        call_command("seed_external", stdout=StringIO())
        PlaceCoordinate.objects.filter(name="Qustul").update(lat=22.5, lon=31.5)

        call_command("seed_external", stdout=StringIO())

        p = PlaceCoordinate.objects.get(iso3="EGY", name="Qustul")
        self.assertEqual((p.lat, p.lon), (22.5, 31.5))
