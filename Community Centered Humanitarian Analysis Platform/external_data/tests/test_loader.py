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
