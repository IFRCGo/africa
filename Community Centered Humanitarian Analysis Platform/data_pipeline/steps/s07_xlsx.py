"""Step 7 of 7 - ingest Excel snapshots — neighbouring countries Sudanese refugees & Sudan IDPs by state.

Reads (from SOURCE_ROOT, the SUDAN Ops folder next to this repository):
  neighbouring countries Pop movement data.xlsx
      One sheet per reporting date; column names vary across sheets.
      Key columns: Country, Data Date, Sudanese refugees/asylum seekers (or 'Sudanese refugees')
      → merges 2026 biweekly series into dashboard/data/refugee_camps.json
        (extending the HDX 2022-2024 annual series already written by s06_mcp_layers.py).

  Sudan IDPs.xlsx
      Sheet1 with Sudan admin1 states; column headers carry snapshot dates:
      'Population (DD Mon YYYY)'.
      → writes dashboard/data/idp_states.json (admin1 IDP bubbles).

Always runs after step 6, which writes the base refugee_camps.json this step extends.
"""
import datetime
import json
import re

import openpyxl

from data_pipeline.common import MCP_CACHE, DASHBOARD_DATA, SOURCE_ROOT

# The two workbooks an analyst keeps up to date by hand, beside the PDFs.
NEIGHBOURS_XLSX = SOURCE_ROOT / "neighbouring countries Pop movement data.xlsx"
IDPS_XLSX = SOURCE_ROOT / "Sudan IDPs.xlsx"
# State outlines, used to place one bubble per Sudanese state.
ADM1_GJ = MCP_CACHE / "sdn_adm1.geojson"

# Column names used across sheets for "Sudanese refugees" (both forms appear)
_SDN_COL_NAMES = {"Sudanese refugees/asylum seekers", "Sudanese refugees"}

# Excel country names → canonical names used in refugee_camps.json
_COUNTRY_MAP = {
    "car": "Central African Republic",
    "central african republic": "Central African Republic",
    "chad": "Chad",
    "egypt": "Egypt",
    "ethiopia": "Ethiopia",
    "libya": "Libya",
    "south sudan": "South Sudan",
    "uganda": "Uganda",
}

# Sudan IDPs.xlsx state names → geoBoundaries shapeName
_STATE_NAME_MAP = {
    "aj jazirah": "Gezira",
    "nile": "River Nile",
}


def _dump(name, obj):
    """Write one file into dashboard/data/ and print its size."""
    p = DASHBOARD_DATA / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {name:30} {p.stat().st_size / 1024:8.1f} KB")


def _norm_country(s):
    """Map a country name as typed in Excel to the name we store."""
    return _COUNTRY_MAP.get((s or "").strip().lower())


# ──────────────────────────────────────────────────── polygon centroid
def _ring_centroid(coords):
    a = cx = cy = 0.0
    for i in range(len(coords) - 1):
        x0, y0 = coords[i][0], coords[i][1]
        x1, y1 = coords[i + 1][0], coords[i + 1][1]
        cr = x0 * y1 - x1 * y0
        a += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
    if abs(a) < 1e-12:
        xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
        return [sum(xs) / len(xs), sum(ys) / len(ys)], 0.0
    a *= 0.5
    return [cx / (6 * a), cy / (6 * a)], abs(a)


def _feature_centroid(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    best, best_a = None, -1
    for poly in polys:
        c, area = _ring_centroid(poly[0])
        if area > best_a:
            best, best_a = c, area
    return best


# ──────────────────────────────────────────────────── neighbours xlsx → refugees
def build_refugees():
    """Extend refugee_camps.json (s06 HDX 2022-2024 annuals) with Excel 2026 biweekly series."""
    if not NEIGHBOURS_XLSX.exists():
        print(f"  [skip] {NEIGHBOURS_XLSX.name} not found")
        return

    wb = openpyxl.load_workbook(str(NEIGHBOURS_XLSX), read_only=True, data_only=True)
    # collect (country, date_str, value) from all sheets
    snapshots = {}  # country → {date_str: value}  (latest value wins for same date)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [str(h or "").strip() for h in rows[0]]
        # find required columns by name (schema drifts across sheets)
        try:
            country_col = headers.index("Country")
        except ValueError:
            continue
        date_col = next((i for i, h in enumerate(headers) if h == "Data Date"), None)
        sdn_col = next((i for i, h in enumerate(headers) if h in _SDN_COL_NAMES), None)
        if date_col is None or sdn_col is None:
            continue

        for row in rows[1:]:
            if not row or all(v is None for v in row):
                continue
            country_raw = row[country_col] if country_col < len(row) else None
            date_val = row[date_col] if date_col < len(row) else None
            sdn_val = row[sdn_col] if sdn_col < len(row) else None
            if not country_raw or date_val is None or sdn_val is None:
                continue
            country = _norm_country(str(country_raw))
            if not country:
                continue
            try:
                sdn_int = int(sdn_val)
                if sdn_int <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            if isinstance(date_val, datetime.datetime):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val)[:10]
            # latest value for the same date wins (sheets are in chronological order)
            snapshots.setdefault(country, {})[date_str] = sdn_int

    wb.close()

    if not snapshots:
        print("  [skip] no refugee snapshots extracted from Excel")
        return

    # read s06 output and merge
    rc_path = DASHBOARD_DATA / "refugee_camps.json"
    if not rc_path.exists():
        print("  [skip] refugee_camps.json not found (run s06 first)")
        return
    rc = json.loads(rc_path.read_text(encoding="utf-8"))

    n_merged = 0
    for country_obj in rc["countries"]:
        extra = snapshots.get(country_obj["country"], {})
        if not extra:
            continue
        # keep only s06 series points (HDX 2022-2024 annuals, dates before 2025)
        base_series = [p for p in country_obj["series"] if p["date"] < "2025-01-01"]
        # add all Excel snapshots
        excel_series = [{"date": d, "value": v} for d, v in extra.items()]
        combined = {p["date"]: p["value"] for p in base_series}
        for p in excel_series:
            combined[p["date"]] = p["value"]
        country_obj["series"] = sorted(
            [{"date": d, "value": v} for d, v in combined.items()],
            key=lambda x: x["date"],
        )
        n_merged += len(extra)

    src = rc.get("source", "")
    if "neighbouring countries" not in src:
        rc["source"] = src + " | 2026 biweekly series from UNHCR Sudan Situation website (neighbouring countries Pop movement data.xlsx)."
    _dump("refugee_camps.json", rc)
    print(f"    {n_merged} Excel snapshots merged across {len(snapshots)} countries")


# ──────────────────────────────────────────────────── Sudan IDPs xlsx → states
def _parse_date_col(header):
    """Extract ISO date from 'Population (DD Mon YYYY)'."""
    m = re.search(r"\((\d{1,2})\s+(\w+)\s+(\d{4})\)", header)
    if not m:
        return None
    day, mon, year = m.group(1), m.group(2), m.group(3)
    MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    mnum = MONTHS.get(mon[:3].lower())
    if not mnum:
        return None
    return f"{year}-{mnum:02d}-{int(day):02d}"


def build_idp_states():
    """Write idp_states.json with Sudan admin1 IDP snapshots."""
    if not IDPS_XLSX.exists():
        print(f"  [skip] {IDPS_XLSX.name} not found")
        return
    if not ADM1_GJ.exists():
        print("  [skip] sdn_adm1.geojson not found")
        return

    # state centroids from geoBoundaries ADM1
    gj = json.loads(ADM1_GJ.read_text(encoding="utf-8"))
    cents = {}
    for f in gj["features"]:
        name = f["properties"].get("shapeName", "")
        if name and name != "Abyei PCA":
            cents[name] = _feature_centroid(f["geometry"])

    wb = openpyxl.load_workbook(str(IDPS_XLSX), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        print("  [skip] Sudan IDPs.xlsx is empty")
        return

    headers = [str(h or "").strip() for h in rows[0]]
    # only use dated "Population (DD Mon YYYY)" columns — skip bare "Population"
    dated_cols = []
    for i, h in enumerate(headers):
        if h.startswith("Population ("):
            d = _parse_date_col(h)
            if d:
                dated_cols.append((i, d))

    if not dated_cols:
        print("  [skip] no dated columns found in Sudan IDPs.xlsx")
        return

    out, unmatched = [], []
    for row in rows[1:]:
        if not row or row[0] is None:
            continue
        state_raw = str(row[0]).strip()
        if not state_raw:
            continue
        mapped = _STATE_NAME_MAP.get(state_raw.lower(), state_raw)
        centroid = cents.get(mapped)
        if not centroid:
            unmatched.append(state_raw)
            continue
        series = []
        for col_i, date_str in dated_cols:
            val = row[col_i] if col_i < len(row) else None
            try:
                v = int(val) if val is not None else 0
                if v > 0:
                    series.append({"date": date_str, "value": v})
            except (TypeError, ValueError):
                pass
        if not series:
            continue
        series.sort(key=lambda x: x["date"])
        out.append({
            "name": state_raw,
            "lon": round(centroid[0], 4),
            "lat": round(centroid[1], 4),
            "peak": max(p["value"] for p in series),
            "series": series,
        })

    if unmatched:
        print(f"    unmatched states (no centroid): {unmatched}")

    out.sort(key=lambda x: -x["peak"])
    all_dates = sorted({p["date"] for s in out for p in s["series"]})
    _dump("idp_states.json", {
        "source": "IOM-DTM / UNHCR — Sudan IDPs by state (Sudan IDPs.xlsx), admin1 level; "
                  "centroids from geoBoundaries SDN ADM1",
        "metric": "IDP individuals (snapshot per reporting date)",
        "dates": all_dates,
        "states": out,
    })
    print(f"    {len(out)} states, {len(dated_cols)} time points: {all_dates}")


def run():
    """Rebuild both Excel-sourced layers."""
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)
    print("== Excel data layers")
    build_refugees()
    build_idp_states()
