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

# ACAPS's vocabulary, mapped onto the kinds the calendar strip colours by.
#
# THE EVENT IS READ BEFORE THE EVENT_TYPE, and that ordering is the whole point.
# ACAPS's taxonomy splits "what the climate does" from "what people plant", and
# a rainy season lands on the climate side - which it files under the event_type
# "Seasonal hazard", alongside Floods, Locusts and Sandstorms. Keying on the
# event_type alone therefore typed every rainy and dry season as a hazard, and
# the strip drew Sudan's rains in the same red as a locust infestation.
#
# A rainy season is not a hazard. It is the most predictable feature of the
# agricultural year, and colouring it as a warning inverts what the calendar is
# for. So the specific event decides first, and the event_type is the fallback.
EVENT_TYPE_OF_EVENT = {
    "main wet/ rainy/ monsoon season": "Rainy",
    "2nd wet/ rainy/ monsoon season": "Rainy",
    "dry season": "Dry",
    "floods": "Hazard",
    "locust/ armyworm (caterpillar)": "Hazard",
    "sandstorms season": "Hazard",
    "malaria": "Hazard",
}

# Planting and harvest are two stages of one cycle and are typed apart so the
# strip can shade them as a sequence rather than as one undifferentiated block.
SEASON_TYPE = {
    "Lean season": "Lean",
    "Harvest": "Harvest",
    "Planting and growing": "Planting",
    "Seasonal hazard": "Hazard",
    "Livestock": "Livestock",
    "Outbreak": "Hazard",
}


def _season_type(event, event_type):
    """The normalised kind an ACAPS row belongs to, event first.

    THERE IS NO SILENT DEFAULT. This used to fall back to "Dry", which is how a
    rainy season came to be filed as a hazard and stayed that way unnoticed: a
    wrong answer that looks like a real season is invisible. A category ACAPS
    adds later comes out as "Other" instead, which the strip draws in grey and
    the legend names as unclassified - visible, and obviously not a claim.
    """
    hit = EVENT_TYPE_OF_EVENT.get((event or "").strip().lower())
    if hit:
        return hit
    return SEASON_TYPE.get((event_type or "").strip(), "Other")


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
            "season_type": _season_type(_first(r.get("event")), event_type),
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
