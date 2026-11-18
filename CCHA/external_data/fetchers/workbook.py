"""Any .xlsx, turned into the JSON a loader is handed.

SOURCE-AGNOSTIC ON PURPOSE. This module knows that a workbook is a set of named
sheets and a sheet is a rectangle of cells. It does not know what any of them
mean. Four workbook sources are planned and they share no layout at all, so
every scrap of understanding lives in the loader that needs it - which also
keeps each loader a pure function over JSON with a readable fixture.

WHY THE RAW BYTES ARE KEPT TOO. The cache exists so a payload that breaks a
parser is still on disk to look at, and a transcription is not the response. If
the parser and the publisher disagree, the bytes are the only artefact that can
settle it. This is the one place a fetcher writes to disk, because this is the
only layer that ever holds them.
"""
import csv
import hashlib
import io
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl
import requests
from django.conf import settings

from external_data.fetchers.base import FetchError, redact


def _cell(value):
    """One cell, as something JSON can hold."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (int, float, str)) or value is None:
        return value
    # A time, a timedelta, a rich-text run. Stringified rather than dropped:
    # a loader that meets one should see it and say so.
    return str(value)


def transcribe(content, source_url):
    """bytes -> the payload dict. Pure: no network, no disk."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True,
                                          data_only=True)
    except Exception as exc:
        raise FetchError(f"{source_url}: not a readable workbook ({exc})") from None

    sheets = {}
    for sheet in workbook.worksheets:
        # values_only gives tuples; lists are what JSON round-trips to, and a
        # test comparing against a list should not have to know the difference.
        sheets[sheet.title] = [
            [_cell(c) for c in row] for row in sheet.iter_rows(values_only=True)
        ]
    workbook.close()

    return {
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha1": hashlib.sha1(content).hexdigest(),
        "sheets": sheets,
    }


def transcribe_csv(content, source_url):
    """bytes -> the payload dict, rows as dicts. Pure: no network, no disk.

    A DIFFERENT SHAPE FROM A WORKBOOK'S, deliberately. A workbook is sheets of
    positional cells and its loader has to find its own header; a CSV is one
    table that already names its columns. Forcing one shape onto both would
    make every loader carry the other format's ceremony.

    Decoded as utf-8-sig: UNHCR's export carries a BOM, and without stripping
    it the first column's key becomes '﻿Country' - every lookup on that
    column then misses, silently, and the loader sees an empty series.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Some publishers still emit Windows-1252. Better a mangled accent
        # than a failed pull.
        text = content.decode("cp1252", errors="replace")

    rows = list(csv.DictReader(io.StringIO(text)))
    return {
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha1": hashlib.sha1(content).hexdigest(),
        "rows": rows,
    }


def _download(call, expect_zip):
    """GET the bytes, or raise FetchError with the secrets already removed."""
    try:
        response = requests.get(call.url, params=call.params or None, timeout=180,
                                headers={"Accept": "*/*", **(call.headers or {})})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(redact(f"{call.url}: {exc}")) from None

    # An HTML error page is a 200 on some CKAN mirrors. Saying which beats
    # "not a readable workbook" from openpyxl three frames down.
    if expect_zip and response.content[:2] != b"PK":
        raise FetchError(redact(
            f"{call.url}: response was not a workbook (first bytes "
            f"{response.content[:16]!r}) - an HTML error page looks like this."))
    if not expect_zip and response.content[:15].lstrip()[:1] == b"<":
        raise FetchError(redact(
            f"{call.url}: response was HTML, not CSV (first bytes "
            f"{response.content[:16]!r})."))
    return response.content


def fetch_csv(call):
    """Download the .csv, keep the bytes, and return the transcription."""
    content = _download(call, expect_zip=False)
    raw_path = Path(settings.API_CACHE_DIR) / call.cache_path.with_suffix(".csv")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(content)
    return transcribe_csv(content, call.url)


def fetch_workbook(call):
    """Download the .xlsx, keep the bytes, and return the transcription."""
    content = _download(call, expect_zip=True)
    raw_path = Path(settings.API_CACHE_DIR) / call.cache_path.with_suffix(".xlsx")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(content)
    return transcribe(content, call.url)
