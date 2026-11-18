"""The refugee pull must produce the series that already exists, not a new one.

Found by the first real pull rather than by review. HAPI answers `get_refugees`
with 611 rows for one country - every combination of gender (f/m/all) and age
band (0-4 ... all) - and the loader collapses all of them onto one natural key
per year and population group. The upsert then failed outright:

    ON CONFLICT DO UPDATE command cannot affect row a second time

Three things had to be pinned, and all three are about MEANING, not tidiness.
"""
from datetime import date

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.loaders.base import load
from external_data.loaders.movement import RefugeeLoader
from external_data.models import MovementPattern, SourceSync


@override_settings(HDX_API_TOKEN="TESTTOKEN")
class RequestShapeTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(source="unhcr", dataset="refugees",
                                              iso3="TCD")
        self.call = next(iter(fetcher_for("unhcr", "refugees", "")().plan(self.sync)))

    def test_totals_only_are_requested(self):
        """611 rows collapse onto ~47 keys. Asking for the totals is what stops
        the upsert colliding with itself - and it is also the only figure the
        table can hold, since MovementPattern has no gender or age column."""
        self.assertEqual(self.call.params["gender"], "all")
        self.assertEqual(self.call.params["age_range"], "all")

    def test_only_refugees_are_requested_not_asylum_seekers(self):
        """ASY rows would land under metric='refugees' beside the REF rows for
        the same country and date. build_refugees() in s06 keeps ONE value per
        (country, date) and does not sum, so Chad's 1,330,950 refugees could be
        overwritten on the dashboard by its 3,645 asylum seekers."""
        self.assertEqual(self.call.params["population_group"], "REF")

    def test_the_origin_is_still_pinned_to_sudan(self):
        self.assertEqual(self.call.params["origin_location_code"], "SDN")


class GroupNormalisationTests(TestCase):
    """HAPI says 'REF'; this project's series is called 'sudanese_refugees'.

    They are the same quantity - verified against the rows seed_external
    transcribed by hand, which match HAPI to the person: Chad 2023 = 923,323 and
    2024 = 1,109,357. If the pulled rows kept the label 'REF' they would sit
    BESIDE the seeded ones rather than update them, and the dashboard would hold
    two refugee series for one country and pick between them arbitrarily.
    """

    def _payload(self, group="REF"):
        return {"data": [{
            "reference_period_start": "2025-01-01",
            "reference_period_end": "2025-12-31",
            "asylum_location_code": "TCD", "asylum_location_name": "Chad",
            "origin_location_code": "SDN", "population_group": group,
            "gender": "all", "age_range": "all", "population": 1330950,
        }]}

    def test_a_ref_row_joins_the_existing_series(self):
        SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        load(RefugeeLoader(), self._payload(), "TCD")
        row = MovementPattern.objects.get(iso3="TCD", date=date(2025, 7, 1))
        self.assertEqual(row.population_group, "sudanese_refugees")
        self.assertEqual(row.value, 1330950)

    def test_a_pull_updates_a_seeded_row_rather_than_duplicating_it(self):
        """The whole point: 'that data should go to update the database'."""
        SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        MovementPattern.objects.create(
            date=date(2025, 7, 1), iso3="TCD", admin_pcode=None, admin_level=0,
            place_name="Chad", metric="refugees",
            population_group="sudanese_refugees", value=1, unit="individuals",
            source="unhcr", source_dataset="get_refugees")
        load(RefugeeLoader(), self._payload(), "TCD")
        rows = MovementPattern.objects.filter(iso3="TCD", date=date(2025, 7, 1))
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().value, 1330950)

    def test_an_unrecognised_group_is_kept_as_published(self):
        """Only REF is renamed, and only because origin is pinned to Sudan. A
        code this project has not thought about must not be silently relabelled
        as Sudanese refugees."""
        SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        load(RefugeeLoader(), self._payload(group="OIP"), "TCD")
        self.assertEqual(MovementPattern.objects.get(iso3="TCD").population_group, "OIP")
