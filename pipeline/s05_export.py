"""Step 5: export platform JSON from the database.

Outputs into platform/data/:
  meta.json      - date range, corpus stats
  flows.json     - corridor geometry + cleaned cumulative time series
  headline.json  - regional headline series (total displaced, IDPs, arrivals, returns)
  events.json    - timeline events
  tags.json      - monthly counts + sample snippets per dimension/tag (the toggles)
  documents.json - source catalog
"""
import json
from collections import defaultdict
from datetime import date, datetime

from common import get_db, PLATFORM_DATA, load_gazetteer

GAZ = load_gazetteer()


def clean_series(points, monotone=True):
    """points: [(date, value)] -> sorted, deduped, outliers dropped.

    Pass 1: collapse same-date duplicates to the median, then reject values far
    from the rolling median of their neighbours (parser mis-reads).
    Pass 2 (cumulative metrics): enforce ~monotonic growth - once the series is
    established, reject sudden jumps (>1.45x) and regressions (<0.9x running max).
    """
    by_date = defaultdict(list)
    for d, v in points:
        if d and v:
            by_date[d].append(v)
    merged = []
    for d in sorted(by_date):
        vals = sorted(by_date[d])
        merged.append((d, vals[len(vals) // 2]))

    if not monotone:
        # rolling-median filter: tolerant of gradual change (IDPs decline as people
        # return) but rejects isolated mis-parses
        vals = [v for _, v in merged]
        out = []
        for i, (d, v) in enumerate(merged):
            win = sorted(vals[max(0, i - 2):i + 3])
            med = win[len(win) // 2]
            if med and (v > med * 2.0 or v < med * 0.5):
                continue
            out.append({"date": d, "value": v})
        return out

    # cumulative series: reject regressions; accept big jumps only when later
    # observations confirm the new level (genuine estimate revisions persist,
    # parser glitches do not)
    out, run_max = [], 0
    for i, (d, v) in enumerate(merged):
        if run_max and v < run_max * 0.9:
            continue
        if run_max >= 100_000 and v > run_max * 1.5:
            nxt = [x for _, x in merged[i + 1:i + 4]]
            need = min(2, len(nxt))
            if need == 0 or sum(1 for x in nxt if x >= v * 0.75) < need:
                continue
        out.append({"date": d, "value": v})
        run_max = max(run_max, v)
    return out


def main():
    con = get_db()
    cur = con.cursor()
    PLATFORM_DATA.mkdir(parents=True, exist_ok=True)

    def dump(name, obj):
        (PLATFORM_DATA / name).write_text(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {name:16} {(PLATFORM_DATA / name).stat().st_size / 1024:8.1f} KB")

    # ---- flows
    corridors = {}
    for cid, rdate, value in cur.execute(
            "SELECT corridor, report_date, value FROM movement_flows ORDER BY corridor, report_date"):
        corridors.setdefault(cid, []).append((rdate, value))
    geo = {}
    for cid, pts in corridors.items():
        row = cur.execute(
            """SELECT origin, origin_lat, origin_lon, destination, dest_lat, dest_lon, flow_type
               FROM movement_flows WHERE corridor=? LIMIT 1""", (cid,)).fetchone()
        series = clean_series(pts)
        if len(series) < 2:
            continue
        geo[cid] = {
            "origin": {"name": row[0], "lat": row[1], "lon": row[2]},
            "destination": {"name": row[3], "lat": row[4], "lon": row[5]},
            "flow_type": row[6],
            "series": series,
        }
    dump("flows.json", geo)

    # ---- headline series
    headline = {}
    metrics = {
        "total_displaced": "Total forcibly displaced",
        "idps": "Internally displaced (IDPs)",
        "cumulative_arrivals": "Refugees, asylum-seekers & returnees in neighbouring countries",
        "refugees": "Refugees & asylum-seekers (regional)",
        "returnees": "Refugee returnees (regional)",
        "returns_to_sudan_total": "Returns to Sudan",
        "self_relocated": "Self-relocated refugees in Sudan",
        "arrivals_from_south_sudan": "Arrivals into Sudan from South Sudan (2025 influx)",
    }
    for metric, label in metrics.items():
        if metric in ("idps", "total_displaced", "returns_to_sudan_total", "arrivals_from_south_sudan"):
            rows = cur.execute(
                """SELECT report_date, value FROM population_figures WHERE metric=?
                   ORDER BY report_date""", (metric,)).fetchall()
        else:
            rows = cur.execute(
                """SELECT report_date, value FROM population_figures
                   WHERE metric=? AND country='Regional' ORDER BY report_date""", (metric,)).fetchall()
        # IDPs/total can genuinely decline (returns), so no monotonicity there
        series = clean_series(rows, monotone=metric not in ("idps", "total_displaced"))
        if series:
            headline[metric] = {"label": label, "series": series}
    dump("headline.json", headline)

    # ---- events
    events = [
        {"date": r[0], "title": r[1], "description": r[2], "category": r[3],
         "location": r[4], "lat": r[5], "lon": r[6], "severity": r[7], "source": r[8]}
        for r in cur.execute(
            """SELECT event_date, title, description, category, location, lat, lon, severity, source
               FROM events WHERE event_date IS NOT NULL ORDER BY event_date""")
    ]
    dump("events.json", events)

    # ---- tags: monthly counts per dimension/tag (+country) and sample snippets
    counts = defaultdict(int)
    snippets = {}
    for dim, tag, country, rdate, snippet in cur.execute(
            """SELECT dimension, tag, country, report_date, snippet FROM narrative_tags
               WHERE report_date IS NOT NULL"""):
        month = rdate[:7]
        counts[(dim, tag, country, month)] += 1
        key = (dim, tag, month)
        if key not in snippets and snippet and len(snippet) > 60:
            snippets[key] = snippet
    tags_out = defaultdict(lambda: defaultdict(lambda: {"monthly": [], "snippets": {}}))
    for (dim, tag, country, month), n in sorted(counts.items()):
        tags_out[dim][tag]["monthly"].append({"month": month, "country": country, "count": n})
    for (dim, tag, month), s in snippets.items():
        tags_out[dim][tag]["snippets"][month] = s
    dump("tags.json", {d: dict(v) for d, v in tags_out.items()})

    # ---- documents catalog
    docs = [
        {"id": r[0], "file": r[1], "family": r[2], "country": r[3], "date": r[4],
         "collection": r[5], "pages": r[6]}
        for r in cur.execute(
            """SELECT id, file_name, family, country_focus, report_date, source_collection, pages
               FROM documents ORDER BY report_date""")
    ]
    dump("documents.json", docs)

    # ---- meta
    dr = cur.execute("SELECT MIN(report_date), MAX(report_date) FROM documents").fetchone()
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "documents": cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "pages": cur.execute("SELECT COUNT(*) FROM document_text").fetchone()[0],
        "figures": cur.execute("SELECT COUNT(*) FROM population_figures").fetchone()[0],
        "tags": cur.execute("SELECT COUNT(*) FROM narrative_tags").fetchone()[0],
        "events": cur.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "date_min": "2023-04-15",
        "date_max": dr[1],
    }
    dump("meta.json", meta)


if __name__ == "__main__":
    main()
