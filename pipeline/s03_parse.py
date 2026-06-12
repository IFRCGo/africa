"""Step 3: structured extraction into population_figures, movement_flows, narrative_tags.

Parsers
  - weekly_mapping / sudan_return: positional (re-opens the PDF; Power BI exports
    scatter numbers across the page, so values are matched to the nearest country label)
  - all narrative families: regex extraction of displacement / arrival / return figures
  - all families: taxonomy tagging for hazards, vulnerabilities, coping, needs, movement patterns
"""
import math
import re

import fitz

from common import ROOT_DIR, get_db, load_gazetteer, load_taxonomy, parse_figure

GAZ = load_gazetteer()
TAX = load_taxonomy()

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
# plausibility bounds for cumulative arrivals per country (reject misassigned numbers)
ARRIVAL_BOUNDS = {
    "Chad": (5_000, 2_500_000), "Egypt": (5_000, 2_500_000),
    "South Sudan": (5_000, 2_500_000), "Ethiopia": (500, 500_000),
    "Central African Republic": (200, 200_000), "Libya": (500, 1_000_000),
    "Uganda": (200, 400_000), "Eritrea": (100, 150_000),
    "Regional": (50_000, 6_000_000),
}

LOC_BY_NAME = {}
for loc in GAZ["locations"]:
    LOC_BY_NAME[loc["name"].lower()] = loc
    for a in (loc.get("aliases") or "").split("|"):
        if a:
            LOC_BY_NAME.setdefault(a.lower(), loc)


def anchor_for_country(country):
    for loc in GAZ["locations"]:
        if loc["kind"] == "country_anchor" and loc["country"] == country:
            return loc
    return None


# ------------------------------------------------------------ positional helpers
NUM_RX = re.compile(r"^\d{1,3}(,\d{3})+$|^\d+(\.\d+)?[KkMm]$")


def page_words(page):
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def find_country_anchors(words):
    """Locate uppercase country labels on the map area of a Power BI export."""
    anchors = []
    singles = {"CHAD": "Chad", "EGYPT": "Egypt", "ETHIOPIA": "Ethiopia",
               "LIBYA": "Libya", "UGANDA": "Uganda", "ERITREA": "Eritrea"}
    for i, (x0, y0, x1, y1, t) in enumerate(words):
        if t in singles:
            anchors.append((singles[t], (x0 + x1) / 2, (y0 + y1) / 2))
        elif t == "SOUTH":
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
    """Map numeric words to the nearest country label; return {country: max_value}."""
    out = {}
    for (x0, y0, x1, y1, t) in words:
        if not NUM_RX.match(t):
            continue
        v = parse_figure(t)
        if not v or v < 200:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best, bd = None, 1e9
        for (country, ax, ay) in anchors:
            d = math.hypot(cx - ax, cy - ay)
            if d < bd:
                best, bd = country, d
        if best and bd <= max_dist:
            lo, hi = ARRIVAL_BOUNDS.get(best, (200, 5_000_000))
            if lo <= v <= hi and v > out.get(best, 0):
                out[best] = v
    return out


# ------------------------------------------------------------ weekly mapping
HEADLINE_LABELS = [
    ("Total Forcibly Displaced", "total_displaced", "mixed"),
    ("New IDPs in Sudan", "idps", "idps"),
    ("Refugees, Asylum Seekers\\s*\\n?and Returnees", "cumulative_arrivals_regional", "mixed"),
    ("Refugees and Asylum\\s*\\n?Seekers", "refugees_regional", "sudanese_refugees"),
    ("Refugee Returnees", "returnees_regional", "refugee_returnees"),
    ("Self-Relocated Refugees in\\s*\\n?Sudan", "self_relocated", "mixed"),
]


def parse_weekly_mapping(cur, doc_id, rel_path, report_date):
    path = ROOT_DIR / rel_path
    try:
        pdf = fitz.open(path)
    except Exception:
        return 0
    n = 0
    page = pdf[0]
    text = page.get_text("text")
    # headline stat cards: label followed closely by a K/M value like 12.4M / 740.3K
    # (country cards use comma format, so requiring the suffix avoids cross-matches)
    for label_rx, metric, group in HEADLINE_LABELS:
        best = None
        for m in re.finditer(label_rx + r"\s*\n\s*([\d.]+[MK])\b", text):
            v = parse_figure(m[1])
            if v and (best is None or v > best[0]):
                best = (v, m)
        if best:
            v, m = best
            cur.execute(
                """INSERT INTO population_figures (document_id, report_date, country, metric,
                       population_group, value, method, confidence, snippet)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (doc_id, report_date, "Regional" if "regional" in metric or metric == "total_displaced" else "Sudan",
                 metric.replace("_regional", ""), group, v, "weekly_mapping_headline", "high",
                 m.group(0).replace("\n", " ")[:200]),
            )
            n += 1
    # per-country arrival totals from map cards (positional)
    words = page_words(page)
    anchors = find_country_anchors(words)
    per_country = assign_values_to_anchors(words, anchors)
    for country, v in per_country.items():
        a = anchor_for_country(country)
        cur.execute(
            """INSERT INTO population_figures (document_id, report_date, country, location, lat, lon,
                   metric, population_group, value, method, confidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, report_date, country, a and a["name"], a and a["lat"], a and a["lon"],
             "cumulative_arrivals", "mixed", v, "weekly_mapping_positional", "medium"),
        )
        n += 1
    pdf.close()
    return n


# ------------------------------------------------------------ returns / influx series
RETURN_COUNTRIES = ["Egypt", "South Sudan", "Libya", "Chad", "Ethiopia", "Uganda"]


def _insert_fig(cur, doc_id, report_date, country, metric, group, value, method, conf, snippet=None):
    cur.execute(
        """INSERT INTO population_figures (document_id, report_date, country, metric,
               population_group, value, method, confidence, snippet)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (doc_id, report_date, country, metric, group, value, method, conf,
         snippet and snippet.replace("\n", " ")[:250]),
    )


def parse_sudan_return(cur, doc_id, rel_path, report_date, full_text):
    """Three layouts share these filename families:
    A) 'Influx from South Sudan' (CORE_SUD 2025): arrivals INTO Sudan from South Sudan
    B) 'Returns to Sudan' v1 (CORE_SDN_Return 2025): departing-country panel, in-order lists
    C) 'CORE Return Sudan v3' (2026): per-asylum-country cross-border movement table
    """
    n = 0
    text = full_text
    # --- A: influx from South Sudan into Sudan
    m = re.search(r"([\d,]+)\s*\n?\s*estimated Arrivals from\s*\n?\s*South Sudan", text)
    if m:
        v = parse_figure(m[1])
        if v and 1_000 <= v <= 2_000_000:
            _insert_fig(cur, doc_id, report_date, "Sudan", "arrivals_from_south_sudan", "mixed",
                        v, "ssd_influx_headline", "high", m.group(0))
            n += 1
        return n
    # --- B: 'Returns to Sudan' panel: country names then K/M values, in order
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
                _insert_fig(cur, doc_id, report_date, country, "returns_to_sudan_from",
                            "refugee_returnees", v, "return_panel_v1", "medium")
                total += v
                n += 1
            if total > 10_000:
                _insert_fig(cur, doc_id, report_date, "Sudan", "returns_to_sudan_total",
                            "refugee_returnees", total, "return_sum_components", "medium")
                n += 1
            return n
    # --- C: v3 layout: total + per-country row table (positional)
    if "Sudanese return from" in text or "CORE Return" in rel_path:
        # headline cards: the two leading M-values are 'returns from abroad' and
        # 'refugees in neighbouring countries'; returns is always the smaller
        heads = [parse_figure(f"{a}M") for a in re.findall(r"([\d.]+)\s*M\b", text[:400])[:2]]
        heads = [v for v in heads if v and 100_000 <= v <= 8_000_000]
        if len(heads) == 2:
            _insert_fig(cur, doc_id, report_date, "Sudan", "returns_to_sudan_total",
                        "refugee_returnees", min(heads), "return_v3_headline", "medium")
            _insert_fig(cur, doc_id, report_date, "Regional", "cumulative_arrivals",
                        "mixed", max(heads), "return_v3_headline", "medium")
            n += 2
        try:
            pdf = fitz.open(ROOT_DIR / rel_path)
        except Exception:
            return n
        page = pdf[0]
        words = page_words(page)
        # table rows are uniquely labelled with a trailing asterisk (Egypt*, Libya*, ...);
        # the largest K/M value on the same line is cumulative cross-border return movement
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
                if abs(cy - ccy) < 7 and x0 > cx0 and v <= return_caps[country]:
                    if v > vals.get(country, 0):
                        vals[country] = v
        pdf.close()
        for country, v in vals.items():
            _insert_fig(cur, doc_id, report_date, country, "returns_to_sudan_from",
                        "refugee_returnees", v, "return_v3_row", "medium")
            n += 1
    return n


# ------------------------------------------------------------ narrative regex
COUNTRY_RX = "|".join(sorted({a for v in COUNTRY_ALIASES.values() for a in v}, key=len, reverse=True))
VALUE_RX = r"(\d[\d,]*(?:\.\d+)?\s*(?:million|M\b|K\b)?)"

NARRATIVE_PATTERNS = [
    # arrivals into a neighbouring country
    (re.compile(
        rf"(?:more than|over|nearly|approximately|about|some|estimated(?: at)?)?\s*{VALUE_RX}\s*"
        rf"(?:people|individuals|persons|refugees|new arrivals|arrivals|Sudanese(?:\s+refugees)?|returnees)?"
        rf"[^.\n]{{0,90}}?(?:crossed|arrived|fled|entered|sought (?:refuge|safety))[^.\n]{{0,60}}?"
        rf"(?:into|in|to|at)\s+(?:the\s+)?({COUNTRY_RX})", re.I),
     "cumulative_arrivals"),
    # country (figure) enumerations: 'Chad (768,000)'
    (re.compile(rf"({COUNTRY_RX})\s*\(\s*{VALUE_RX}\s*\)"), "cumulative_arrivals_enum"),
    # regional cross-border total: 'X million have crossed/fled into neighbouring countries'
    (re.compile(rf"{VALUE_RX}\s*(?:people|individuals|persons|refugees(?: and asylum[- ]seekers)?)?"
                rf"[^.\n]{{0,80}}?(?:crossed|fled|arrived|sought (?:refuge|safety))[^.\n]{{0,60}}?"
                rf"(?:into|in|to)\s+(?:the\s+)?neighbouring countries", re.I), "regional_arrivals"),
    # IDPs
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
    s = s.strip()
    m = re.match(r"([\d,]*\.?\d+)\s*(million|M|K)?", s, re.I)
    if not m:
        return None
    v = float(m[1].replace(",", ""))
    suf = (m[2] or "").lower()
    if suf in ("million", "m"):
        v *= 1_000_000
    elif suf == "k":
        v *= 1_000
    return int(v)


def normalize_country(s):
    for country, aliases in COUNTRY_ALIASES.items():
        if s.strip().lower() in (a.lower() for a in aliases):
            return country
    return s.strip()


def parse_narrative(cur, doc_id, report_date, country_focus, text):
    n = 0
    seen = set()
    for rx, metric in NARRATIVE_PATTERNS:
        for m in rx.finditer(text):
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
            key = (metric_out, country, v)
            if key in seen:
                continue
            seen.add(key)
            snippet = text[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip()
            a = anchor_for_country(country)
            cur.execute(
                """INSERT INTO population_figures (document_id, report_date, country, location, lat, lon,
                       metric, population_group, value, method, confidence, snippet)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, report_date, country, a and a["name"], a and a["lat"], a and a["lon"],
                 metric_out, "mixed", v, "narrative_regex", "medium", snippet[:300]),
            )
            n += 1
    return n


# ------------------------------------------------------------ taxonomy tagging
TAX_COMPILED = {
    dim: {tag: [re.compile(p, re.I) for p in pats] for tag, pats in tags.items()}
    for dim, tags in TAX.items() if not dim.startswith("_")
}
MAX_SNIPPETS_PER_TAG = 2


def tag_document(cur, doc_id, report_date, country_focus, text):
    n = 0
    for dim, tags in TAX_COMPILED.items():
        for tag, patterns in tags.items():
            hits = 0
            for rx in patterns:
                for m in rx.finditer(text):
                    snippet = text[max(0, m.start() - 80):m.end() + 120].replace("\n", " ").strip()
                    cur.execute(
                        """INSERT INTO narrative_tags (document_id, report_date, dimension, tag, country, snippet)
                           VALUES (?,?,?,?,?,?)""",
                        (doc_id, report_date, dim, tag, country_focus, snippet[:280]),
                    )
                    n += 1
                    hits += 1
                    if hits >= MAX_SNIPPETS_PER_TAG:
                        break
                if hits >= MAX_SNIPPETS_PER_TAG:
                    break
    return n


# ------------------------------------------------------------ flows
def build_flows(cur):
    """Convert per-country arrival/return observations into corridor flow rows."""
    cur.execute("DELETE FROM movement_flows")
    corridors = GAZ["corridors"]
    by_country = GAZ["country_for_corridor"]

    def loc(name):
        return LOC_BY_NAME.get(name.lower())

    n = 0
    rows = cur.execute(
        """SELECT document_id, report_date, country, metric, MAX(value)
           FROM population_figures
           WHERE metric IN ('cumulative_arrivals', 'returns_to_sudan_from', 'arrivals_from_south_sudan')
           GROUP BY document_id, report_date, country, metric"""
    ).fetchall()
    for doc_id, rdate, country, metric, value in rows:
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
        o, d = loc(c["origin"]), loc(c["destination"])
        if not (o and d):
            continue
        cur.execute(
            """INSERT INTO movement_flows (document_id, report_date, corridor, origin, origin_lat, origin_lon,
                   destination, dest_lat, dest_lon, flow_type, value)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, rdate, cid, c["origin"], o["lat"], o["lon"],
             c["destination"], d["lat"], d["lon"], c["flow_type"], value),
        )
        n += 1
    return n


# ------------------------------------------------------------ main
def main():
    con = get_db()
    cur = con.cursor()
    # idempotent: clear derived tables (extraction sources stay)
    cur.execute("DELETE FROM population_figures")
    cur.execute("DELETE FROM narrative_tags")

    # seed gazetteer table
    cur.execute("DELETE FROM locations")
    for loc in GAZ["locations"]:
        cur.execute("INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?,?,?)",
                    (loc["name"], loc["country"], loc.get("admin1"), loc["lat"], loc["lon"],
                     loc["kind"], loc.get("aliases", "")))

    docs = cur.execute(
        "SELECT id, rel_path, family, country_focus, report_date FROM documents ORDER BY id"
    ).fetchall()
    counts = {"figures": 0, "tags": 0}
    for doc_id, rel, family, country, rdate in docs:
        text = "\n".join(t for (t,) in cur.execute(
            "SELECT text FROM document_text WHERE document_id=? ORDER BY page", (doc_id,)))
        if family == "weekly_mapping":
            counts["figures"] += parse_weekly_mapping(cur, doc_id, rel, rdate)
        elif family == "sudan_return":
            counts["figures"] += parse_sudan_return(cur, doc_id, rel, rdate, text)
        if text:
            if family in ("regional_external_update", "flash_update", "egypt_update", "car_update",
                          "protection_brief", "rrp_appeal", "sudan_ops", "thematic_report",
                          "chad_core", "ethiopia_core", "ssd_core", "libya_core", "uganda_core",
                          "car_core", "sudan_core_map", "egypt_other", "other"):
                counts["figures"] += parse_narrative(cur, doc_id, rdate, country, text)
            counts["tags"] += tag_document(cur, doc_id, rdate, country, text)
    flows = build_flows(cur)
    con.commit()
    print(f"figures: {counts['figures']}, tags: {counts['tags']}, flow rows: {flows}")


if __name__ == "__main__":
    main()
