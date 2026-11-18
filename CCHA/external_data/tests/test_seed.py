"""The three hand-typed dictionaries become rows, once.

seed_external is not part of a refresh. It runs once to move what is currently
Python source into the database, and after it the dictionaries are deleted from
s06_mcp_layers.py - leaving them in place would guarantee that one day the code
path nobody watches is the one serving the dashboard.

Sudan's seasonal calendar is seeded as 'curated' rather than 'fewsnet' precisely so
the real FEWS NET pull can replace it and the curated rows can then be deleted. The
existing dict claims to come from get_seasons and does not.
"""
from django.core.management import call_command
from django.test import TestCase, override_settings

from external_data.models import (BorderCrossing, MovementPattern, SeasonalCalendar,
                                  SourceSync)


class SeedExternalTests(TestCase):
    def test_the_curated_crossings_are_seeded(self):
        call_command("seed_external")
        self.assertEqual(BorderCrossing.objects.count(), 9)
        adre = BorderCrossing.objects.get(name__startswith="El Geneina")
        self.assertEqual(adre.corridor, "sudan-chad")
        self.assertEqual(adre.return_corridor, "chad-sudan-return")
        self.assertEqual(adre.source, "curated")
        self.assertEqual(adre.iso3, "TCD")

    def test_a_crossing_with_no_return_corridor_keeps_null_not_empty_string(self):
        """Um Dukhun has no return corridor. That absence is a fact, not a blank."""
        call_command("seed_external")
        um = BorderCrossing.objects.get(name__startswith="Um Dukhun")
        self.assertIsNone(um.return_corridor)

    def test_the_sudan_calendar_is_seeded_as_curated_so_the_real_pull_can_replace_it(self):
        call_command("seed_external")
        bands = SeasonalCalendar.objects.filter(iso3="SDN", source="curated")
        self.assertEqual(bands.count(), 5)
        lean = bands.get(label="Lean / hunger season")
        self.assertEqual((lean.start_month, lean.end_month), (5, 10))

    def test_refugee_totals_are_seeded_as_movement_rows(self):
        call_command("seed_external")
        rows = MovementPattern.objects.filter(source="unhcr", metric="refugees")
        self.assertEqual(rows.filter(iso3="TCD").count(), 3)      # 2022, 2023, 2024
        self.assertEqual(rows.get(iso3="TCD", date__year=2024).value, 1_109_357)

    def test_egypts_caveat_survives_into_the_database(self):
        """UNHCR registers a fraction of the Sudanese actually in Egypt.

        The existing REF_COUNTRIES dict carries that warning as a note, and it is
        the single most important thing about the Egypt figure - 27,696 registered
        against a government estimate above a million. Losing it in the move from
        Python to SQL would turn a caveated number into a bare one.
        """
        call_command("seed_external")
        sync = SourceSync.objects.get(source="unhcr", dataset="refugees", iso3="EGY")
        self.assertIn("registered", sync.notes.lower())

    def test_seeding_twice_changes_nothing(self):
        call_command("seed_external")
        call_command("seed_external")
        self.assertEqual(BorderCrossing.objects.count(), 9)
        self.assertEqual(
            SeasonalCalendar.objects.filter(iso3="SDN", source="curated").count(), 5
        )
        self.assertEqual(
            MovementPattern.objects.filter(source="unhcr", metric="refugees").count(), 21
        )


class MontandonSourceRowTests(TestCase):
    """Eight rows, eight buttons - and every one of them pullable.

    pull_button and pullable() both key off the fetcher registry, with no
    whitelist anywhere, so seeding the rows IS the button. These tests are what
    say so out loud.
    """

    def test_one_row_per_country_of_focus(self):
        rows = SourceSync.objects.filter(source="montandon", dataset="hazard_events")
        self.assertEqual(
            sorted(rows.values_list("iso3", flat=True)),
            ["CAF", "EGY", "ETH", "LBY", "SDN", "SSD", "TCD", "UGA"])

    @override_settings(IFRC_API_TOKEN="TESTTOKEN")
    def test_every_row_has_a_fetcher_so_every_row_has_a_button(self):
        from api_calls.views import pullable
        for row in SourceSync.objects.filter(source="montandon"):
            self.assertIsNone(pullable(row), row.iso3)

    @override_settings(IFRC_API_TOKEN="")
    def test_without_the_token_the_button_says_so_rather_than_calling(self):
        from api_calls.views import pullable
        row = SourceSync.objects.filter(source="montandon").first()
        self.assertEqual(pullable(row), "IFRC_API_TOKEN is not set")

    def test_the_notes_explain_why_the_watermark_never_narrows(self):
        row = SourceSync.objects.filter(source="montandon").first()
        self.assertIn("never narrows", row.notes)
