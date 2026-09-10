"""What every loader must guarantee, proved on the smallest real source.

The de-duplication test uses the genuine Chad payload rather than a hand-made one,
because the duplication is the kind of thing nobody invents: FEWS NET returns each
season once per historical geographic-unit version, so Chad's six seasons arrive as
fifteen rows. A loader that misses this renders every band three times.
"""
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from external_data.models import SeasonalCalendar, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


class SeasonalLoaderTests(TestCase):
    fixture = "fewsnet_seasons_TCD.json"

    def _load(self, **kwargs):
        call_command("load_external", "seasonal_calendar",
                     str(FIXTURES / self.fixture), "--iso3", "TCD", **kwargs)

    def test_historical_unit_versions_are_discarded(self):
        """15 rows in, 6 out - one per real season, none from a versioned fnid."""
        self._load()
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        refs = set(SeasonalCalendar.objects.values_list("source_ref", flat=True))
        self.assertEqual(refs, {"TD"})

    def test_the_lean_season_is_read_correctly(self):
        self._load()
        lean = SeasonalCalendar.objects.get(label="Lean", purpose="NutritionIndicator")
        self.assertEqual((lean.start_month, lean.end_month), (4, 9))
        self.assertEqual(lean.season_type, "Lean")
        self.assertEqual(lean.iso3, "TCD")
        self.assertIn("soudure", lean.aliases)

    def test_a_season_that_wraps_the_year_end_is_kept_as_published(self):
        """Chad's cold off-season harvest is November to February. Do not 'fix' it."""
        self._load()
        cold = SeasonalCalendar.objects.get(label="Cold off-season harvest")
        self.assertEqual((cold.start_month, cold.end_month), (11, 2))

    def test_loading_twice_changes_nothing(self):
        self._load()
        self._load()
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        self.assertEqual(SourceSync.objects.count(), 1)
        self.assertEqual(SourceSync.objects.get().row_count, 6)

    def test_the_watermark_is_written(self):
        self._load()
        sync = SourceSync.objects.get()
        self.assertEqual(sync.source, "fewsnet")
        self.assertEqual(sync.dataset, "seasonal_calendar")
        self.assertEqual(sync.iso3, "TCD")
        self.assertIsNotNone(sync.last_pulled_at)

    def test_dry_run_writes_nothing(self):
        self._load(dry_run=True)
        self.assertEqual(SeasonalCalendar.objects.count(), 0)
        self.assertEqual(SourceSync.objects.count(), 0)


class EmptyPayloadTests(TestCase):
    def test_an_empty_payload_fails_loudly(self):
        """An MCP error serialised as [] must never be recorded as 'up to date'.

        This is the failure mode most likely to make the whole design lie: a silent
        empty load would advance the watermark and every later refresh would skip
        genuinely missing data.
        """
        with self.assertRaises(CommandError):
            call_command("load_external", "seasonal_calendar",
                         str(FIXTURES / "empty.json"), "--iso3", "TCD")
        self.assertEqual(SourceSync.objects.count(), 0)
        self.assertEqual(SeasonalCalendar.objects.count(), 0)


class SudanSeasonalTests(TestCase):
    """The regression that changed the de-duplication rule.

    Sudan's real payload has twelve records under two definitions, and they are NOT
    copies of each other. Three crop seasons - traditional rainfed, mechanized
    rainfed, irrigated - exist only under SD2014A0. The first rule written here kept
    just the plain "SD" fnid and would have deleted all three while appearing to
    remove duplicates. These are the bands the dashboard has drawn since it was
    built.
    """

    def _load(self):
        call_command("load_external", "seasonal_calendar",
                     str(FIXTURES / "fewsnet_seasons_SDN.json"), "--iso3", "SDN")

    def test_seasons_unique_to_a_versioned_definition_are_kept(self):
        self._load()
        labels = set(SeasonalCalendar.objects.values_list("label", flat=True))
        self.assertIn("Traditional rainfed harvest", labels)
        self.assertIn("Mechanized rainfed harvest", labels)
        self.assertIn("Irrigated harvest", labels)

    def test_seasons_repeated_across_definitions_are_stored_once(self):
        self._load()
        self.assertEqual(
            SeasonalCalendar.objects.filter(label="Lean", purpose="NutritionIndicator").count(), 1
        )
        # 12 records in, 9 distinct seasons out: three nutrition seasons are
        # repeated under both definitions and collapse.
        self.assertEqual(SeasonalCalendar.objects.count(), 9)

    def test_the_lean_season_matches_what_the_dashboard_has_always_shown(self):
        """May-October, the same span as the hand-typed dict it replaces."""
        self._load()
        lean = SeasonalCalendar.objects.get(label="Lean", purpose="NutritionIndicator")
        self.assertEqual((lean.start_month, lean.end_month), (5, 10))

    def test_the_current_definition_wins_where_both_carry_a_season(self):
        self._load()
        lean = SeasonalCalendar.objects.get(label="Lean", purpose="NutritionIndicator")
        self.assertEqual(lean.source_ref, "SD")
