"""The column that stops a button undoing a curator's judgement.

known_ids means HELD. The notes column already records analyses a person
deliberately left out, and those ids are in neither list - so a naive diff
re-pulls every one of them, and the known-empty ones fail forever.
"""
from django.test import TestCase

from external_data.models import SourceSync


class ColumnTests(TestCase):
    def test_a_new_row_starts_with_an_empty_skip_list(self):
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        self.assertEqual(sync.skipped_ids, [])

    def test_entries_carry_an_id_and_a_reason(self):
        """A skip with no reason is indistinguishable from a bug six months on."""
        sync = SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="CAF",
            skipped_ids=[{"id": "87143421", "reason": "publishes no current-period geometry"}],
        )
        sync.refresh_from_db()
        self.assertEqual(sync.skipped_ids[0]["id"], "87143421")
        self.assertIn("geometry", sync.skipped_ids[0]["reason"])


class SeedTests(TestCase):
    """The four exclusions transcribed out of the notes by migration 0013.

    The real rows are written by seed_external and do not exist in a fresh test
    database, so the migration's own function is run here against rows the test
    creates. Reading the real database instead would make every one of these
    tests skip silently, which is indistinguishable from passing.
    """

    def setUp(self):
        from importlib import import_module
        migration = import_module("external_data.migrations.0013_seed_skipped_ids")
        for source, iso3 in (("ipc", "CAF"), ("ipc", "SSD"), ("ch", "TCD")):
            SourceSync.objects.create(source=source, dataset="food_security", iso3=iso3)
        migration.apply_skips(SourceSync)

    def _skipped(self, source, iso3):
        sync = SourceSync.objects.get(source=source, dataset="food_security", iso3=iso3)
        return [s["id"] for s in sync.skipped_ids]

    def test_running_it_twice_does_not_duplicate_an_entry(self):
        from importlib import import_module
        migration = import_module("external_data.migrations.0013_seed_skipped_ids")
        migration.apply_skips(SourceSync)
        self.assertEqual(len(self._skipped("ch", "TCD")), 2)

    def test_caf_skips_the_analysis_with_no_geometry(self):
        self.assertIn("87143421", self._skipped("ipc", "CAF"))

    def test_ssd_skips_its_projection_update(self):
        self.assertIn("81832747", self._skipped("ipc", "SSD"))

    def test_chad_skips_the_displaced_population_analysis(self):
        """The one that matters most: March 2024 is INSIDE the crisis window, so
        the date floor does not exclude it. Only the curator's decision does."""
        self.assertIn("68596035", self._skipped("ch", "TCD"))

    def test_chad_skips_the_pre_crisis_march_2023_analysis(self):
        self.assertIn("48055748", self._skipped("ch", "TCD"))

    def test_every_skip_carries_a_reason(self):
        for source, iso3 in (("ipc", "CAF"), ("ipc", "SSD"), ("ch", "TCD")):
            sync = SourceSync.objects.get(source=source, dataset="food_security",
                                          iso3=iso3)
            self.assertTrue(sync.skipped_ids)
            for entry in sync.skipped_ids:
                self.assertTrue(entry.get("reason"),
                                f"{source}/{iso3} {entry.get('id')} has no reason")
