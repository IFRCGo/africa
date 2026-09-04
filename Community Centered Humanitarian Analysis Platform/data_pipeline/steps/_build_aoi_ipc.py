"""Enrich IFRC Areas of Interest with their IPC phase.

For each AOI polygon, find IPC analysis areas whose centroid falls inside it (point-in-polygon),
take the latest analysis period, and record the worst (max) IPC phase among them. Sources: IPC
MCP get_areas geojson per AOI country (cached as tool-result pulls) + the Sudan IPC snapshot.

Outputs:
  dashboard/data/aoi_ipc.geojson      AOI polygons + ipc_* properties
  data_pipeline/mcp_cache/aoi_ipc_phases.json   small {name: {...}} cache for s06 reproducibility
"""
import glob
import json
import os
import re

from data_pipeline.common import MCP_CACHE, DASHBOARD_DATA

# Where Claude Code drops the raw get_areas MCP results when an analyst
# refreshes the IPC data. Point IPC_TOOL_RESULTS_DIR somewhere else if
# needed; when the folder does not exist only the cached geojson is used.
TOOLRES = os.environ.get("IPC_TOOL_RESULTS_DIR",
                        str(MCP_CACHE / "ipc_tool_results"))
AOI = str(DASHBOARD_DATA / "boundaries" / "aoi.geojson")
CACHE = str(MCP_CACHE)
OUT = str(DASHBOARD_DATA / "aoi_ipc.geojson")

PHASE_COLOR = {1: "#cdfacd", 2: "#fae61e", 3: "#e67800", 4: "#c80000", 5: "#640000"}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# AOI name (normalised substring) -> IPC country code
AOI_COUNTRY = [
    ("kiryandongo", "UG"), ("amhara", "ET"), ("shangul", "ET"), ("gumu", "ET"),
    ("vakaga", "CF"), ("unity", "SS"), ("upper nile", "SS"), ("northern bahr", "SS"),
    ("western bahr", "SS"), ("abyei", "SD"), ("wadi fira", "TD"), ("sila", "TD"),
    ("ouadda", "TD"), ("ennedi", "TD"), ("aswan", "EG"),
]


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def aoi_country(name):
    n = norm(name)
    for sub, c in AOI_COUNTRY:
        if sub in n:
            return c
    return None


def to_rank(s):
    """'Aug 2026' -> sortable int; missing -> 0."""
    if not s:
        return 0
    m = re.search(r"([A-Za-z]{3})\w*\s+(\d{4})", s)
    if not m:
        return 0
    return int(m[2]) * 12 + MONTHS.get(m[1].lower()[:3], 0)


def ring_centroid(coords):
    a = cx = cy = 0.0
    for i in range(len(coords) - 1):
        x0, y0 = coords[i][0], coords[i][1]
        x1, y1 = coords[i + 1][0], coords[i + 1][1]
        cr = x0 * y1 - x1 * y0
        a += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
    if abs(a) < 1e-12:
        xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def feature_centroid(geom):
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    best, ba = None, -1
    for poly in polys:
        ring = poly[0]
        # area magnitude
        a = abs(sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                    for i in range(len(ring) - 1)))
        if a > ba:
            ba, best = a, ring_centroid(ring)
    return best


def pt_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def pt_in_geom(x, y, geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polys:
        if pt_in_ring(x, y, poly[0]):
            if not any(pt_in_ring(x, y, hole) for hole in poly[1:]):
                return True
    return False


def load_ipc_areas():
    """country -> list of {cx,cy,phase,p3,rank,color}. From get_areas geojson + Sudan snapshot."""
    by_country = {}
    for f in glob.glob(os.path.join(TOOLRES, "mcp-ipc-get_areas-*.txt")):
        try:
            g = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not (isinstance(g, dict) and g.get("features")
                and g["features"][0].get("geometry")):
            continue
        c = g["features"][0]["properties"].get("country")
        rows = by_country.setdefault(c, [])
        for ft in g["features"]:
            p = ft["properties"]
            ph = p.get("overall_phase")
            if ph is None:
                continue
            c = feature_centroid(ft["geometry"])
            if not c:
                continue
            rows.append({"cx": c[0], "cy": c[1], "phase": ph,
                         "p3": p.get("phase3_worse_percentage") or 0,
                         "rank": to_rank(p.get("to")), "color": p.get("color")})
    # Sudan snapshot (get_areas_by_analysis schema) for Abyei etc.
    sd = sorted(glob.glob(os.path.join(CACHE, "ipc_area_*.geojson")))
    if sd:
        g = json.load(open(sd[-1], encoding="utf-8"))
        m = re.search(r"(\d{4})-(\d{2})", sd[-1])
        rank = int(m.group(1)) * 12 + int(m.group(2)) if m else 0
        rows = by_country.setdefault("SD", [])
        for ft in g["features"]:
            p = ft["properties"]
            ph = p.get("overall_phase")
            if ph is None:
                continue
            c = feature_centroid(ft["geometry"])
            if not c:
                continue
            cx, cy = c
            p3 = (p.get("phase3_percent") or 0) + (p.get("phase4_percent") or 0) + (p.get("phase5_percent") or 0)
            rows.append({"cx": cx, "cy": cy, "phase": ph, "p3": round(p3, 3),
                         "rank": rank, "color": p.get("color")})
    return by_country


def run():
    aoi = json.load(open(AOI, encoding="utf-8"))
    ipc = load_ipc_areas()
    print("IPC areas loaded per country:", {k: len(v) for k, v in ipc.items()})
    cache = {}
    for ft in aoi["features"]:
        name = ft["properties"].get("name", "")
        country = aoi_country(name)
        rows = ipc.get(country, [])
        inside = [r for r in rows if r["phase"] >= 1 and pt_in_geom(r["cx"], r["cy"], ft["geometry"])]
        if inside:
            latest = max(r["rank"] for r in inside)
            cur = [r for r in inside if r["rank"] == latest] or inside
            worst = max(cur, key=lambda r: r["phase"])
            n3 = sum(1 for r in cur if r["phase"] >= 3)
            info = {"ipc_phase": worst["phase"],
                    "ipc_color": worst["color"] or PHASE_COLOR.get(worst["phase"], "#cccccc"),
                    "ipc_p3": round(max(r["p3"] for r in cur), 3),
                    "ipc_n_areas": len(cur), "ipc_n_phase3plus": n3, "ipc_country": country}
        else:
            info = {"ipc_phase": None, "ipc_color": "#bdbdbd", "ipc_p3": None,
                    "ipc_n_areas": 0, "ipc_n_phase3plus": 0, "ipc_country": country}
        ft["properties"].update(info)
        cache[norm(name)] = info
    json.dump(aoi, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(cache, open(os.path.join(CACHE, "aoi_ipc_phases.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\naoi_ipc.geojson: {len(aoi['features'])} AOIs")
    for ft in aoi["features"]:
        p = ft["properties"]
        print(f"  {p['name']:28} phase {p['ipc_phase']}  ({p['ipc_n_phase3plus']}/{p['ipc_n_areas']} areas in P3+)  [{p['ipc_country']}]")


if __name__ == "__main__":
    run()
