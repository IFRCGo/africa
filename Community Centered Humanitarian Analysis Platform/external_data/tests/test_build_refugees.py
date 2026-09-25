"""The host-country refugee layer: two quantities that must never share a line.

The bug this pins: build_refugees() used to merge every refugee source into one
series per country. Chad's line therefore ran 1,330,950 at 2025-07-01 (UNHCR's
annual stock - every Sudanese refugee in Chad) straight into 919,187 at
2026-04-10 (the office workbook - arrivals SINCE 15 April 2023 only). A reader
saw 411,763 people leave Chad. Nobody left; the definition changed mid-series.
"""
import json
import pathlib
import tempfile
from datetime import date

from django.test import TestCase

from data_pipeline.steps import s06_mcp_layers as s06
from external_data.models import MovementPattern


def figure(source, on, value, country="Chad", iso3="TCD"):
    MovementPattern.objects.create(
        date=on, iso3=iso3, admin_pcode=None, admin_level=0, place_name=country,
        metric="refugees", population_group="sudanese_refugees", value=value,
        unit="individuals", source=source, source_dataset=f"test-{source}")


class RefugeeSeriesSplitTests(TestCase):
    def setUp(self):
        # The real Chad shape: a pre-war UNHCR total, a wartime UNHCR total,
        # a finer UNHCR ODP total, and the workbook's arrivals-only count.
        figure("unhcr", date(2022, 7, 1), 403846)
        figure("unhcr", date(2025, 7, 1), 1330950)
        figure("unhcr-odp", date(2026, 9, 7), 1396884)
        figure("excel", date(2026, 9, 7), 954257)

        self.tmp = pathlib.Path(tempfile.mkdtemp())
        real = s06.DASHBOARD_DATA
        s06.DASHBOARD_DATA = self.tmp
        self.addCleanup(setattr, s06, "DASHBOARD_DATA", real)

    def chad(self):
        s06.build_refugees()
        out = json.loads((self.tmp / "refugee_camps.json").read_text(encoding="utf-8"))
        return next(c for c in out["countries"] if c["country"] == "Chad")

    def test_the_portal_leads_and_its_figure_is_what_the_map_draws(self):
        """The office reads it by hand from UNHCR's Sudan situation portal and
        it is the freshest figure there is. A build that dropped it off the
        bubble took the operation's own number off its own map."""
        self.assertEqual(self.chad()["series"][-1],
                         {"date": "2026-09-07", "value": 954257,
                          "basis": "portal"})

    def test_the_timeline_meets_the_three_bases_in_order(self):
        """Parked at the start a reader sees the pre-war caseload; HDX covers
        the years before the portal series begins; the portal takes over where
        it reports. A step between them is a change of footing, so every point
        has to say which one it is on."""
        series = self.chad()["series"]
        order = []
        for p in series:
            if not order or order[-1] != p["basis"]:
                order.append(p["basis"])
        self.assertEqual(order, ["prewar", "hdx", "portal"])

    def test_the_odp_reading_never_enters_the_drawn_line(self):
        """UNHCR's annual stock and its ODP operational reading look like one
        quantity and are not: on 29 Jun 2025 ODP put South Sudan at 951,275 and
        the annual series put it at 571,066 two days later. Stitching them
        draws a collapse that did not happen."""
        self.assertNotIn(1396884, [p["value"] for p in self.chad()["series"]])

    def test_the_odp_reading_is_published_separately_as_current(self):
        self.assertEqual(self.chad()["current"],
                         {"date": "2026-09-07", "value": 1396884})

    def test_arrivals_are_their_own_series(self):
        self.assertEqual(self.chad()["arrivals"],
                         [{"date": "2026-09-07", "value": 954257}])

    def test_the_pre_war_baseline_is_the_last_total_before_15_april_2023(self):
        """This is the number that explains the gap: the Darfur caseload Chad
        had been hosting since 2003."""
        self.assertEqual(self.chad()["pre_war"],
                         {"date": "2022-07-01", "value": 403846,
                          "basis": "prewar"})

    def test_a_reading_on_the_crisis_date_itself_is_not_pre_war(self):
        figure("unhcr", date(2023, 4, 15), 500000)
        self.assertEqual(self.chad()["pre_war"]["date"], "2022-07-01")

    def test_current_is_the_latest_odp_reading_not_the_first(self):
        figure("unhcr-odp", date(2025, 7, 1), 1261175)
        self.assertEqual(self.chad()["current"]["value"], 1396884)

    def test_the_portal_link_travels_with_the_file(self):
        """The popup names the portal and links to it, so the URL is data
        rather than a string buried in the JS."""
        s06.build_refugees()
        out = json.loads((self.tmp / "refugee_camps.json").read_text(encoding="utf-8"))
        self.assertEqual(out["portal_url"],
                         "https://data.unhcr.org/en/situations/sudansituation")

    def test_a_country_with_only_a_portal_figure_still_draws(self):
        """Egypt has no SDN-origin ODP rows at all. Falling back to arrivals
        keeps its bubble on the map rather than dropping the country."""
        figure("excel", date(2026, 9, 7), 1500000, country="Egypt", iso3="EGY")
        s06.build_refugees()
        out = json.loads((self.tmp / "refugee_camps.json").read_text(encoding="utf-8"))
        egypt = next(c for c in out["countries"] if c["country"] == "Egypt")
        self.assertEqual(egypt["series"],
                         [{"date": "2026-09-07", "value": 1500000,
                           "basis": "portal"}])

    def test_the_crisis_date_travels_with_the_file(self):
        s06.build_refugees()
        out = json.loads((self.tmp / "refugee_camps.json").read_text(encoding="utf-8"))
        self.assertEqual(out["crisis_start"], "2023-04-15")
