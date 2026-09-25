"""The xlsx→JSON transcriber: source-agnostic, and deliberately so.

Four workbook-shaped sources are coming (one here, three in Phase 2). A
transcriber that understood any one of them would need rewriting for the
others. This one understands only "a sheet is a rectangle of cells", which is
why its tests never mention DTM.
"""
import datetime
import io

import openpyxl
from django.test import TestCase

from external_data.fetchers.workbook import transcribe


def workbook_bytes(sheets):
    """Build a real .xlsx in memory. {sheet_name: [[cell, ...], ...]}"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class TranscribeTests(TestCase):
    def test_every_sheet_comes_back_by_name(self):
        raw = workbook_bytes({"One": [["a"]], "Two": [["b"]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(sorted(out["sheets"]), ["One", "Two"])

    def test_numbers_stay_numbers_and_text_stays_text(self):
        raw = workbook_bytes({"S": [["Khartoum", 1234, 12.5]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["sheets"]["S"][0], ["Khartoum", 1234, 12.5])

    def test_dates_become_iso_strings(self):
        """JSON has no date type, so the payload must carry a parseable string."""
        raw = workbook_bytes({"S": [[datetime.datetime(2026, 7, 30, 0, 0)]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["sheets"]["S"][0][0], "2026-07-30T00:00:00")

    def test_blank_cells_are_null_not_dropped(self):
        """Column position is the whole key to a header-anchored parser. A row
        that dropped its empty cells would shift every later column left."""
        raw = workbook_bytes({"S": [["a", None, "c"]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["sheets"]["S"][0], ["a", None, "c"])

    def test_an_empty_sheet_is_an_empty_list_not_an_error(self):
        raw = workbook_bytes({"Empty": [], "S": [["a"]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["sheets"]["Empty"], [])

    def test_provenance_is_recorded(self):
        raw = workbook_bytes({"S": [["a"]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["source_url"], "https://example.org/x.xlsx")
        self.assertEqual(len(out["sha1"]), 40)
        self.assertTrue(out["fetched_at"].endswith("Z"))

    def test_sha1_is_of_the_bytes(self):
        """So a resource edited in place is visible on re-pull."""
        import hashlib
        raw = workbook_bytes({"S": [["a"]]})
        out = transcribe(raw, "https://example.org/x.xlsx")
        self.assertEqual(out["sha1"], hashlib.sha1(raw).hexdigest())


from pathlib import Path
from unittest.mock import patch

from external_data.fetchers import base
from external_data.fetchers.base import Call


class DispatchTests(TestCase):
    def test_format_defaults_to_json_so_every_existing_call_is_unchanged(self):
        call = Call(url="u", params={}, cache_path=Path("a.json"),
                    loader_dataset="d")
        self.assertEqual(call.format, "json")

    def test_fetch_routes_xlsx_to_the_workbook_path(self):
        call = Call(url="u", params={}, cache_path=Path("a.json"),
                    loader_dataset="d", format="xlsx")
        with patch.object(base, "fetch_workbook", return_value={"sheets": {}}) as fw:
            self.assertEqual(base.fetch(call), {"sheets": {}})
        fw.assert_called_once_with(call)

    def test_fetch_still_routes_json_to_http_get_json(self):
        call = Call(url="u", params={"a": 1}, cache_path=Path("a.json"),
                    loader_dataset="d")
        with patch.object(base, "http_get_json", return_value={"data": []}) as gj:
            self.assertEqual(base.fetch(call), {"data": []})
        gj.assert_called_once_with("u", {"a": 1})


from external_data.fetchers.workbook import transcribe_csv


class TranscribeCsvTests(TestCase):
    """CSV is the second format, and it has its own payload shape.

    A workbook is sheets of positional cells; a CSV is one table with a header,
    so its rows are dicts. Forcing one shape onto both would make every loader
    carry the other format's ceremony.
    """

    CSV = (b"Country,ISO3,Population type,Date,Individuals\r\n"
           b"Chad,TCD,Refugees,2026-09-07,1396884\r\n"
           b"Uganda,UGA,Refugees,2026-09-07,189098\r\n")

    def test_rows_come_back_as_dicts_keyed_by_the_header(self):
        out = transcribe_csv(self.CSV, "https://example.org/x.csv")
        self.assertEqual(out["rows"][0]["Country"], "Chad")
        self.assertEqual(out["rows"][1]["Individuals"], "189098")

    def test_every_row_is_kept(self):
        self.assertEqual(len(transcribe_csv(self.CSV, "u")["rows"]), 2)

    def test_a_utf8_bom_does_not_poison_the_first_header(self):
        """UNHCR's export carries one; without this the first column's key
        becomes '﻿Country' and every lookup on it silently misses."""
        out = transcribe_csv(b"\xef\xbb\xbf" + self.CSV, "u")
        self.assertEqual(out["rows"][0]["Country"], "Chad")

    def test_provenance_is_recorded_the_same_way_as_a_workbook(self):
        import hashlib
        out = transcribe_csv(self.CSV, "https://example.org/x.csv")
        self.assertEqual(out["sha1"], hashlib.sha1(self.CSV).hexdigest())
        self.assertEqual(out["source_url"], "https://example.org/x.csv")
        self.assertTrue(out["fetched_at"].endswith("Z"))
