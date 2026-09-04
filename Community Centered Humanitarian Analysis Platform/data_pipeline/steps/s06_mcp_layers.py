"""Step 6 of 7 - external open-data layers (sourced via the IFRC/HDX/FEWS NET MCP servers).

These five layers are built from data pulled through MCP servers in Claude Desktop / Claude
Code (HDX HAPI, UNHCR, FEWS NET). MCP tools are only callable by the assistant at runtime, so
the raw pulls are cached under data_pipeline/mcp_cache/ and this step rebuilds the dashboard
JSON from those caches + curated geography. To refresh the data, re-run the MCP pulls (see
MAINTENANCE.md "Refreshing the MCP layers") and overwrite the caches, then run this step.

Outputs into dashboard/data/:
  crossings.json          border crossings tagged to movement corridors  (curated geography)
  idp_localities.json     IDP locality bubbles + monthly series           (IOM-DTM via HDX HAPI)
  refugee_camps.json      host-country refugee totals + camp markers      (UNHCR via HDX HAPI)
  ipc_areas_fs.geojson    area-level IPC phase snapshots over time        (IPC via IPC MCP)
  seasonal.json           seasonal calendar                               (FEWS NET get_seasons)
  aoi_ipc.geojson         IFRC Areas of Interest + their IPC phase         (HSP boundaries + IPC MCP)

Boundary context layers (vendored static assets, from the IFRC HSP dashboard, not rebuilt here):
  dashboard/data/boundaries/admin0.geojson        operational-country outlines
  dashboard/data/boundaries/admin1_lines.geojson  state/region context lines
  dashboard/data/boundaries/aoi.geojson           Areas-of-Interest polygons (base geometry)

Caches consumed (refreshed by the assistant via MCP):
  mcp_cache/idps_admin2_overview.json   HDX get_idps, admin2, 'Overview' cumulative rows
  mcp_cache/sdn_adm2.geojson            geoBoundaries ADM2 (locality centroids)
  mcp_cache/ipc_area_YYYY-MM.geojson    IPC get_areas_by_analysis, one per analysis period
  mcp_cache/aoi_ipc_phases.json         per-AOI IPC phase (from _build_aoi_ipc.py)
"""
import collections
import json
import re

from data_pipeline.common import MCP_CACHE, DASHBOARD_DATA

# Shorthand for the folder holding the raw MCP pulls.
CACHE = MCP_CACHE


def norm(s):
    """Simplify a place name so spellings can be compared.

    "Ash Shamaliyah" and "Shamaliyah" both become "shamaliyah", which lets us
    match names between two datasets that transliterate Arabic differently.
    """
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for a in ("al ", "el ", "ash ", "aj ", "as ", "ad "):
        s = s.replace(a, "")
    return s.strip()


def dump(name, obj):
    """Write one file into dashboard/data/ and print its size."""
    p = DASHBOARD_DATA / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {name:24} {p.stat().st_size / 1024:8.1f} KB")


# ============================================================ border crossings
# Curated authoritative crossings, each tagged to corridor IDs present in flows.json so the
# frontend can highlight a crossing whenever population actually moved along that corridor.
CROSSINGS = [
    {"name": "El Geneina – Adré", "country": "Chad", "lon": 22.20, "lat": 13.47,
     "corridor": "sudan-chad", "return_corridor": "chad-sudan-return"},
    {"name": "Tiné", "country": "Chad", "lon": 22.30, "lat": 14.94,
     "corridor": "sudan-chad", "return_corridor": "chad-sudan-return"},
    {"name": "Um Dukhun – Am Dafok", "country": "Central African Republic", "lon": 23.45, "lat": 11.00,
     "corridor": "sudan-car", "return_corridor": None},
    {"name": "Wadi Halfa – Argeen / Ashkeet", "country": "Egypt", "lon": 31.55, "lat": 21.95,
     "corridor": "sudan-egypt", "return_corridor": "egypt-sudan-return"},
    {"name": "Qustul – Ashkeet", "country": "Egypt", "lon": 31.50, "lat": 22.00,
     "corridor": "sudan-egypt", "return_corridor": "egypt-sudan-return"},
    {"name": "Sudan–Libya desert route (Dongola–Kufra)", "country": "Libya", "lon": 24.40, "lat": 20.30,
     "corridor": "sudan-libya", "return_corridor": "libya-sudan-return"},
    {"name": "Joda – Renk", "country": "South Sudan", "lon": 32.41, "lat": 11.90,
     "corridor": "sudan-south_sudan", "return_corridor": "south_sudan-sudan-return"},
    {"name": "Gallabat – Metema", "country": "Ethiopia", "lon": 36.16, "lat": 12.97,
     "corridor": "sudan-ethiopia", "return_corridor": None},
    {"name": "Hamdayet", "country": "Ethiopia", "lon": 36.35, "lat": 14.30,
     "corridor": "sudan-ethiopia", "return_corridor": None},
]


def build_crossings():
    """Write the border-crossing points (curated, not fetched)."""
    dump("crossings.json", {
        "source": "Curated authoritative Sudan border crossings (UNHCR/OCHA operational geography), "
                  "tagged to the movement corridors in flows.json.",
        "points": CROSSINGS,
    })


# ============================================================ IDP localities (IOM-DTM)
def _ring_centroid(coords):
    """Find the centre of a polygon ring, so we can draw one dot per locality.

    This is the standard area-weighted centroid formula. If the ring has no
    area (a straight line, or a bad shape) we fall back to the average point.
    """
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
    """Centre of a map shape; for multi-part shapes use the biggest part."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    best, best_a = None, -1
    for poly in polys:
        c, area = _ring_centroid(poly[0])
        if area > best_a:
            best, best_a = c, area
    return best


def build_idp_localities():
    """IDP bubbles: DTM counts per locality, matched to locality centroids."""
    gj = json.loads((CACHE / "sdn_adm2.geojson").read_text(encoding="utf-8"))
    cents = {norm(f["properties"].get("shapeName")): _feature_centroid(f["geometry"])
             for f in gj["features"]}
    ov = json.loads((CACHE / "idps_admin2_overview.json").read_text(encoding="utf-8"))
    loc = collections.defaultdict(lambda: {"name": "", "state": "", "months": {}})
    for r in ov:
        d = loc[r["admin2_code"]]
        d["name"] = r["admin2_name"]; d["state"] = r["admin1_name"]
        mk, date = r["reference_period_end"][:7], r["reference_period_end"][:10]
        if mk not in d["months"] or date > d["months"][mk][0]:
            d["months"][mk] = (date, int(r["population"]))
    out, unmatched = [], 0
    for d in loc.values():
        c = cents.get(norm(d["name"]))
        if not c:
            unmatched += 1; continue
        series = [{"date": dt, "value": v} for _, (dt, v) in sorted(d["months"].items()) if v > 0]
        if len(series) < 2:
            continue
        out.append({"name": d["name"], "state": d["state"],
                    "lon": round(c[0], 4), "lat": round(c[1], 4),
                    "peak": max(p["value"] for p in series), "series": series})
    out.sort(key=lambda x: -x["peak"])
    dump("idp_localities.json", {
        "source": "IOM DTM via HDX HAPI (get_idps, 'Overview' cumulative series), admin2; "
                  "centroids from geoBoundaries SDN ADM2",
        "metric": "IDP individuals (cumulative, IOM DTM)",
        "localities": out,
    })
    print(f"    {len(out)} localities ({unmatched} unmatched centroids)")


# ============================================================ refugees (UNHCR via HDX)
# REAL — UNHCR registered Sudanese refugees by country of asylum (get_refugees, REF, all/all).
REF_COUNTRIES = {
    "Chad":        {"2022": 403846, "2023": 923323, "2024": 1109357, "anchor": [21.9, 13.9]},
    "South Sudan": {"2022": 290740, "2023": 359581, "2024": 487652,  "anchor": [32.9, 10.5]},
    "Egypt":       {"2022": 25476,  "2023": 26213,  "2024": 27696,   "anchor": [31.0, 24.0],
                    "note": "UNHCR-registered only; actual Sudanese presence far larger (gov. est. >1M)"},
    "Ethiopia":    {"2022": 48020,  "2023": 77424,  "2024": 90442,   "anchor": [36.5, 12.6]},
    "Central African Republic": {"2022": 478, "2023": 21816, "2024": 29932, "anchor": [22.8, 9.5]},
    "Libya":       {"2022": 1133,   "2023": 975,    "2024": 199388,  "anchor": [23.3, 24.2]},
    "Uganda":      {"2022": 2871,   "2023": 14971,  "2024": 65367,   "anchor": [32.4, 2.5]},
}
# Curated camps / transit centres (coords approximate, from UNHCR RRP operational reporting).
REF_CAMPS = [
    {"name": "Adré transit centre", "country": "Chad", "lon": 22.20, "lat": 13.47, "opened": "2023-04", "type": "Transit centre", "size": 3},
    {"name": "Aboutengue camp", "country": "Chad", "lon": 22.05, "lat": 13.55, "opened": "2023-06", "type": "Refugee camp", "size": 2},
    {"name": "Metché camp", "country": "Chad", "lon": 21.85, "lat": 13.62, "opened": "2023-09", "type": "Refugee camp", "size": 2},
    {"name": "Gaga camp", "country": "Chad", "lon": 21.45, "lat": 13.49, "opened": "2023-05", "type": "Refugee camp", "size": 2},
    {"name": "Farchana camp", "country": "Chad", "lon": 21.66, "lat": 13.42, "opened": "2023-05", "type": "Refugee camp", "size": 1},
    {"name": "Tiné reception site", "country": "Chad", "lon": 22.30, "lat": 14.94, "opened": "2023-05", "type": "Reception site", "size": 1},
    {"name": "Iriba camps (Touloum/Iridimi)", "country": "Chad", "lon": 22.27, "lat": 15.13, "opened": "2023-06", "type": "Refugee camp", "size": 1},
    {"name": "Renk transit centre", "country": "South Sudan", "lon": 32.78, "lat": 11.75, "opened": "2023-05", "type": "Transit centre", "size": 3},
    {"name": "Maban camps (Doro/Kaya/Batil)", "country": "South Sudan", "lon": 33.73, "lat": 9.94, "opened": "2023-06", "type": "Refugee camp", "size": 2},
    {"name": "Wedweil settlement", "country": "South Sudan", "lon": 28.20, "lat": 9.10, "opened": "2023-08", "type": "Refugee settlement", "size": 1},
    {"name": "Kumer camp", "country": "Ethiopia", "lon": 36.30, "lat": 12.85, "opened": "2023-06", "type": "Refugee camp", "size": 1},
    {"name": "Awlala / Aftit sites", "country": "Ethiopia", "lon": 36.40, "lat": 12.70, "opened": "2023-09", "type": "Reception site", "size": 1},
    {"name": "Wadi Halfa / Argeen arrival", "country": "Egypt", "lon": 31.30, "lat": 22.00, "opened": "2023-04", "type": "Border arrival (urban onward)", "size": 1},
    {"name": "Kufra reception", "country": "Libya", "lon": 23.31, "lat": 24.18, "opened": "2023-05", "type": "Reception / transit", "size": 1},
    {"name": "Korsi site (Birao)", "country": "Central African Republic", "lon": 22.78, "lat": 10.28, "opened": "2023-06", "type": "Reception site", "size": 1},
]


def build_refugees():
    """Refugee totals per host country, plus the curated camp markers."""
    countries = []
    for name, d in REF_COUNTRIES.items():
        countries.append({
            "country": name, "anchor": d["anchor"],
            "series": [{"date": f"{y}-07-01", "value": d[y]} for y in ("2022", "2023", "2024") if y in d],
            "note": d.get("note", ""),
        })
    dump("refugee_camps.json", {
        "source": "Country totals: UNHCR via HDX HAPI (get_refugees, REF). "
                  "Camp markers: curated from UNHCR RRP operational reporting (coordinates approximate).",
        "countries": countries, "camps": REF_CAMPS,
    })


# ============================================================ food security (IPC via IPC MCP)
# One full IPC snapshot per analysis period (IPC redraws analysis units each round), built from
# the cached per-period geojson pulls. Geometry simplified for the web. Frontend shows the period
# in effect at the current timeline date and colours by IPC's own phase colour.
def _simplify(geom, nd=3):
    """Round coordinates to 3 decimals (~100 m) so the map file stays small."""
    def ring(r):
        out = []
        for pt in r:
            p = [round(pt[0], nd), round(pt[1], nd)]
            if not out or out[-1] != p:
                out.append(p)
        if len(out) < 4:
            return [[round(pt[0], nd), round(pt[1], nd)] for pt in r]
        if out[0] != out[-1]:
            out.append(out[0])
        return out
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(r) for r in geom["coordinates"]]}
    if geom["type"] == "MultiPolygon":
        return {"type": "MultiPolygon",
                "coordinates": [[ring(r) for r in poly] for poly in geom["coordinates"]]}
    return geom


def build_foodsec():
    """One IPC food-insecurity snapshot per analysis period."""
    import glob
    files = sorted(glob.glob(str(CACHE / "ipc_area_*.geojson")))
    periods, dates = {}, []
    for f in files:
        date = re.search(r"ipc_area_(\d{4}-\d{2})", f)[1] + "-01"
        dates.append(date)
        g = json.loads(open(f, encoding="utf-8").read())
        feats = []
        for ft in g["features"]:
            p = ft["properties"]
            phase = p.get("overall_phase")
            if phase is None:
                continue
            p3 = round((p.get("phase3_percent") or 0) + (p.get("phase4_percent") or 0)
                       + (p.get("phase5_percent") or 0), 3)
            fam = bool((p.get("phase5_population") or 0) > 0 or phase >= 5)
            feats.append({"type": "Feature", "geometry": _simplify(ft["geometry"]),
                          "properties": {"area": (p.get("title") or "").strip(), "ph": phase,
                                         "p3": p3, "fam": fam, "color": p.get("color", "#cccccc")}})
        periods[date] = {"type": "FeatureCollection", "features": feats}
    dump("ipc_areas_fs.geojson", {
        "_meta": {"source": "IPC (ipcinfo.org) via IPC MCP get_areas_by_analysis; one snapshot per "
                            "analysis period, area level (overall IPC phase; p3 = phase 3+ share; "
                            "fam = Phase 5 famine present).",
                  "dates": sorted(dates)},
        "periods": periods,
    })
    print(f"    {len(periods)} IPC periods, {sum(len(v['features']) for v in periods.values())} area-features")


# ============================================================ seasonal (FEWS NET get_seasons)
SEASONAL = {
    "source": "FEWS NET seasonal calendar for Sudan (get_seasons API).",
    "items": [
        {"label": "Lean / hunger season", "months": [5, 6, 7, 8, 9, 10], "color": "#e67e22",
         "note": "FEWS NET nutrition lean season (May–Oct)"},
        {"label": "Rainy / growing season", "months": [6, 7, 8, 9, 10], "color": "#3498db",
         "note": "Main agricultural season (cultivation)"},
        {"label": "Main (rainfed) harvest", "months": [11, 12, 1], "color": "#27ae60",
         "note": "Traditional & mechanized rainfed harvest (Nov–Jan)"},
        {"label": "Irrigated harvest", "months": [3], "color": "#9ccc65",
         "note": "Irrigated harvest (March)"},
        {"label": "Post-harvest / dry season", "months": [1, 2, 3, 4], "color": "#c9a14a",
         "note": "Dry post-harvest period (Jan–Apr)"},
    ],
}


def build_seasonal():
    """Write the lean / rainy / harvest calendar bands."""
    dump("seasonal.json", SEASONAL)


# ============================================================ IFRC Areas of Interest + IPC
# Country outlines (admin0) and state lines (admin1) are vendored static assets under
# dashboard/data/boundaries/ (from the IFRC HSP dashboard). Here we merge the cached per-AOI
# IPC phases (built by _build_aoi_ipc.py from IPC MCP pulls) onto the AOI polygons.
def build_aoi():
    """Colour each IFRC Area of Interest by the worst IPC phase inside it."""
    base_path = DASHBOARD_DATA / "boundaries" / "aoi.geojson"
    if not base_path.exists():
        print("    (no aoi.geojson — skipping AOI layer)")
        return
    nm = lambda s: re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    phases_path = CACHE / "aoi_ipc_phases.json"
    phases = json.loads(phases_path.read_text(encoding="utf-8")) if phases_path.exists() else {}
    none_info = {"ipc_phase": None, "ipc_color": "#bdbdbd", "ipc_p3": None,
                 "ipc_n_areas": 0, "ipc_n_phase3plus": 0}
    with_ipc = 0
    for ft in base["features"]:
        info = phases.get(nm(ft["properties"].get("name", "")))
        ft["properties"].update(info or none_info)
        with_ipc += 1 if (info and info.get("ipc_phase")) else 0
    dump("aoi_ipc.geojson", base)
    print(f"    {len(base['features'])} AOIs, {with_ipc} with an IPC phase")


def run():
    """Rebuild every external layer from whatever is currently cached."""
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)
    print("== external MCP layers")
    build_crossings()
    build_idp_localities()
    build_refugees()
    build_foodsec()
    build_seasonal()
    build_aoi()
