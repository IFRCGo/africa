"""What the watermark table must guarantee.

The first test is the one that matters. An earlier draft of this design keyed the
table on a digest of the call's arguments, which is wrong in a way that is easy to
miss: `start_date` is one of those arguments, so every incremental pull would have
hashed differently, created a new row, and left the next pull with no accumulated
watermark to read. The row identifies a thing that CAN be pulled, not a pull.
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from external_data.models import SourceSync


class SourceSyncIdentityTests(TestCase):
    def test_two_pulls_of_the_same_thing_are_one_row(self):
        """Different start_date, same row - this is the whole mechanism."""
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview",
            params={"start_date": "2024-01-01"}, high_water_date=date(2024, 6, 30),
        )
        row = SourceSync.objects.get(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        row.params = {"start_date": "2024-06-30"}
        row.high_water_date = date(2025, 12, 31)
        row.save()

        self.assertEqual(SourceSync.objects.count(), 1)
        self.assertEqual(
            SourceSync.objects.get().high_water_date, date(2025, 12, 31)
        )

    def test_duplicate_identity_is_refused(self):
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceSync.objects.create(
                source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
            )

    def test_variants_are_separate_rows(self):
        """IDPs at admin1 and at admin2 are genuinely different things to pull."""
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin1"
        )
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        self.assertEqual(SourceSync.objects.count(), 2)

    def test_null_iso3_still_collides(self):
        """A global pull has no country. Two NULLs must not slip past the constraint."""
        SourceSync.objects.create(source="ipc", dataset="food_security", variant="")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceSync.objects.create(source="ipc", dataset="food_security", variant="")
