"""UNHCR ODP situations: the other end of the returns DTM counts."""
from datetime import date

from django.test import TestCase

from external_data.fetchers import fetcher_for
from external_data.loaders import LOADERS
from external_data.loaders.base import load
from external_data.models import MovementPattern, SourceSync


def row(country, iso3, ptype, on, n, origin="SDN"):
    return {"Country": country, "ISO3": iso3, "Country of Origin": "Sudan",
            "ISO3 of Origin": origin, "Population type": ptype,
            "Source": "UNHCR", "Date": on, "Individuals": str(n)}


def payload(rows):
    return {"source_url": "https://example.org/unhcr-situations.csv",
            "fetched_at": "2026-09-25T00:00:00Z", "sha1": "0" * 40, "rows": rows}


class RegistrationTests(TestCase):
    def test_the_fetcher_is_registered_and_needs_no_key(self):
        from external_data.fetchers.base import missing_keys
        cls = fetcher_for("unhcr-odp", "situations", "")
        self.assertIsNotNone(cls)
        self.assertEqual(missing_keys(cls), [])

    def test_the_loader_is_registered_under_its_own_source(self):
        """Not 'unhcr': that source already holds the ANNUAL HAPI series, and
        build_refugees() merges what it finds under metric='refugees'."""
        self.assertEqual(LOADERS["situations"].source, "unhcr-odp")


class ParseTests(TestCase):
    def parse(self, rows):
        return LOADERS["situations"]().parse(payload(rows), "SDN", {})

    def test_a_sudanese_refugee_row_becomes_a_country_total(self):
        out = self.parse([row("Chad", "TCD", "Refugees", "2026-09-07", 1396884)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["iso3"], "TCD")
        self.assertEqual(out[0]["place_name"], "Chad")
        self.assertEqual(out[0]["value"], 1396884)
        self.assertEqual(out[0]["date"], date(2026, 9, 7))
        self.assertEqual(out[0]["source"], "unhcr-odp")
        self.assertIsNone(out[0]["admin_pcode"])

    def test_rows_of_another_origin_are_ignored(self):
        """The file covers every situation UNHCR tracks, not just Sudan's."""
        out = self.parse([row("Chad", "TCD", "Refugees", "2026-09-07", 99, origin="CAF")])
        self.assertEqual(out, [])

    def test_the_changeover_date_is_collapsed_not_summed(self):
        """UNHCR publishes BOTH types on the date a population is reclassified.
        Uganda 2026-03-16 really carries 183,215 under each label; summing
        would report 366,430 people who do not exist."""
        out = self.parse([
            row("Uganda", "UGA", "Asylum-Seekers", "2026-03-16", 183215),
            row("Uganda", "UGA", "Refugees", "2026-03-16", 183215)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["value"], 183215)

    def test_where_the_pair_disagrees_the_larger_restated_figure_wins(self):
        """South Sudan 2025-12-01: 1,013,746 as asylum-seekers, 1,016,692 as
        refugees. The refugee figure is the restatement."""
        out = self.parse([
            row("South Sudan", "SSD", "Asylum-Seekers", "2025-12-01", 1013746),
            row("South Sudan", "SSD", "Refugees", "2025-12-01", 1016692)])
        self.assertEqual(out[0]["value"], 1016692)

    def test_a_series_that_switches_label_stays_one_continuous_series(self):
        out = self.parse([
            row("Uganda", "UGA", "Asylum-Seekers", "2025-12-01", 180870),
            row("Uganda", "UGA", "Refugees", "2026-09-07", 189098)])
        self.assertEqual([r["value"] for r in out], [180870, 189098])

    def test_sudan_as_its_own_country_of_asylum_is_excluded(self):
        """Those are not people who went anywhere. A panel about countries of
        asylum listing Sudan would read as Sudan hosting its own refugees."""
        out = self.parse([row("Sudan", "SDN", "Refugees", "2026-08-31", 547258)])
        self.assertEqual(out, [])

    def test_an_unparseable_date_is_skipped_not_guessed(self):
        out = self.parse([row("Chad", "TCD", "Refugees", "not a date", 5)])
        self.assertEqual(out, [])


class LoadTests(TestCase):
    def setUp(self):
        SourceSync.objects.update_or_create(
            source="unhcr-odp", dataset="situations", iso3=None, variant="")

    def test_rows_land_under_their_own_source(self):
        load(LOADERS["situations"](),
             payload([row("Chad", "TCD", "Refugees", "2026-09-07", 1396884)]),
             None, context={})
        self.assertEqual(
            MovementPattern.objects.get(source="unhcr-odp").value, 1396884)

    def test_the_existing_refugee_layer_reads_only_its_own_two_sources(self):
        """build_refugees() has always merged unhcr + excel. A third series
        folded in would rewrite country totals the dashboard has always shown."""
        MovementPattern.objects.create(
            date=date(2025, 7, 1), iso3="TCD", admin_pcode=None, admin_level=0,
            place_name="Chad", metric="refugees",
            population_group="sudanese_refugees", value=1109357,
            unit="individuals", source="unhcr", source_dataset="get_refugees")
        load(LOADERS["situations"](),
             payload([row("Chad", "TCD", "Refugees", "2026-09-07", 1396884)]),
             None, context={})
        seen = (MovementPattern.objects
                .filter(metric="refugees", source__in=["unhcr", "excel"])
                .values_list("value", flat=True))
        self.assertEqual(list(seen), [1109357])


class WatermarkTests(TestCase):
    """One source, one source_sync row, and a row_count that means something.

    The bug: the fetcher's dataset was `situations` and the loader's was
    `unhcr_situations`, and Loader.sync_key() keys on the LOADER's. So a pull
    wrote its watermark to a second row while the seeded row - the one the
    admin page shows and the Pull now button belongs to - stayed at "never
    pulled", for ever, exactly as the DTM row did before its own fix.
    """

    def test_the_fetcher_and_the_loader_agree_on_the_dataset_name(self):
        self.assertEqual(LOADERS["situations"].dataset,
                         fetcher_for("unhcr-odp", "situations", "").dataset)

    def test_the_call_routes_to_that_same_loader(self):
        from unittest.mock import patch
        from external_data.models import SourceSync
        sync, _ = SourceSync.objects.update_or_create(
            source="unhcr-odp", dataset="situations", iso3=None, variant="")
        package = {"result": {"resources": [
            {"id": "r1", "format": "CSV", "url": "https://x/unhcr-situations.csv"}]}}
        with patch("external_data.fetchers.unhcr_situations.http_get_json",
                   return_value=package):
            call = next(iter(fetcher_for("unhcr-odp", "situations", "")().plan(sync)))
        self.assertEqual(call.loader_dataset, "situations")
        self.assertIn(call.loader_dataset, LOADERS)

    def test_a_load_updates_the_seeded_row_rather_than_making_a_second(self):
        from external_data.models import SourceSync
        SourceSync.objects.update_or_create(
            source="unhcr-odp", dataset="situations", iso3=None, variant="")
        load(LOADERS["situations"](),
             payload([row("Chad", "TCD", "Refugees", "2026-09-07", 1396884)]),
             None, context={})
        rows = SourceSync.objects.filter(source="unhcr-odp")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().dataset, "situations")
        self.assertIsNotNone(rows.first().last_pulled_at)

    def test_row_count_counts_the_rows_this_source_actually_holds(self):
        """The default scope is (source, iso3), and iso3 is null for this row -
        one file covering every asylum country. Counting on a null iso3 matched
        nothing and the admin page read 0 beside 292 loaded rows."""
        from external_data.models import SourceSync
        SourceSync.objects.update_or_create(
            source="unhcr-odp", dataset="situations", iso3=None, variant="")
        load(LOADERS["situations"](),
             payload([row("Chad", "TCD", "Refugees", "2026-09-07", 1396884),
                      row("Uganda", "UGA", "Refugees", "2026-09-07", 189098)]),
             None, context={})
        self.assertEqual(
            SourceSync.objects.get(source="unhcr-odp").row_count, 2)
