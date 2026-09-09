"""IPC phases into the database, geometry included.

The fixture is a real IPC pull trimmed to three areas, with one area's phase nulled
so the skip rule has something to skip. Two behaviours are carried over from
s06_mcp_layers.build_foodsec deliberately: an area with no overall_phase is skipped,
and phase 3+ is the sum of the phase 3, 4 and 5 percentages. Changing either would
change what the map has always shown.
"""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from external_data.models import FoodSecurityArea, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = "ipc_area_2026-02_TCD.geojson"


class FoodSecurityLoaderTests(TestCase):
    def _load(self, **kwargs):
        call_command("load_external", "food_security", str(FIXTURES / FIXTURE),
                     "--iso3", "TCD", **kwargs)

    def test_areas_without_a_phase_are_skipped(self):
        """Three features in the fixture; one has no overall_phase."""
        self._load()
        self.assertEqual(FoodSecurityArea.objects.count(), 2)
        self.assertFalse(
            FoodSecurityArea.objects.filter(area_id="unanalysed-test").exists()
        )

    def test_phase3plus_is_the_sum_of_phases_3_4_and_5(self):
        self._load()
        for area in FoodSecurityArea.objects.all():
            self.assertAlmostEqual(
                area.phase3plus_pct,
                round((area.phase3_pct or 0) + (area.phase4_pct or 0)
                      + (area.phase5_pct or 0), 3),
            )

    def test_chad_is_recorded_as_cadre_harmonise_not_ipc(self):
        self._load()
        self.assertEqual(
            set(FoodSecurityArea.objects.values_list("source", flat=True)), {"ch"}
        )

    def test_the_period_comes_from_the_filename_not_from_today(self):
        self._load()
        self.assertEqual(
            set(FoodSecurityArea.objects.values_list("period_date", flat=True)),
            {date(2026, 2, 1)},
        )

    def test_ipc_identifiers_and_population_strings_are_read(self):
        """anl_id, aar_id and estimated_population - the last arrives as a string."""
        self._load()
        area = FoodSecurityArea.objects.get(area_title="Abassiya")
        self.assertEqual(area.analysis_id, "87143417")
        self.assertEqual(area.area_id, "1558")
        self.assertIsInstance(area.total_population, int)
        self.assertEqual(area.colour, "#E67800")

    def test_geometry_is_written_and_the_web_copy_is_simpler(self):
        self._load()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM food_security "
                "WHERE geom IS NOT NULL AND geom_web IS NOT NULL"
            )
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute(
                "SELECT bool_and(ST_NPoints(geom) >= ST_NPoints(geom_web)) FROM food_security"
            )
            self.assertTrue(cur.fetchone()[0])

    def test_loading_twice_changes_nothing(self):
        self._load()
        self._load()
        self.assertEqual(FoodSecurityArea.objects.count(), 2)

    def test_the_analysis_id_is_remembered_for_identity_diffing(self):
        """IPC has no date filter, so known_ids is how we know what to skip."""
        self._load()
        sync = SourceSync.objects.get(source="ch", dataset="food_security", iso3="TCD")
        self.assertIn("87143417", sync.known_ids)
        self.assertEqual(sync.high_water_date, date(2026, 2, 1))
