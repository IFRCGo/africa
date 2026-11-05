"""Shared helpers used by every pipeline step.

Three groups of things live here:

  1. Folder shortcuts  - where the PDFs, the dashboard data and the caches are.
                         The real values come from Django settings, which read
                         them from the .env file, so nothing is hard-coded.
  2. Document families - a list of filename patterns that says which report
                         series a PDF belongs to and which country it covers.
  3. Text helpers      - pulling a date or a number out of messy report text.

None of this touches the database; the steps do that with the Django models.
"""
import json
import re
from datetime import date, datetime

from django.conf import settings

# --------------------------------------------------------------- folders
# This file sits in data_pipeline/, so PIPELINE_DIR is that folder.
PIPELINE_DIR = settings.BASE_DIR / "data_pipeline"

# Re-exported from settings so the steps can simply do "from data_pipeline.common import ...".
SOURCE_ROOT = settings.SOURCE_ROOT                  # the SUDAN Ops folder
SOURCE_COLLECTIONS = settings.SOURCE_COLLECTIONS    # the two PDF folders
DASHBOARD_DATA = settings.DASHBOARD_DATA_DIR        # dashboard/data/, served by the dashboard app
MCP_CACHE = settings.API_CACHE_DIR        # raw MCP pulls

# The day fighting broke out in Khartoum - the start of every timeline.
CRISIS_START = date(2023, 4, 15)


def load_gazetteer():
    """Place names, coordinates and the movement corridors between them."""
    return json.loads((PIPELINE_DIR / "gazetteer.json").read_text(encoding="utf-8"))


def load_taxonomy():
    """The keyword lists behind the hazard / need / coping toggles."""
    return json.loads((PIPELINE_DIR / "taxonomy.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- families
# Ordered rules: the first pattern that matches the filename wins.
# (family, country the series reports on, regular expression to look for)
FAMILY_RULES = [
    ("weekly_mapping",      "Regional",                  r"Sudan Situation Weekly Update Mapping"),
    ("regional_external_update", "Regional",             r"Sudan Situation - UNHCR External Update"),
    ("flash_update",        "Regional",                  r"Flash Update"),
    ("egypt_update",        "Egypt",                     r"UNHCR Egypt"),
    ("egypt_other",         "Egypt",                     r"Egypt"),
    ("car_core",            "Central African Republic",  r"CAR_(Core_)?Sudan_Situation|CAR_Sudan|CAR - SUDAN|SUDAN REFUGEE SITUATION in CAR"),
    ("car_update",          "Central African Republic",  r"UNHCR CAR|CAR External Update|update_CAR|Central African Republic"),
    ("ethiopia_offtopic",   "Ethiopia",                  r"Somali Region"),
    ("ethiopia_core",       "Ethiopia",                  r"ETHIOPIA CORE|eth_CORE|ETH_CORE|UNHCR ETHIOPIA|UNHCR Ethiopia|ETHIOPIA Sudan Situation|Protection Brief Ethiopia|AMH - UNHCR"),
    ("sudan_return",        "Sudan",                     r"CORE_SDN_Return|CORE Return Sudan|CORE_SUD_"),
    ("chad_core",           "Chad",                      r"HCR_CORE_TCD|CORE HCR_TCD|HCR_TCD|tcd_core|TCD_|P21 - TCD|Chad"),
    ("ssd_core",            "South Sudan",               r"SSD_CORE|ssd_core|CORE_SSD|South Sudan|Renk|Joda|SSD "),
    ("libya_core",          "Libya",                     r"core_lby|Libya"),
    ("uganda_core",         "Uganda",                    r"uga_core|Uganda"),
    ("sudan_core_map",      "Sudan",                     r"sdn_core|sdn_situation_map"),
    ("sudan_ops",           "Sudan",                     r"UNHCR Sudan|Overview of Refugees|Sudan cross border|Position on Returns|Cross border movement"),
    ("protection_brief",    "Regional",                  r"Protection Brief|GBV|Child Protection|GBViE"),
    ("rrp_appeal",          "Regional",                  r"RRP|Refugee Response Plan|Response Plan|Supp Appeal|Supplementary Appeal|At[- ][Aa][- ]Glance|EmergencyRRP"),
    ("thematic_report",     "Regional",                  r"Socioeconomic Profile|Intention Survey|Border Monitoring|War Infographic|Impact Update|3 Year Update|Life-saving Needs|CBI Dashboard|IT Emergency"),
    ("other",               "Regional",                  r"."),   # catch-all: matches anything
]
# Compile the patterns once, so matching thousands of filenames stays fast.
FAMILY_RULES = [(fam, c, re.compile(rx, re.I)) for fam, c, rx in FAMILY_RULES]


def classify(file_name: str):
    """Return (family, country_focus) for a PDF filename."""
    for family, country, rx in FAMILY_RULES:
        if rx.search(file_name):
            return family, country
    return "other", "Regional"


# ---------------------------------------------------------------- dates
# Month name -> month number, including three-letter abbreviations.
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
for m, i in list(MONTHS.items()):
    MONTHS[m[:3]] = i
MONTHS["sept"] = 9

# One regular expression that matches any month spelling used in the reports
# (including the recurring typo "Febraury").
_MONTH_RX = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Febraury)"


def _valid(y, m, d):
    """Return a real date, or None if the numbers are not a plausible report date."""
    try:
        dt = date(y, m, d)
    except ValueError:
        return None            # e.g. 31 February
    if date(2022, 1, 1) <= dt <= date(2027, 12, 31):
        return dt
    return None                # outside the crisis window: almost certainly a misread


def parse_date_from_name(name: str, year_hint: int | None = None):
    """Try hard to pull a report date out of a UNHCR filename.

    UNHCR filenames spell dates a dozen different ways, so each block below
    handles one style and the first one that produces a valid date wins.
    """
    name = re.sub(r"\[\d+\]", "", name)            # drop "[1]" download suffixes
    name = name.replace("Febraury", "February")

    # yyyy-mm-dd or yyyy_mm_dd
    m = re.search(r"(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})", name)
    if m:
        dt = _valid(int(m[1]), int(m[2]), int(m[3]))
        if dt:
            return dt
    # "15 March 2024"
    m = re.search(rf"(\d{{1,2}})[\s\-_]*({_MONTH_RX})[\s\-_.,]*(20\d{{2}})", name, re.I)
    if m:
        dt = _valid(int(m[3]), MONTHS[m[2].lower()[:3]] if m[2].lower()[:4] != "sept" else 9, int(m[1]))
        if dt:
            return dt
    # "March 15, 2024"
    m = re.search(rf"({_MONTH_RX})[\s\-_.,]*(\d{{1,2}})[\s\-_.,]+(20\d{{2}})", name, re.I)
    if m:
        dt = _valid(int(m[3]), MONTHS[m[1].lower()[:3]], int(m[2]))
        if dt:
            return dt
    # "March 2024" with no day: assume mid-month.
    m = re.search(rf"({_MONTH_RX})[\s\-_.]*\s*(20\d{{2}})", name, re.I)
    if m:
        dt = _valid(int(m[2]), MONTHS[m[1].lower()[:3]], 15)
        if dt:
            return dt
    # yyyymmdd anywhere in the name
    for g in re.findall(r"(20\d{6})", name):
        dt = _valid(int(g[:4]), int(g[4:6]), int(g[6:8]))
        if dt:
            return dt
    # ddmmyyyy (e.g. "as of 02092023")
    for g in re.findall(r"(?<!\d)(\d{8})(?!\d)", name):
        dt = _valid(int(g[4:8]), int(g[2:4]), int(g[0:2]))
        if dt:
            return dt
    # dd mm yyyy with separators (e.g. "v3 15 02 2026")
    m = re.search(r"(?<!\d)(\d{1,2})[ ._-](\d{1,2})[ ._-](20\d{2})(?!\d)", name)
    if m:
        dt = _valid(int(m[3]), int(m[2]), int(m[1]))
        if dt:
            return dt
    # dd.mm.yy (e.g. "24.03.26")
    m = re.search(r"(?<!\d)(\d{1,2})[._](\d{1,2})[._](2[3-7])(?!\d)", name)
    if m:
        dt = _valid(2000 + int(m[3]), int(m[2]), int(m[1]))
        if dt:
            return dt
    # yymmdd (e.g. "uga_core_241007")
    for g in re.findall(r"(?<!\d)(2[3-7]\d{4})(?!\d)", name):
        dt = _valid(2000 + int(g[:2]), int(g[2:4]), int(g[4:6]))
        if dt:
            return dt
    # date ranges like "13-19022026": use the end date
    m = re.search(r"(?<!\d)\d{1,2}-(\d{2})(\d{2})(20\d{2})", name)
    if m:
        dt = _valid(int(m[3]), int(m[2]), int(m[1]))
        if dt:
            return dt
    return None


def parse_date_from_text(text: str):
    """Fallback when the filename has no date: scan the first page for one."""
    for rx in (
        rf"(?:Published|as of|As of|AS OF)[:\s]*?(\d{{1,2}})\s+({_MONTH_RX})[,\s]+(20\d{{2}})",
        rf"(\d{{1,2}})\s+({_MONTH_RX})[,\s]+(20\d{{2}})",
    ):
        m = re.search(rx, text[:4000], re.I)
        if m:
            mo = MONTHS.get(m[2].lower()[:3])
            if mo:
                dt = _valid(int(m[3]), mo, int(m[1]))
                if dt:
                    return dt
    m = re.search(rf"({_MONTH_RX})\s+(\d{{1,2}}),\s+(20\d{{2}})", text[:4000], re.I)
    if m:
        mo = MONTHS.get(m[1].lower()[:3])
        if mo:
            dt = _valid(int(m[3]), mo, int(m[2]))
            if dt:
                return dt
    return None


# ---------------------------------------------------------------- numbers
def parse_figure(s: str):
    """Turn a printed figure into a plain integer.

    '1,013,927' -> 1013927     '740.3K' -> 740300      '12.4M' -> 12400000
    Returns None when the text is not a number we recognise.
    """
    s = s.strip().replace(" ", "")
    m = re.fullmatch(r"([\d,.]+)\s*([KkMm])?", s)
    if not m:
        return None
    num, suffix = m[1], m[2]
    try:
        if suffix and suffix.lower() == "m":
            return int(float(num.replace(",", "")) * 1_000_000)
        if suffix and suffix.lower() == "k":
            return int(float(num.replace(",", "")) * 1_000)
        return int(num.replace(",", ""))
    except ValueError:
        return None


def iso(d):
    """Format a date as 'YYYY-MM-DD'; anything else is returned untouched."""
    return d.isoformat() if isinstance(d, (date, datetime)) else d
