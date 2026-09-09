"""The two hand-maintained workbooks, into the same table as the APIs.

They are not a lesser source. The neighbours workbook carries a 2026 biweekly
refugee series; UNHCR's API stops at 2024. Whichever is newer, an analyst asking
"what is the latest figure for Chad" should get it from one query.

The parsers are pure functions over a worksheet, so these tests build tiny
workbooks in memory rather than depending on the real files, which live outside the
repository and change weekly.
"""
from datetime import date, datetime

import openpyxl
from django.test import TestCase

from external_data.loaders.excel import parse_idp_states_sheet, parse_neighbours_sheet


def sheet(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return ws


class NeighboursWorkbookTests(TestCase):
    def test_a_sheet_becomes_one_row_per_country_per_date(self):
        ws = sheet([
            ["Country", "Data Date", "Sudanese refugees/asylum seekers"],
            ["Chad", datetime(2026, 2, 15), 1_250_000],
            ["Egypt", datetime(2026, 2, 15), 1_500_000],
        ])
        rows = parse_neighbours_sheet(ws)

        self.assertEqual(len(rows), 2)
        chad = next(r for r in rows if r["place_name"] == "Chad")
        self.assertEqual(chad["value"], 1_250_000)
        self.assertEqual(chad["metric"], "refugees")
        self.assertEqual(chad["source"], "excel")
        self.assertEqual(chad["iso3"], "TCD")
        self.assertEqual(chad["date"], date(2026, 2, 15))

    def test_the_other_spelling_of_the_column_is_accepted(self):
        """Sheets use 'Sudanese refugees' and 'Sudanese refugees/asylum seekers'."""
        ws = sheet([
            ["Country", "Data Date", "Sudanese refugees"],
            ["Chad", datetime(2026, 2, 15), 1_250_000],
        ])
        self.assertEqual(len(parse_neighbours_sheet(ws)), 1)

    def test_a_country_spelled_CAR_maps_to_the_same_iso3_as_the_full_name(self):
        ws = sheet([
            ["Country", "Data Date", "Sudanese refugees"],
            ["CAR", datetime(2026, 2, 15), 30_000],
            ["Central African Republic", datetime(2026, 3, 1), 31_000],
        ])
        rows = parse_neighbours_sheet(ws)
        self.assertEqual({r["iso3"] for r in rows}, {"CAF"})

    def test_a_row_with_no_figure_is_skipped_not_stored_as_zero(self):
        ws = sheet([
            ["Country", "Data Date", "Sudanese refugees"],
            ["Chad", datetime(2026, 2, 15), None],
            ["Egypt", datetime(2026, 2, 15), 0],
        ])
        self.assertEqual(parse_neighbours_sheet(ws), [])

    def test_a_sheet_without_the_expected_headings_yields_nothing(self):
        ws = sheet([["Notes"], ["some free text"]])
        self.assertEqual(parse_neighbours_sheet(ws), [])


class IdpStatesWorkbookTests(TestCase):
    def test_dated_column_headers_become_dated_rows(self):
        ws = sheet([
            ["State", "Population (15 Jan 2026)", "Population (15 Feb 2026)"],
            ["North Darfur", 1_000, 1_200],
        ])
        rows = parse_idp_states_sheet(ws)

        self.assertEqual(len(rows), 2)
        self.assertEqual({r["value"] for r in rows}, {1_000, 1_200})
        self.assertEqual({r["date"] for r in rows},
                         {date(2026, 1, 15), date(2026, 2, 15)})
        self.assertTrue(all(r["metric"] == "idps" for r in rows))
        self.assertTrue(all(r["admin_level"] == 1 for r in rows))
        self.assertTrue(all(r["iso3"] == "SDN" for r in rows))

    def test_an_undated_population_column_is_ignored(self):
        """A bare 'Population' column has no date, so it cannot become a row."""
        ws = sheet([
            ["State", "Population", "Population (15 Feb 2026)"],
            ["North Darfur", 999, 1_200],
        ])
        rows = parse_idp_states_sheet(ws)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], 1_200)

    def test_a_blank_state_row_is_skipped(self):
        ws = sheet([
            ["State", "Population (15 Feb 2026)"],
            [None, 1_200],
            ["", 1_300],
        ])
        self.assertEqual(parse_idp_states_sheet(ws), [])
