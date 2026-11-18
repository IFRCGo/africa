"""The returnee layer file, built from the database like every other s06 output."""
import json
import pathlib
import tempfile
from datetime import date

from django.test import TestCase

from boundaries.models import AdminArea, BoundarySource
from data_pipeline.steps import s06_mcp_layers as s06
from external_data.models import DisplacementBreakdown, MovementPattern


def admin_areas():
    """The centroids the builder joins on.

    The real boundary library is loaded by `manage.py load_boundaries` into the
    deployment database; the test database starts empty, so a builder test has
    to supply the handful of rows it joins against or every locality reads as
    "without a centroid".
    """
    source = BoundarySource.objects.create(path="test/fixture.shp")
    for level, pcode, name, lon, lat in [
            (1, "SD09", "White Nile", 32.35, 13.59),
            (1, "SD03", "South Darfur", 24.31, 10.89),
            (1, "SD15", "Aj Jazirah", 33.28, 14.51),
            (2, "SD09045", "Um Rimta", 31.88, 14.61)]:
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN",
            country_name="Sudan", level=level, pcode=pcode, name=name,
            name_alt=[], center_lon=lon, center_lat=lat)


def movement(pcode, name, on, value, level=2):
    MovementPattern.objects.create(
        date=on, iso3="SDN", admin_pcode=pcode, admin_level=level,
        place_name=name, metric="returnees", population_group="returnees",
        value=value, unit="individuals", source="dtm",
        source_dataset="iom-dtm-snapshot", reference_period_end=on)


def cell(pcode, on, key, value, dimension="displaced_in"):
    DisplacementBreakdown.objects.create(
        date=on, iso3="SDN", metric="returnees", dest_pcode=pcode, dest_level=2,
        dimension=dimension, key=key, value=value, source="dtm",
        source_dataset="iom-dtm-snapshot")


class BuildReturneeLocalitiesTests(TestCase):
    def setUp(self):
        admin_areas()
        # Two dates for one locality, so the layer has something to animate.
        for on, total, outside, sd03 in [(date(2026, 6, 30), 40000, 10000, 30000),
                                         (date(2026, 7, 28), 60680, 17270, 29890)]:
            movement("SD09045", "Um Rimta", on, total)
            cell("SD09045", on, "OUTSIDE_SDN", outside)
            cell("SD09045", on, "SD03", sd03)
        cell("SD09045", date(2026, 7, 28), "SD15", 13520)
        # Households must not reach the map as an origin.
        cell("SD09045", date(2026, 7, 28), "total", 12165, dimension="households")

        # s06's dump() writes to the module-global DASHBOARD_DATA, so the test
        # redirects it at a temp folder and puts it back afterwards. Writing
        # into the real dashboard/data/ from a test would overwrite a file the
        # running site is serving.
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.real_data_dir = s06.DASHBOARD_DATA
        s06.DASHBOARD_DATA = self.tmp
        self.addCleanup(setattr, s06, "DASHBOARD_DATA", self.real_data_dir)

    def build(self):
        s06.build_returnee_localities()
        return json.loads(
            (self.tmp / "returnee_localities.json").read_text(encoding="utf-8"))

    def test_one_entry_per_locality(self):
        out = self.build()
        self.assertEqual(len(out["localities"]), 1)
        self.assertEqual(out["localities"][0]["pcode"], "SD09045")

    def test_the_series_carries_the_total_and_the_outside_share_apart(self):
        latest = self.build()["localities"][0]["series"][-1]
        self.assertEqual(latest["date"], "2026-07-28")
        self.assertEqual(latest["value"], 60680)
        self.assertEqual(latest["outside"], 17270)

    def test_pcode_origins_go_to_from_and_outside_sudan_does_not(self):
        """OUTSIDE_SDN has no centroid because it is not a place. A builder
        that joined every key to `states` would drop the one number this
        feature exists to show."""
        latest = self.build()["localities"][0]["series"][-1]
        self.assertEqual(latest["from"], {"SD03": 29890, "SD15": 13520})
        self.assertNotIn("OUTSIDE_SDN", latest["from"])

    def test_households_never_reach_the_map(self):
        latest = self.build()["localities"][0]["series"][-1]
        self.assertNotIn("total", latest["from"])

    def test_peaks_are_recorded_for_both_sizings(self):
        locality = self.build()["localities"][0]
        self.assertEqual(locality["peak"], 60680)
        self.assertEqual(locality["peak_outside"], 17270)

    def test_the_citation_iom_requires_is_in_the_source_line(self):
        out = self.build()
        self.assertIn("IOM", out["source"])
        self.assertIn("DTM", out["source"])

    def test_nothing_held_writes_an_empty_file_rather_than_none(self):
        """The dashboard preloads this file at first paint, so it must exist
        even before the first pull - a 404 there breaks loadData()."""
        MovementPattern.objects.all().delete()
        out = self.build()
        self.assertEqual(out["localities"], [])
        self.assertEqual(out["states"], {})

    def test_admin1_state_totals_are_not_drawn_beside_their_own_localities(self):
        """The layer is admin2. DTM publishes a state total AND the localities
        inside it, and both carry a p-code - so an unfiltered builder draws
        Khartoum's 2.5m state bubble on top of the Khartoum localities that
        make it up, double-counting the same people on the same map."""
        movement("SD09", "White Nile", date(2026, 7, 28), 234485, level=1)
        cell("SD09", date(2026, 7, 28), "OUTSIDE_SDN", 71641)
        out = self.build()
        levels = {L["pcode"] for L in out["localities"]}
        self.assertNotIn("SD09", levels)
        self.assertEqual(levels, {"SD09045"})

    def test_households_ride_beside_the_series_not_inside_from(self):
        """A second unit of the same observation, not an origin. Listing
        'total' beside White Nile would read as a place."""
        latest = self.build()["localities"][0]["series"][-1]
        self.assertEqual(latest["households"], 12165)
        self.assertNotIn("total", latest["from"])
