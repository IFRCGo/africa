"""ACAPS Seasonal Events Calendar -> seasonal_calendar rows.

WHY THIS EXISTS ALONGSIDE THE FEWS NET LOADER. FEWS NET publishes national bands
with bare names - "Lean", "Harvest", "Post-harvest". ACAPS publishes the same
seasons with the crop named, a sentence explaining what happens, the admin-1
regions each one applies to, and the organisation that made the assessment with a
link to its document. The office asked for the ACAPS calendar for that reason, and
both are kept so a reader can see either.

ACAPS IS AN AGGREGATOR, AND THE ROWS SAY SO. The assessment behind each event is
USDA's, FAO's, FEWS NET's or WFP's; `source` records 'acaps' because that is where
we got it, and `source_org` records who actually judged it. Losing that distinction
would credit ACAPS with work it collated rather than did.

The CSV export and the MCP endpoint return the same records, so one parser reads
both: the CSV stores list fields as Python literals ("['SDN']") while the MCP
returns real lists, and _as_list flattens that difference.
"""
import ast
import csv
import io
from datetime import datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import SeasonalCalendar

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}

COUNTRY_NAMES = {
    "SDN": "Sudan", "TCD": "Chad", "EGY": "Egypt", "ETH": "Ethiopia",
    "LBY": "Libya", "SSD": "South Sudan", "UGA": "Uganda",
    "CAF": "Central African Republic", "ERI": "Eritrea",
}

# ACAPS's event types, mapped onto the four kinds the calendar strip colours by.
# "Seasonal hazard" gets its own kind rather than being forced into Dry or Rainy:
# a flood window is not a season, it is a warning, and it should not be coloured
# as though it were part of the agricultural cycle.
SEASON_TYPE = {
    "Lean season": "Lean",
    "Harvest": "Harvest",
    "Planting and growing": "Rainy",
    "Seasonal hazard": "Hazard",
    "Livestock": "Livestock",
    "Outbreak": "Hazard",
}


def _as_list(value):
    """CSV gives "['SDN']"; the MCP gives ['SDN']. Both end up a list."""
    if isinstance(value, list):
        return value
    if value in (None, "", "[]"):
        return []
    try:
        parsed = ast.literal_eval(value)
        return parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, SyntaxError):
        return [v.strip() for v in str(value).split(",") if v.strip()]


def _first(value, default=""):
    items = _as_list(value)
    return items[0] if items else default


def _span(month_numbers):
    """The contiguous span a set of months describes, wrap included.

    ACAPS publishes contiguous runs (verified across all 173 records), so a span
    is a faithful summary - but `months` remains the stored truth, and this only
    fills the start/end pair the strip reads.
    """
    if not month_numbers:
        return None, None
    ms = sorted(set(month_numbers))
    if len(ms) == 1:
        return ms[0], ms[0]
    # A run that wraps the year end shows up as one gap bigger than 1.
    gaps = [(b - a, i) for i, (a, b) in enumerate(zip(ms, ms[1:])) if b - a > 1]
    if not gaps:
        return ms[0], ms[-1]
    _, at = max(gaps)
    return ms[at + 1], ms[at]


def parse_records(records):
    """ACAPS records -> seasonal_calendar row dicts. Pure; no database access."""
    rows = []
    for r in records:
        iso3 = _first(r.get("iso"))
        if iso3 not in COUNTRY_NAMES:
            continue
        month_names = _as_list(r.get("months"))
        nums = [MONTH_NUM[m] for m in month_names if m in MONTH_NUM]
        if not nums:
            continue
        start, end = _span(nums)
        event_type = _first(r.get("event_type"))
        label = _first(r.get("label")) or _first(r.get("event")) or event_type

        raw_wide = r.get("country_wide")
        wide = raw_wide if isinstance(raw_wide, bool) else str(raw_wide).lower() == "true"

        sdate = None
        if r.get("source_date"):
            try:
                sdate = datetime.strptime(str(r["source_date"])[:10], "%Y-%m-%d").date()
            except ValueError:
                sdate = None

        rows.append({
            "iso3": iso3,
            "country_name": _first(r.get("country")) or COUNTRY_NAMES[iso3],
            "admin_pcode": None,          # ACAPS publishes GADM codes, not p-codes
            "source": "acaps",
            "source_ref": str(r.get("id") or ""),
            "label": label,
            "season_type": SEASON_TYPE.get(event_type, "Dry"),
            "purpose": None,
            "event": _first(r.get("event")),
            "event_type": event_type,
            "months": nums,
            "start_month": start,
            "end_month": end,
            "alignment": None,
            "description": (r.get("comment") or "").strip(),
            "aliases": [],
            "country_wide": wide,
            "admin_names": _as_list(r.get("adm1_eng_name")),
            "admin_codes": (r.get("adm1") or "").strip() or None,
            "source_org": (r.get("source") or "").strip() or None,
            "source_date": sdate,
            "source_url": (r.get("source_link") or "").strip() or None,
            "display_order": 0,
        })
    return rows


@register
class AcapsSeasonalLoader(Loader):
    dataset = "acaps_seasonal"
    source = "acaps"
    model = SeasonalCalendar
    tool = "list_seasonal_calendar"
    unique_fields = ["source", "iso3", "admin_pcode", "purpose", "label", "source_ref"]
    update_fields = [
        "country_name", "season_type", "event", "event_type", "months",
        "start_month", "end_month", "description", "country_wide", "admin_names",
        "admin_codes", "source_org", "source_date", "source_url", "display_order",
    ]

    def sync_key(self, iso3, context=None):
        # One row per country, so external_status can show which countries the
        # calendar covers rather than a single global "acaps" line.
        return {"source": self.source, "dataset": "seasonal_calendar",
                "iso3": iso3, "variant": "acaps-events"}

    def parse(self, payload, iso3, context=None):
        if isinstance(payload, dict):
            records = payload.get("results", payload.get("data", []))
        else:
            records = payload
        rows = parse_records(records)
        # The file carries every country ACAPS covers; a load names one.
        return [r for r in rows if not iso3 or r["iso3"] == iso3]


def read_csv(path):
    """The ACAPS CSV export, as records the parser understands."""
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))
