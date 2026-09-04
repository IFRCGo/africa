"""Step 3 of 7 - turn stored text into structured numbers, corridors and themes.

Three kinds of parser run over the corpus:

  1. Positional parsers   For Power BI map exports (the weekly mapping and the
                          returns dashboards). Those PDFs scatter numbers across
                          the page, so we re-open the PDF, read the position of
                          every word, and match each number to the nearest
                          country label.
  2. Narrative regex      For written reports: patterns that recognise phrases
                          like "over 1.2 million people have crossed into Chad".
  3. Taxonomy tagging     Counts mentions of hazards, vulnerabilities, coping
                          mechanisms, needs and movement patterns. This is what
                          the dashboard toggles are built from.

Everything this step writes is *derived* data, so it starts by deleting the
three derived tables and rebuilding them. The source text is never touched, so
you can re-tune a parser and re-run without re-reading a single PDF.
"""
import math
import re

import fitz

from django.db import transaction
from django.db.models import Max

from data_pipeline.common import (
    SOURCE_ROOT,
    load_gazetteer,
    load_taxonomy,
    parse_figure,
)
from data_track.models import (
    Document,
    DocumentText,
    Location,
    MovementFlow,
    NarrativeTag,
    PopulationFigure,
)

GAZ = load_gazetteer()
TAX = load_taxonomy()

# The many ways the reports spell each country.
COUNTRY_ALIASES = {
    "Chad": ["Chad", "CHAD", "Tchad"],
    "Egypt": ["Egypt", "EGYPT"],
    "South Sudan": ["South Sudan", "SOUTH SUDAN", "SOUTH  SUDAN"],
    "Ethiopia": ["Ethiopia", "ETHIOPIA"],
    "Central African Republic": ["Central African Republic", "CENTRAL AFRICAN REPUBLIC", "CAR", "C.A.R", "Central African Rep"],
    "Libya": ["Libya", "LIBYA"],
    "Uganda": ["Uganda", "UGANDA"],
    "Eritrea": ["Eritrea", "ERITREA"],
}

# Plausible range of cumulative arrivals per country. A number outside its
# country's range is a misread, so we throw it away rather than publish it.
ARRIVAL_BOUNDS = {
    "Chad": (5_000, 2_500_000), "Egypt": (5_000, 2_500_000),
    "South Sudan": (5_000, 2_500_000), "Ethiopia": (500, 500_000),
    "Central African Republic": (200, 200_000), "Libya": (500, 1_000_000),
    "Uganda": (200, 400_000), "Eritrea": (100, 150_000),
    "Regional": (50_000, 6_000_000),
}

# Look-up table: any spelling of a place -> its gazetteer entry.
LOC_BY_NAME = {}
for _loc in GAZ["locations"]:
    LOC_BY_NAME[_loc["name"].lower()] = _loc
    for _alias in (_loc.get("aliases") or "").split("|"):
        if _alias:
            LOC_BY_NAME.setdefault(_alias.lower(), _loc)


def anchor_for_country(country):
    """The single point we use to represent a whole country on the map."""
    for loc in GAZ["locations"]:
        if loc["kind"] == "country_anchor" and loc["country"] == country:
            return loc
    return None


class Collector:
    """Collects rows in memory, then writes them all at once.

    Saving 200,000 rows one at a time would take hours. Collecting them in a
    list and calling bulk_create at the end takes seconds.
    """

    def __init__(self):
        self.figures = []
        self.tags = []

    def add_figure(self, **fields):
        self.figures.append(PopulationFigure(**fields))

    def add_tag(self, **fields):
        self.tags.append(NarrativeTag(**fields))

    def save(self):
        PopulationFigure.objects.bulk_create(self.figures, batch_size=1000)
        NarrativeTag.objects.bulk_create(self.tags, batch_size=1000)


# ------------------------------------------------------------ positional helpers
# A word that looks like a printed figure: "1,234,567" or "740.3K".
NUM_RX = re.compile(r"^\d{1,3}(,\d{3})+$|^\d+(\.\d+)?[KkMm]$")


def page_words(page):
    """Every word on a PDF page as (left, top, right, bottom, text)."""
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def find_country_anchors(words):
    """Find the UPPERCASE country labels printed on a Power BI map export."""
    anchors = []
    singles = {"CHAD": "Chad", "EGYPT": "Egypt", "ETHIOPIA": "Ethiopia",
               "LIBYA": "Libya", "UGANDA": "Uganda", "ERITREA": "Eritrea"}
    for i, (x0, y0, x1, y1, t) in enumerate(words):
        if t in singles:
            anchors.append((singles[t], (x0 + x1) / 2, (y0 + y1) / 2))
        elif t == "SOUTH":
            # Two-word labels are split into two words by the PDF, so look for
            # the second word close by on the same line.
            for (a0, b0, a1, b1, t2) in words:
                if t2 == "SUDAN" and abs(b0 - y0) < 20 and abs(a0 - x0) < 60 and (a0, b0) != (x0, y0):
                    anchors.append(("South Sudan", (x0 + a1) / 2, (y0 + b1) / 2))
                    break
        elif t == "CENTRAL":
            for (a0, b0, a1, b1, t2) in words:
                if t2 == "AFRICAN" and 0 <= b0 - y0 < 25 and abs(a0 - x0) < 40:
                    anchors.append(("Central African Republic", (x0 + x1) / 2, (y0 + y1) / 2))
                    break
    return anchors


def assign_values_to_anchors(words, anchors, max_dist=170):
    """Give each number on the page to the closest country label.

    Returns {country: largest plausible value found near it}. Numbers further
    than max_dist points from any label are ignored.
    """
    out = {}
    for (x0, y0, x1, y1, t) in words:
        if not NUM_RX.match(t):
            continue
        v = parse_figure(t)
        if not v or v < 200:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best, best_distance = None, 1e9
        for (country, ax, ay) in anchors:
            d = math.hypot(cx - ax, cy - ay)   # straight-line distance on the page
            if d < best_distance:
                best, best_distance = country, d
        if best and best_distance <= max_dist:
            lo, hi = ARRIVAL_BOUNDS.get(best, (200, 5_000_000))
            if lo <= v <= hi and v > out.get(best, 0):
                out[best] = v
    return out


# ------------------------------------------------------------ weekly mapping
# The headline "stat cards" printed at the top of the weekly mapping PDF.
HEADLINE_LABELS = [
    ("Total Forcibly Displaced", "total_displaced", "mixed"),
    ("New IDPs in Sudan", "idps", "idps"),
    ("Refugees, Asylum Seekers\\s*\\n?and Returnees", "cumulative_arrivals_regional", "mixed"),
    ("Refugees and Asylum\\s*\\n?Seekers", "refugees_regional", "sudanese_refugees"),
    ("Refugee Returnees", "returnees_regional", "refugee_returnees"),
    ("Self-Relocated Refugees in\\s*\\n?Sudan", "self_relocated", "mixed"),
]


def parse_weekly_mapping(sink, doc_id, rel_path, report_date):
    """Read the weekly mapping PDF: headline cards + per-country map numbers."""
    path = SOURCE_ROOT / rel_path
    try:
        pdf = fitz.open(path)
    except Exception:
        return 0
    n = 0
    page = pdf[0]
    text = page.get_text("text")

    # Headline cards: a label followed by a value like "12.4M" or "740.3K".
    # Country cards use comma format, so requiring the K/M suffix avoids
    # accidentally picking up a country number as a headline.
    for label_rx, metric, group in HEADLINE_LABELS:
        best = None
        for m in re.finditer(label_rx + r"\s*\n\s*([\d.]+[MK])\b", text):
            v = parse_figure(m[1])
            if v and (best is None or v > best[0]):
                best = (v, m)
        if best:
            v, m = best
            sink.add_figure(
                document_id=doc_id, report_date=report_date,
                country=("Regional" if "regional" in metric or metric == "total_displaced" else "Sudan"),
                metric=metric.replace("_regional", ""), population_group=group, value=v,
                method="weekly_mapping_headline", confidence="high",
                snippet=m.group(0).replace("\n", " ")[:200],
            )
            n += 1

    # Per-country arrival totals printed on the map itself (positional parser).
    words = page_words(page)
    anchors = find_country_anchors(words)
    per_country = assign_values_to_anchors(words, anchors)
    for country, v in per_country.items():
        a = anchor_for_country(country)
        sink.add_figure(
            document_id=doc_id, report_date=report_date, country=country,
            location=a and a["name"], lat=a and a["lat"], lon=a and a["lon"],
            metric="cumulative_arrivals", population_group="mixed", value=v,
            method="weekly_mapping_positional", confidence="medium",
        )
        n += 1
    pdf.close()
    return n


# ------------------------------------------------------------ returns / influx series
RETURN_COUNTRIES = ["Egypt", "South Sudan", "Libya", "Chad", "Ethiopia", "Uganda"]


def _add_fig(sink, doc_id, report_date, country, metric, group, value, method, conf, snippet=None):
    """Shorthand for the many similar figure rows this file creates."""
    sink.add_figure(
        document_id=doc_id, report_date=report_date, country=country, metric=metric,
        population_group=group, value=value, method=method, confidence=conf,
        snippet=snippet and snippet.replace("\n", " ")[:250],
    )


def parse_sudan_return(sink, doc_id, rel_path, report_date, full_text):
    """Three different layouts share these filename families:

    A) "Influx from South Sudan"  (CORE_SUD, 2025) - arrivals INTO Sudan
    B) "Returns to Sudan" v1      (CORE_SDN_Return, 2025) - country panel
    C) "CORE Return Sudan v3"     (2026) - per-country cross-border table
    """
    n = 0
    text = full_text

    # --- A: influx from South Sudan into Sudan
    m = re.search(r"([\d,]+)\s*\n?\s*estimated Arrivals from\s*\n?\s*South Sudan", text)
    if m:
        v = parse_figure(m[1])
        if v and 1_000 <= v <= 2_000_000:
            _add_fig(sink, doc_id, report_date, "Sudan", "arrivals_from_south_sudan", "mixed",
                     v, "ssd_influx_headline", "high", m.group(0))
            n += 1
        return n

    # --- B: a panel listing departing countries then their values, in order
    m = re.search(r"Returns to Sudan[^\n]*\n(.{0,500}?)(?:Departing country|Returnees:|$)", text, re.S)
    if m:
        block = m[1]
        countries = re.findall(r"\b(Egypt|South\s*\n?Sudan|Libya|Chad|Ethiopia|Uganda)\b", block)
        values = re.findall(r"(?<![\d.%])(\d+(?:\.\d+)?[KkMm])\b", block)
        countries = [re.sub(r"\s+", " ", c) for c in countries]
        if countries and len(values) >= len(countries):
            total = 0
            for country, raw in zip(countries, values):
                v = parse_figure(raw)
                if not v or not (500 <= v <= 3_000_000):
                    continue
                _add_fig(sink, doc_id, report_date, country, "returns_to_sudan_from",
                         "refugee_returnees", v, "return_panel_v1", "medium")
                total += v
                n += 1
            if total > 10_000:
                _add_fig(sink, doc_id, report_date, "Sudan", "returns_to_sudan_total",
                         "refugee_returnees", total, "return_sum_components", "medium")
                n += 1
            return n

    # --- C: the 2026 layout - headline cards plus a positional row table
    if "Sudanese return from" in text or "CORE Return" in rel_path:
        # The two leading "M" values are returns from abroad and refugees in
        # neighbouring countries. Returns is always the smaller of the two.
        heads = [parse_figure(f"{a}M") for a in re.findall(r"([\d.]+)\s*M\b", text[:400])[:2]]
        heads = [v for v in heads if v and 100_000 <= v <= 8_000_000]
        if len(heads) == 2:
            _add_fig(sink, doc_id, report_date, "Sudan", "returns_to_sudan_total",
                     "refugee_returnees", min(heads), "return_v3_headline", "medium")
            _add_fig(sink, doc_id, report_date, "Regional", "cumulative_arrivals",
                     "mixed", max(heads), "return_v3_headline", "medium")
            n += 2
        try:
            pdf = fitz.open(SOURCE_ROOT / rel_path)
        except Exception:
            return n
        page = pdf[0]
        words = page_words(page)

        # Table rows are labelled with a trailing asterisk (Egypt*, Libya*...).
        # On each such line, the largest K/M value is the cumulative movement.
        return_caps = {"Egypt": 1_500_000, "South Sudan": 600_000, "Libya": 400_000,
                       "Chad": 250_000, "Ethiopia": 80_000, "Uganda": 30_000}
        col_words = {t[:-1]: (x0, (y0 + y1) / 2)
                     for (x0, y0, x1, y1, t) in words
                     if t.endswith("*") and t[:-1] in ("Egypt", "Libya", "Chad", "Ethiopia", "Uganda")}
        for (x0, y0, x1, y1, t) in words:
            if t == "South":
                for (a0, b0, a1, b1, t2) in words:
                    if t2 == "Sudan*" and abs(b0 - y0) < 4 and 0 < a0 - x1 < 30:
                        col_words["South Sudan"] = (x0, (y0 + y1) / 2)
        vals = {}
        for (x0, y0, x1, y1, t) in words:
            if not re.fullmatch(r"\d+(\.\d+)?[KkMm]", t):
                continue
            v = parse_figure(t)
            if not v or v < 500:
                continue
            cy = (y0 + y1) / 2
            for country, (cx0, ccy) in col_words.items():
                # Same line (within 7 points) and to the right of the label.
                if abs(cy - ccy) < 7 and x0 > cx0 and v <= return_caps[country]:
                    if v > vals.get(country, 0):
                        vals[country] = v
        pdf.close()
        for country, v in vals.items():
            _add_fig(sink, doc_id, report_date, country, "returns_to_sudan_from",
                     "refugee_returnees", v, "return_v3_row", "medium")
            n += 1
    return n


# ------------------------------------------------------------ narrative regex
COUNTRY_RX = "|".join(sorted({a for v in COUNTRY_ALIASES.values() for a in v}, key=len, reverse=True))
VALUE_RX = r"(\d[\d,]*(?:\.\d+)?\s*(?:million|M\b|K\b)?)"

# Each entry is (pattern to look for, what kind of number it is).
NARRATIVE_PATTERNS = [
    # "over 1.2 million people crossed into Chad"
    (re.compile(
        rf"(?:more than|over|nearly|approximately|about|some|estimated(?: at)?)?\s*{VALUE_RX}\s*"
        rf"(?:people|individuals|persons|refugees|new arrivals|arrivals|Sudanese(?:\s+refugees)?|returnees)?"
        rf"[^.\n]{{0,90}}?(?:crossed|arrived|fled|entered|sought (?:refuge|safety))[^.\n]{{0,60}}?"
        rf"(?:into|in|to|at)\s+(?:the\s+)?({COUNTRY_RX})", re.I),
     "cumulative_arrivals"),
    # country followed by a figure in brackets: "Chad (768,000)"
    (re.compile(rf"({COUNTRY_RX})\s*\(\s*{VALUE_RX}\s*\)"), "cumulative_arrivals_enum"),
    # "X million have fled into neighbouring countries"
    (re.compile(rf"{VALUE_RX}\s*(?:people|individuals|persons|refugees(?: and asylum[- ]seekers)?)?"
                rf"[^.\n]{{0,80}}?(?:crossed|fled|arrived|sought (?:refuge|safety))[^.\n]{{0,60}}?"
                rf"(?:into|in|to)\s+(?:the\s+)?neighbouring countries", re.I), "regional_arrivals"),
    # internally displaced, written either way round
    (re.compile(rf"{VALUE_RX}\s*(?:people|persons|individuals)?\s*(?:are\s+|have been\s+|newly\s+)?"
                rf"internally displaced", re.I), "idps"),
    (re.compile(rf"internally displaced(?:\s+persons)?(?:\s*\(IDPs?\))?[^.\n]{{0,40}}?{VALUE_RX}", re.I), "idps"),
    # returns to Sudan
    (re.compile(rf"{VALUE_RX}\s*(?:people|persons|individuals|Sudanese|refugees|returnees)?"
                rf"[^.\n]{{0,80}}?returned[^.\n]{{0,40}}?(?:to\s+)?Sudan", re.I), "returns_to_sudan_total"),
    # total displaced
    (re.compile(rf"{VALUE_RX}\s*(?:people|persons)?\s*(?:have been\s+)?(?:forcibly\s+)?displaced", re.I),
     "total_displaced"),
]


def parse_value_text(s):
    """Read '1.2 million', '740K' or '1,013,927' out of matched narrative text."""
    s = s.strip()
    m = re.match(r"([\d,]*\.?\d+)\s*(million|M|K)?", s, re.I)
    if not m:
        return None
    v = float(m[1].replace(",", ""))
    suffix = (m[2] or "").lower()
    if suffix in ("million", "m"):
        v *= 1_000_000
    elif suffix == "k":
        v *= 1_000
    return int(v)


def normalize_country(s):
    """Map any spelling back to the country name we store."""
    for country, aliases in COUNTRY_ALIASES.items():
        if s.strip().lower() in (a.lower() for a in aliases):
            return country
    return s.strip()


def parse_narrative(sink, doc_id, report_date, country_focus, text):
    """Pull figures out of written reports, rejecting implausible values."""
    n = 0
    seen = set()
    for rx, metric in NARRATIVE_PATTERNS:
        for m in rx.finditer(text):
            # Different patterns capture the country and value in different
            # positions, so unpack each one its own way.
            if metric == "cumulative_arrivals_enum":
                country, raw_v = normalize_country(m[1]), m[2]
                metric_out = "cumulative_arrivals"
            elif metric == "cumulative_arrivals":
                raw_v, country = m[1], normalize_country(m[2])
                metric_out = metric
            elif metric == "regional_arrivals":
                raw_v, country = m[1], "Regional"
                metric_out = "cumulative_arrivals"
            else:
                raw_v = m[1]
                country = "Sudan" if metric != "total_displaced" else "Regional"
                metric_out = metric

            v = parse_value_text(raw_v)
            if not v:
                continue

            # Sanity bounds - a figure outside these is a misread sentence.
            if metric_out == "cumulative_arrivals":
                lo, hi = ARRIVAL_BOUNDS.get(country, (0, 0))
                if not (lo <= v <= hi):
                    continue
            elif metric_out == "idps" and not (100_000 <= v <= 15_000_000):
                continue
            elif metric_out == "total_displaced" and not (500_000 <= v <= 20_000_000):
                continue
            elif metric_out == "returns_to_sudan_total" and not (5_000 <= v <= 5_000_000):
                continue

            # The same number is often repeated in one report; keep it once.
            key = (metric_out, country, v)
            if key in seen:
                continue
            seen.add(key)

            snippet = text[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip()
            a = anchor_for_country(country)
            sink.add_figure(
                document_id=doc_id, report_date=report_date, country=country,
                location=a and a["name"], lat=a and a["lat"], lon=a and a["lon"],
                metric=metric_out, population_group="mixed", value=v,
                method="narrative_regex", confidence="medium", snippet=snippet[:300],
            )
            n += 1
    return n


# ------------------------------------------------------------ taxonomy tagging
# Compile every keyword pattern once, grouped by dimension and tag.
TAX_COMPILED = {
    dim: {tag: [re.compile(p, re.I) for p in pats] for tag, pats in tags.items()}
    for dim, tags in TAX.items() if not dim.startswith("_")
}
# Two example sentences per tag per document is enough evidence; more would
# balloon the table without telling the reader anything new.
MAX_SNIPPETS_PER_TAG = 2


def tag_document(sink, doc_id, report_date, country_focus, text):
    """Record which themes a document mentions, with a sample sentence each."""
    n = 0
    for dim, tags in TAX_COMPILED.items():
        for tag, patterns in tags.items():
            hits = 0
            for rx in patterns:
                for m in rx.finditer(text):
                    snippet = text[max(0, m.start() - 80):m.end() + 120].replace("\n", " ").strip()
                    sink.add_tag(
                        document_id=doc_id, report_date=report_date, dimension=dim,
                        tag=tag, country=country_focus, snippet=snippet[:280],
                    )
                    n += 1
                    hits += 1
                    if hits >= MAX_SNIPPETS_PER_TAG:
                        break
                if hits >= MAX_SNIPPETS_PER_TAG:
                    break
    return n


# ------------------------------------------------------------ flows
def build_flows():
    """Turn per-country arrival/return figures into corridor rows for the map."""
    MovementFlow.objects.all().delete()
    corridors = GAZ["corridors"]
    by_country = GAZ["country_for_corridor"]

    def loc(name):
        return LOC_BY_NAME.get(name.lower())

    # One row per document/date/country/metric, keeping the largest value -
    # the same grouping the original SQL did.
    grouped = (
        PopulationFigure.objects
        .filter(metric__in=["cumulative_arrivals", "returns_to_sudan_from",
                            "arrivals_from_south_sudan"])
        .values("document_id", "report_date", "country", "metric")
        .annotate(value=Max("value"))
        .order_by("document_id", "report_date", "country", "metric")
    )

    rows = []
    for row in grouped:
        country, metric = row["country"], row["metric"]
        # Decide which corridor this observation belongs to.
        if metric == "cumulative_arrivals":
            cid = by_country.get(country) if country != "Regional" else None
        elif metric == "arrivals_from_south_sudan":
            cid = "south_sudan-sudan-influx"
        else:
            cid = {"Egypt": "egypt-sudan-return", "South Sudan": "south_sudan-sudan-return",
                   "Libya": "libya-sudan-return", "Chad": "chad-sudan-return"}.get(country)
        if not cid or cid not in corridors:
            continue

        c = corridors[cid]
        origin, destination = loc(c["origin"]), loc(c["destination"])
        if not (origin and destination):
            continue
        rows.append(MovementFlow(
            document_id=row["document_id"], report_date=row["report_date"], corridor=cid,
            origin=c["origin"], origin_lat=origin["lat"], origin_lon=origin["lon"],
            destination=c["destination"], dest_lat=destination["lat"], dest_lon=destination["lon"],
            flow_type=c["flow_type"], value=row["value"],
        ))

    MovementFlow.objects.bulk_create(rows, batch_size=1000)
    return len(rows)


# ------------------------------------------------------------ main
# Families whose text is plain narrative worth running the regex parsers over.
NARRATIVE_FAMILIES = (
    "regional_external_update", "flash_update", "egypt_update", "car_update",
    "protection_brief", "rrp_appeal", "sudan_ops", "thematic_report",
    "chad_core", "ethiopia_core", "ssd_core", "libya_core", "uganda_core",
    "car_core", "sudan_core_map", "egypt_other", "other",
)


def run():
    """Re-derive every figure, tag and flow from the stored text."""
    # This step is repeatable: wipe what it produced last time and start over.
    PopulationFigure.objects.all().delete()
    NarrativeTag.objects.all().delete()

    # Refresh the gazetteer table from gazetteer.json.
    Location.objects.all().delete()
    Location.objects.bulk_create([
        Location(name=loc["name"], country=loc["country"], admin1=loc.get("admin1"),
                 lat=loc["lat"], lon=loc["lon"], kind=loc["kind"],
                 aliases=loc.get("aliases", ""))
        for loc in GAZ["locations"]
    ])

    sink = Collector()
    counts = {"figures": 0, "tags": 0}

    documents = Document.objects.order_by("id").values_list(
        "id", "rel_path", "family", "country_focus", "report_date"
    )
    for doc_id, rel, family, country, report_date in documents:
        # Stitch the pages of this document back into one string.
        pages = (DocumentText.objects.filter(document_id=doc_id)
                 .order_by("page").values_list("text", flat=True))
        text = "\n".join(p for p in pages if p)

        if family == "weekly_mapping":
            counts["figures"] += parse_weekly_mapping(sink, doc_id, rel, report_date)
        elif family == "sudan_return":
            counts["figures"] += parse_sudan_return(sink, doc_id, rel, report_date, text)

        if text:
            if family in NARRATIVE_FAMILIES:
                counts["figures"] += parse_narrative(sink, doc_id, report_date, country, text)
            counts["tags"] += tag_document(sink, doc_id, report_date, country, text)

    # Write everything in one transaction, then build the corridors from it.
    with transaction.atomic():
        sink.save()
        flows = build_flows()

    print(f"figures: {counts['figures']}, tags: {counts['tags']}, flow rows: {flows}")
