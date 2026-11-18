"""IDP and refugee series, long format.

The watermark tests are the ones that prove the design's central claim: loading an
overlapping range moves high_water_date forward exactly once, does not duplicate
rows already held, and never rewinds when older data is backfilled.

The fixture is a real slice of the cached HDX pull - two Khartoum localities across
three months - so the field names and types are the source's own.
"""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from external_data.models import MovementPattern, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


class IdpLoaderTests(TestCase):
    def _load(self, name="hdx_idps_SDN_admin2.json"):
        call_command("load_external", "idps", str(FIXTURES / name), "--iso3", "SDN")

    def test_rows_are_long_format_one_per_place_per_date(self):
        self._load()
        self.assertEqual(MovementPattern.objects.count(), 6)
        row = MovementPattern.objects.get(admin_pcode="SD01001", date=date(2025, 12, 31))
        self.assertEqual(row.metric, "idps")
        self.assertEqual(row.source, "hdx")
        self.assertEqual(row.unit, "individuals")
        self.assertEqual(row.place_name, "Jebel Awlia")
        self.assertEqual(row.value, 28773)

    def test_the_pcode_is_kept_so_the_boundary_library_can_be_joined(self):
        """SD01001 is an OCHA p-code - no name matching needed to place this row."""
        self._load()
        self.assertEqual(
            set(MovementPattern.objects.values_list("admin_pcode", flat=True)),
            {"SD01001", "SD01002"},
        )

    def test_the_reporting_period_is_kept_at_both_ends(self):
        self._load()
        row = MovementPattern.objects.get(admin_pcode="SD01001", date=date(2025, 12, 31))
        self.assertIsNotNone(row.reference_period_start)
        self.assertEqual(row.reference_period_end, date(2025, 12, 31))

    def test_the_watermark_is_the_latest_data_date_not_today(self):
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        self.assertEqual(sync.high_water_date, date(2025, 12, 31))
        self.assertNotEqual(sync.high_water_date, date.today())

    def test_the_variant_distinguishes_admin_levels(self):
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        self.assertEqual(sync.variant, "admin2-overview")

    def test_an_incremental_load_advances_the_watermark_and_unions_the_rows(self):
        """Load October, then October-December. Six rows, not eight."""
        self._load("hdx_idps_SDN_admin2_early.json")
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        self.assertEqual(sync.high_water_date, date(2025, 10, 31))
        self.assertEqual(MovementPattern.objects.count(), 2)

        self._load()
        sync.refresh_from_db()
        self.assertEqual(sync.high_water_date, date(2025, 12, 31))
        self.assertEqual(MovementPattern.objects.count(), 6)
        self.assertEqual(sync.row_count, 6)

    def test_reloading_the_same_data_does_not_duplicate(self):
        self._load()
        self._load()
        self.assertEqual(MovementPattern.objects.count(), 6)

    def test_the_watermark_never_rewinds(self):
        """Backfilling older data must not move the mark backwards."""
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        self.assertEqual(sync.high_water_date, date(2025, 12, 31))

        self._load("hdx_idps_SDN_admin2_early.json")
        sync.refresh_from_db()
        self.assertEqual(sync.high_water_date, date(2025, 12, 31))


class PlaceIdentityTests(TestCase):
    """The regression guard for the bug that ate 228 of 234 rows.

    Sudan's admin1 IDP rows carry no p-code. With place_name outside the natural
    key, every state sharing a date collided and all but one were overwritten - and
    silently, because an upsert reports success either way. The workbook looked like
    it held six observations instead of two hundred and thirty-four.
    """

    def test_two_places_on_one_date_without_pcodes_are_two_rows(self):
        for state in ("North Darfur", "South Darfur"):
            MovementPattern.objects.create(
                date=date(2026, 7, 31), iso3="SDN", admin_pcode=None, admin_level=1,
                place_name=state, metric="idps", population_group="idps",
                value=1000, source="excel", source_dataset="Sudan IDPs.xlsx",
            )
        self.assertEqual(MovementPattern.objects.count(), 2)

    def test_the_same_place_and_date_is_still_one_row(self):
        for value in (1000, 2000):
            MovementPattern.objects.update_or_create(
                date=date(2026, 7, 31), iso3="SDN", admin_pcode=None, admin_level=1,
                place_name="North Darfur", metric="idps", population_group="idps",
                source="excel", defaults={"value": value},
            )
        self.assertEqual(MovementPattern.objects.count(), 1)
        self.assertEqual(MovementPattern.objects.get().value, 2000)
