"""The two hand-maintained workbooks -> movement_patterns rows.

    neighbouring countries Pop movement data.xlsx   one sheet per reporting date
    Sudan IDPs.xlsx                                 admin1 states, dated headers

THESE ARE NOT A LESSER SOURCE. The neighbours workbook runs to 2026 biweekly where
UNHCR's API stops at 2024, and Sudan IDPs.xlsx carries admin1 snapshots no MCP
layer produces at all. Reading them into the same table as the API sources is what
makes "the latest figure for Chad" a single query rather than a judgement call.

The reading rules are lifted from data_pipeline/steps/s07_xlsx.py rather than
reinvented, because they encode things learned from the actual files: column names
drift between sheets ('Sudanese refugees' and 'Sudanese refugees/asylum seekers'
both appear), dates arrive as either datetimes or strings, non-positive figures are
placeholders rather than data, and only headers of the form 'Population (DD Mon
YYYY)' carry a date - a bare 'Population' column must be ignored.
"""
import re
from datetime import date, datetime

# Both forms appear across the sheets.
SDN_COL_NAMES = {"Sudanese refugees/asylum seekers", "Sudanese refugees"}

COUNTRY_TO_ISO3 = {
    "car": "CAF", "central african republic": "CAF", "chad": "TCD",
    "egypt": "EGY", "ethiopia": "ETH", "libya": "LBY",
    "south sudan": "SSD", "uganda": "UGA", "sudan": "SDN",
}
CANONICAL_NAME = {
    "CAF": "Central African Republic", "TCD": "Chad", "EGY": "Egypt",
    "ETH": "Ethiopia", "LBY": "Libya", "SSD": "South Sudan",
    "UGA": "Uganda", "SDN": "Sudan",
}

# 'Population (15 Jan 2026)' -> 15 January 2026. A bare 'Population' yields None.
_HEADER_DATE = re.compile(r"\((\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})\)")
_MONTHS = {m.lower()[:3]: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def _as_date(value):
    """Excel gives a datetime; a hand-typed cell gives a string. Accept both."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _header_date(text):
    m = _HEADER_DATE.search(str(text or ""))
    if not m:
        return None
    month = _MONTHS.get(m[2].lower()[:3])
    if not month:
        return None
    try:
        return date(int(m[3]), month, int(m[1]))
    except ValueError:
        return None


def _positive_int(value):
    """A figure, or None. Zero and negatives are placeholders, not counts."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_neighbours_sheet(ws):
    """One sheet of the neighbours workbook -> refugee rows."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(c or "").strip() for c in rows[0]]
    if "Country" not in header:
        return []
    i_country = header.index("Country")
    i_date = next((i for i, h in enumerate(header) if h == "Data Date"), None)
    i_value = next((i for i, h in enumerate(header) if h in SDN_COL_NAMES), None)
    if i_date is None or i_value is None:
        return []

    out = []
    for row in rows[1:]:
        if not row or all(v is None for v in row):
            continue
        name = str(row[i_country] or "").strip() if i_country < len(row) else ""
        iso3 = COUNTRY_TO_ISO3.get(name.lower())
        when = _as_date(row[i_date]) if i_date < len(row) else None
        value = _positive_int(row[i_value]) if i_value < len(row) else None
        if not iso3 or when is None or value is None:
            continue
        out.append({
            "date": when, "iso3": iso3, "admin_pcode": None, "admin_level": 0,
            "place_name": CANONICAL_NAME[iso3], "metric": "refugees",
            "population_group": "sudanese_refugees", "value": value,
            "unit": "individuals", "source": "excel",
            "source_dataset": "neighbouring countries Pop movement data.xlsx",
            "reference_period_start": None, "reference_period_end": when,
            "lat": None, "lon": None,
        })
    return out


def parse_idp_states_sheet(ws):
    """Sudan IDPs.xlsx -> one row per state per dated column header."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    dated = [(i, _header_date(h)) for i, h in enumerate(rows[0])]
    dated = [(i, d) for i, d in dated if d]
    if not dated:
        return []

    out = []
    for row in rows[1:]:
        if not row or row[0] is None:
            continue
        state = str(row[0]).strip()
        if not state:
            continue
        for i, when in dated:
            value = _positive_int(row[i]) if i < len(row) else None
            if value is None:
                continue
            out.append({
                "date": when, "iso3": "SDN", "admin_pcode": None, "admin_level": 1,
                "place_name": state, "metric": "idps", "population_group": "idps",
                "value": value, "unit": "individuals", "source": "excel",
                "source_dataset": "Sudan IDPs.xlsx",
                "reference_period_start": None, "reference_period_end": when,
                "lat": None, "lon": None,
            })
    return out
