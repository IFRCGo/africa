"""The codebook reaches the tag rows, and then the dashboard files.

THESE TESTS NEVER TOUCH dashboard/data/. build_hazards() and
build_hazard_events() write through dump(), which writes into DASHBOARD_DATA -
so the module-level name s06 resolved at import is redirected at a temporary
directory for the duration of each test. Without that, running the suite would
overwrite the real dashboard with two-row fixtures.
"""
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from data_pipeline.steps.s06_mcp_layers import build_hazard_events, build_hazards
from boundaries.models import AdminArea, BoundarySource
from data_track.models import NarrativeTag
from external_data.models import HazardEvent, HazardImpact
from insights.models import Insight, InsightCoding

_DASH = None


def read_dash(name):
    return json.loads((_DASH / name).read_text(encoding="utf-8"))


class DashboardSandbox(TestCase):
    """Point dump() at a scratch directory, and put the real one back after."""

    def setUp(self):
        global _DASH
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _DASH = Path(tmp.name)
        patcher = patch("data_pipeline.steps.s06_mcp_layers.DASHBOARD_DATA", _DASH)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The exporter reads country names out of the boundary library, so the
        # strings it writes match the ones tags.json already carries. Without
        # these two rows it would fall back to the ISO3 code and the country
        # filter on the dashboard would never match.
        source = BoundarySource.objects.create(path="test/countries.shp")
        for iso3, name in (("SDN", "Sudan"), ("SSD", "South Sudan")):
            AdminArea.objects.create(
                source=source, kind=AdminArea.KIND_ADMIN, iso3=iso3,
                country_name=name, level=0, pcode=f"{iso3}-ADM0",
                name=name, name_alt=[])
        super().setUp()


class TagStampingTests(TestCase):
    """Every hazard tag carries its codebook category, stamped at parse time.

    Derived rather than curated: s03_parse deletes and rebuilds narrative_tags
    on every run, so a category written into the table by hand would not
    survive the next pass. The codebook file is the place to change one.
    """

    def test_a_hazard_tag_carries_its_codebook_category(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "flooding"),
                         {"hazard_category": "hydrological", "hazard_sub": "flooding"})

    def test_a_conflict_tag_lands_in_the_project_category(self):
        """The codebook excludes armed conflict from man-made hazards, but six
        of the ten tags are conflict tags and they are most of the reporting."""
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "armed_conflict"),
                         {"hazard_category": "conflict_violence",
                          "hazard_sub": "armed_conflict"})

    def test_a_need_has_no_hazard_category(self):
        """Null, not empty string - an empty string reads as a blank category."""
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("need", "water_wash"),
                         {"hazard_category": None, "hazard_sub": None})

    def test_the_columns_survive_a_round_trip_through_the_table(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        NarrativeTag.objects.create(
            dimension="hazard", tag="flooding", country="Sudan",
            report_date=date(2026, 8, 1), **hazard_columns("hazard", "flooding"))
        row = NarrativeTag.objects.get(tag="flooding")
        self.assertEqual(row.hazard_category, "hydrological")
        self.assertEqual(row.hazard_sub, "flooding")


class HazardExportTests(DashboardSandbox):
    """What the dashboard reads: the vocabulary, the counts and the popup."""

    def setUp(self):
        super().setUp()          # redirects dump() at a temporary directory
        self.flood = HazardEvent.objects.create(
            source="montandon", collection="idmc-idu",
            event_id="idmc-idu-event-80585",
            corr_id="20260817-SDN-900001-MH0600-1-GCDB", iso3="SDN",
            event_date=date(2026, 8, 17),
            title="Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026",
            hazard_codes=["MH0600"], hazard_category="hydrological",
            hazard_sub="floods", significance="event",
            lat=13.51, lon=24.86, admin_pcode="SD16", admin_level=2,
            admin_iso3="SDN", match_method="point-in-polygon")
        HazardImpact.objects.create(
            source="montandon", collection="idmc-idu",
            impact_id="idmc-idu-impact-80585-displaced",
            corr_id=self.flood.corr_id, iso3="SDN", event_date=date(2026, 8, 17),
            impact_type="displaced_internal", category="people",
            value=813, unit="count")
        self.fire = HazardEvent.objects.create(
            source="montandon", collection="gdacs", event_id="gdacs-event-1",
            corr_id="20260301-SDN-EN0205-1-GCDB", iso3="SDN",
            event_date=date(2026, 3, 1), title="Forest fires in Sudan",
            hazard_codes=["EN0205"], hazard_category="non_technological",
            hazard_sub="wildfires", significance="detection",
            severity_label="Green", severity_unit="GDACS Severity Score",
            severity_value=0.5, lat=6.08, lon=33.82,
            admin_pcode="SD17", admin_level=2, admin_iso3="SDN",
            match_method="point-in-polygon")

    def test_only_categories_present_in_the_data_are_offered(self):
        """The codebook is a clustering method, not a list to render. A Sahel
        operation must not be shown tsunamis."""
        build_hazards()
        keys = {c["key"] for c in read_dash("hazards.json")["categories"]}
        self.assertIn("hydrological", keys)
        self.assertIn("non_technological", keys)
        self.assertNotIn("technological", keys)

    def test_a_sub_hazard_records_which_evidence_stands_behind_it(self):
        NarrativeTag.objects.create(dimension="hazard", tag="flooding",
                                    country="Sudan", report_date=date(2026, 8, 1),
                                    hazard_category="hydrological",
                                    hazard_sub="flooding")
        build_hazards()
        hydro = next(c for c in read_dash("hazards.json")["categories"]
                     if c["key"] == "hydrological")
        by_key = {s["key"]: s for s in hydro["sub_hazards"]}
        self.assertEqual(by_key["floods"]["from"], "montandon")
        self.assertEqual(by_key["flooding"]["from"], "documents")

    def test_the_project_categories_are_marked_as_outside_the_codebook(self):
        NarrativeTag.objects.create(dimension="hazard", tag="armed_conflict",
                                    country="Sudan", report_date=date(2026, 8, 1),
                                    hazard_category="conflict_violence",
                                    hazard_sub="armed_conflict")
        build_hazards()
        cat = next(c for c in read_dash("hazards.json")["categories"]
                   if c["key"] == "conflict_violence")
        self.assertFalse(cat["in_codebook"])

    def test_events_are_counted_by_sub_hazard_area_and_month(self):
        build_hazard_events()
        rows = read_dash("hazard_events.json")["by_sub"]["floods"]["monthly"]
        self.assertEqual(rows, [{"month": "2026-08", "country": "Sudan",
                                 "count": 1, "area": "SD16",
                                 "significance": "event"}])

    def test_the_detection_flag_travels_so_the_dashboard_can_hold_fires_back(self):
        build_hazard_events()
        rows = read_dash("hazard_events.json")["by_sub"]["wildfires"]["monthly"]
        self.assertEqual(rows[0]["significance"], "detection")

    def test_the_popup_entry_carries_severity_with_its_unit(self):
        """Never a bare number: GDACS 0.5 and PDC 0.1 are different scales."""
        build_hazard_events()
        entry = read_dash("hazard_events.json")["events"]["SD17"]["2026-03"][0]
        self.assertEqual(entry["severity_label"], "Green")
        self.assertEqual(entry["severity_unit"], "GDACS Severity Score")

    def test_the_popup_entry_carries_the_impact_figures(self):
        build_hazard_events()
        entry = read_dash("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["impacts"],
                         [{"type": "displaced_internal", "value": 813,
                           "unit": "count", "category": "people",
                           "source": "idmc-idu"}])

    def test_the_country_is_the_polygons_not_the_filing(self):
        """Montandon files cross-border events under a neighbour. The map
        filters on country, so it must be told where the lit area really is."""
        HazardEvent.objects.create(
            source="montandon", collection="gdacs", event_id="gdacs-crossborder",
            corr_id="x-border", iso3="SDN", event_date=date(2026, 4, 1),
            title="Forest fires in Sudan", hazard_category="non_technological",
            hazard_sub="wildfires", significance="event",
            admin_pcode="SS01", admin_level=1, admin_iso3="SSD",
            match_method="point-in-polygon")
        build_hazard_events()
        rows = read_dash("hazard_events.json")["by_sub"]["wildfires"]["monthly"]
        crossborder = [r for r in rows if r["area"] == "SS01"]
        self.assertEqual(len(crossborder), 1)
        self.assertEqual(crossborder[0]["country"], "South Sudan")

    def test_an_unmatched_event_is_not_exported_because_it_cannot_be_drawn(self):
        HazardEvent.objects.create(
            source="montandon", collection="pdc", event_id="pdc-nowhere",
            corr_id="nowhere", iso3="SDN", event_date=date(2026, 7, 1),
            title="Somewhere in the desert", hazard_category="hydrological",
            hazard_sub="floods", match_method="unmatched", admin_pcode=None)
        build_hazard_events()
        total = sum(r["count"] for r in
                    read_dash("hazard_events.json")["by_sub"]["floods"]["monthly"])
        self.assertEqual(total, 1)

    def test_three_sources_reporting_one_flood_light_the_area_once(self):
        for collection in ("gdacs", "pdc"):
            HazardEvent.objects.create(
                source="montandon", collection=collection,
                event_id=f"{collection}-dup", corr_id=self.flood.corr_id,
                iso3="SDN", event_date=date(2026, 8, 17),
                title="Flood - Tawila", hazard_category="hydrological",
                hazard_sub="floods", significance="event",
                admin_pcode="SD16", admin_level=2, admin_iso3="SDN",
                match_method="point-in-polygon")
        build_hazard_events()
        rows = read_dash("hazard_events.json")["by_sub"]["floods"]["monthly"]
        self.assertEqual(rows[0]["count"], 1)
        entry = read_dash("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(sorted(entry["sources"]), ["gdacs", "idmc-idu", "pdc"])

    def test_the_most_place_specific_source_is_the_one_shown(self):
        """"North Darfur (Tawila Locality)" beats "Flood - Tawila"."""
        HazardEvent.objects.create(
            source="montandon", collection="gdacs", event_id="gdacs-dup2",
            corr_id=self.flood.corr_id, iso3="SDN", event_date=date(2026, 8, 17),
            title="Flood in Sudan", hazard_category="hydrological",
            hazard_sub="floods", significance="event",
            admin_pcode="SD16", admin_level=2, admin_iso3="SDN",
            match_method="point-in-polygon")
        build_hazard_events()
        entry = read_dash("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertIn("Tawila Locality", entry["title"])


class InsightLinkingTests(DashboardSandbox):
    """Some hazards have insights and many do not. Both are expected."""

    def setUp(self):
        super().setUp()          # redirects dump() at a temporary directory
        self.flood = HazardEvent.objects.create(
            source="montandon", collection="idmc-idu", event_id="e1",
            corr_id="c1", iso3="SDN", event_date=date(2026, 8, 17),
            title="Sudan: Flood - North Darfur (Tawila Locality)",
            hazard_category="hydrological", hazard_sub="floods",
            significance="event", admin_pcode="SD16", admin_level=2,
            admin_iso3="SDN", match_method="point-in-polygon")

    def _insight(self, pcode, on, tag="flooding", status="published"):
        ins = Insight.objects.create(
            quote="The water came through the night.", iso3="SDN",
            admin_pcode=pcode, admin_level=2, stated_on=on, status=status,
            quote_sha1=f"{pcode}{on}{tag}"[:40])
        InsightCoding.objects.create(insight=ins, dimension="hazard", tag=tag)
        return ins

    def _ids(self):
        build_hazard_events()
        return read_dash("hazard_events.json")["events"]["SD16"]["2026-08"][0]["insight_ids"]

    def test_a_same_place_same_month_same_hazard_insight_links(self):
        ins = self._insight("SD16", date(2026, 8, 20))
        self.assertEqual(self._ids(), [ins.id])

    def test_a_different_month_does_not_link(self):
        self._insight("SD16", date(2026, 5, 20))
        self.assertEqual(self._ids(), [])

    def test_a_different_place_does_not_link(self):
        self._insight("SD99", date(2026, 8, 20))
        self.assertEqual(self._ids(), [])

    def test_a_different_hazard_category_does_not_link(self):
        self._insight("SD16", date(2026, 8, 20), tag="armed_conflict")
        self.assertEqual(self._ids(), [])

    def test_an_unpublished_insight_does_not_link(self):
        self._insight("SD16", date(2026, 8, 20), status="pending")
        self.assertEqual(self._ids(), [])

    def test_a_hazard_with_no_insight_at_all_is_still_exported(self):
        """The hazards are the spine; the insights attach where they exist."""
        build_hazard_events()
        entry = read_dash("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [])
        self.assertEqual(entry["sub"], "floods")

    def test_a_flooding_insight_links_to_a_floods_event(self):
        """The two are different sub-hazards on purpose - a document mention is
        not an agency record - but they share a CATEGORY, which is what links."""
        ins = self._insight("SD16", date(2026, 8, 1), tag="flooding")
        self.assertEqual(self._ids(), [ins.id])
