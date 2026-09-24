"""Fetch the geometry the theme layers are drawn on: states, and water.

    python manage.py build_map_context            # use the cache where possible
    python manage.py build_map_context --refresh  # re-download everything

It writes two files:

    dashboard/data/boundaries/admin1.geojson   named states/provinces, 8 countries
    dashboard/data/water.geojson               named rivers and lakes, clipped

WHY THIS IS SEPARATE FROM s06
s06 rebuilds the layers that change: displacement figures, IPC phases, prices.
These two do not. State boundaries move once a decade and the Nile has not
moved at all, so re-downloading them on every pipeline run would be a slow way
to fetch the same bytes. This runs on its own, when the geometry needs
refreshing, and caches what it pulls in api_cache/.

SOURCES
  geoBoundaries (gbOpen, CC-BY 4.0) - the same source the project already uses
    for the Sudan ADM1/ADM2 centroids. The *simplified* geometry is taken
    deliberately: full resolution is tens of megabytes and this is a wall map,
    not a cadastral survey.
  Natural Earth 10m physical (public domain) - rivers with lake centrelines,
    and lakes. Only named features are kept, because a river the map cannot
    name is a river the reader cannot be told about.
"""
import json
import urllib.request

from django.core.management.base import BaseCommand

from data_pipeline.common import DASHBOARD_DATA, MCP_CACHE

# The eight countries the dashboard covers, as geoBoundaries ISO3 codes.
COUNTRIES = {
    "SDN": "Sudan", "TCD": "Chad", "EGY": "Egypt", "ETH": "Ethiopia",
    "SSD": "South Sudan", "LBY": "Libya", "UGA": "Uganda", "CAF": "Central African Republic",
}

GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM1/"
NE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
      "ne_10m_{name}.geojson")

# Everything is clipped to this box - the region the map can pan over, plus a
# margin so a river does not stop dead at the frame edge.
REGION = (7.0, -5.0, 58.0, 36.0)          # west, south, east, north


def _get(url, tries=4):
    """Download and parse JSON, retrying: the Natural Earth host rate-limits."""
    import time
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ccha-pipeline"})
            return json.loads(urllib.request.urlopen(req, timeout=180).read())
        except Exception as exc:                      # noqa: BLE001 - report and retry
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def _bbox(geom):
    w, s, e, n = 180.0, 90.0, -180.0, -90.0

    def walk(c):
        nonlocal w, s, e, n
        if c and isinstance(c[0], (int, float)):
            w, e = min(w, c[0]), max(e, c[0])
            s, n = min(s, c[1]), max(n, c[1])
        else:
            for part in c:
                walk(part)

    walk(geom["coordinates"])
    return w, s, e, n


def _in_region(geom):
    """Does this shape touch the region box at all?"""
    w, s, e, n = _bbox(geom)
    rw, rs, re_, rn = REGION
    return not (e < rw or w > re_ or n < rs or s > rn)


class Command(BaseCommand):
    help = "Fetch state boundaries and water bodies for the theme layers."

    def add_arguments(self, parser):
        parser.add_argument("--refresh", action="store_true",
                            help="Re-download even when a cached copy exists.")

    # ---------------------------------------------------------------- states
    def build_admin1(self, refresh):
        feats = []
        for iso3, country in COUNTRIES.items():
            cache = MCP_CACHE / f"{iso3.lower()}_adm1_simpl.geojson"
            if cache.exists() and not refresh:
                data = json.loads(cache.read_text(encoding="utf-8"))
            else:
                self.stdout.write(f"  downloading {country} ADM1 ...")
                meta = _get(GB_API.format(iso3=iso3))
                data = _get(meta["simplifiedGeometryGeoJSON"])
                cache.write_text(json.dumps(data), encoding="utf-8")
            for f in data.get("features", []):
                name = (f["properties"].get("shapeName") or "").strip()
                if not name:
                    continue
                feats.append({
                    "type": "Feature",
                    "geometry": f["geometry"],
                    # Only what the map needs. The id is what a tag row points at.
                    "properties": {"name": name, "country": country, "iso3": iso3,
                                   "level": "adm1", "id": f"{iso3}:{name}"},
                })
            self.stdout.write(f"  {country:<26} {len(data.get('features', []))} states")
        return feats

    # ------------------------------------------- the finer units we also hold
    def build_extra_areas(self):
        """Sudan's localities and the IFRC Areas of Interest.

        Two things the states alone cannot do. Sudan is the country the corpus
        writes about in most detail, so a report naming El Bauga should
        highlight El Bauga rather than the whole of River Nile State; and
        places like Kiryandongo are not an ADM1 in any country's own division
        but are exactly what the IFRC reporting is about.
        """
        feats = []
        adm2 = MCP_CACHE / "sdn_adm2.geojson"
        if adm2.exists():
            data = json.loads(adm2.read_text(encoding="utf-8"))
            for f in data["features"]:
                nm = (f["properties"].get("shapeName") or "").strip()
                if nm:
                    feats.append({"type": "Feature", "geometry": f["geometry"],
                                  "properties": {"name": nm, "country": "Sudan",
                                                 "iso3": "SDN", "level": "adm2",
                                                 "id": f"SDN-ADM2:{nm}"}})
            self.stdout.write(f"  {'Sudan localities':<26} {len(data['features'])} areas")
        aoi = DASHBOARD_DATA / "boundaries" / "aoi.geojson"
        if aoi.exists():
            data = json.loads(aoi.read_text(encoding="utf-8"))
            for f in data["features"]:
                nm = (f["properties"].get("name") or f["properties"].get("shapeName") or "").strip()
                if nm:
                    feats.append({"type": "Feature", "geometry": f["geometry"],
                                  "properties": {"name": nm, "country": None,
                                                 "iso3": None, "level": "aoi",
                                                 "id": f"AOI:{nm}"}})
            self.stdout.write(f"  {'IFRC areas of interest':<26} {len(data['features'])} areas")
        return feats

    # ----------------------------------------------------------------- water
    def build_water(self, refresh):
        feats = []
        for ne_name, kind in (("rivers_lake_centerlines", "river"), ("lakes", "lake")):
            cache = MCP_CACHE / f"ne_{ne_name}.geojson"
            if cache.exists() and not refresh:
                data = json.loads(cache.read_text(encoding="utf-8"))
            else:
                self.stdout.write(f"  downloading Natural Earth {ne_name} ...")
                data = _get(NE.format(name=ne_name))
                cache.write_text(json.dumps(data), encoding="utf-8")
            kept = 0
            for f in data["features"]:
                name = f["properties"].get("name") or f["properties"].get("name_alt")
                if not name or not f.get("geometry"):
                    continue
                if not _in_region(f["geometry"]):
                    continue
                feats.append({
                    "type": "Feature", "geometry": f["geometry"],
                    "properties": {"name": name, "kind": kind},
                })
                kept += 1
            self.stdout.write(f"  {kind:<26} {kept} named features in region")
        return {"type": "FeatureCollection", "features": feats}

    # --------------------------------------------------- which water is near
    def link_water(self, adm1, water):
        """Write onto each state the names of the water bodies that touch it.

        Worked out here, once, rather than in the browser: the dashboard only
        needs to know that flooding in River Nile State should light up the
        Nile, and asking that question of 133 states and 158 rivers on every
        redraw would be wasted work.

        The test is a box overlap with a margin, not true distance. A river is
        a long thin thing and its bounding box is a poor description of it, so
        this is generous by design - it is deciding which river to name, not
        measuring a floodplain.
        """
        MARGIN = 0.35                      # degrees, roughly 35-40 km
        boxes = [(f["properties"]["name"], f["properties"]["kind"], _bbox(f["geometry"]))
                 for f in water["features"]]
        linked = 0
        for state in adm1["features"]:
            w, s, e, n = _bbox(state["geometry"])
            near = []
            for name, kind, (ww, ws, we, wn) in boxes:
                if (we >= w - MARGIN and ww <= e + MARGIN
                        and wn >= s - MARGIN and ws <= n + MARGIN and name not in near):
                    near.append(name)
            state["properties"]["water"] = near
            linked += bool(near)
        self.stdout.write(f"  {linked} of {len(adm1['features'])} areas have named water nearby")

    def handle(self, *args, **options):
        refresh = options["refresh"]
        MCP_CACHE.mkdir(parents=True, exist_ok=True)
        out_dir = DASHBOARD_DATA / "boundaries"
        out_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write("=== states (geoBoundaries ADM1) ===")
        feats = self.build_admin1(refresh)
        self.stdout.write("=== finer areas (Sudan localities, IFRC AOIs) ===")
        feats += self.build_extra_areas()
        # Finest first: where a report names both a locality and the state
        # around it, the more precise polygon should be the one found.
        order = {"adm2": 0, "aoi": 1, "adm1": 2}
        feats.sort(key=lambda f: order.get(f["properties"]["level"], 9))
        adm1 = {"type": "FeatureCollection", "features": feats}

        self.stdout.write("=== water (Natural Earth 10m) ===")
        water = self.build_water(refresh)
        p = DASHBOARD_DATA / "water.geojson"
        p.write_text(json.dumps(water), encoding="utf-8")
        self.stdout.write(f"  -> {p.name}  {len(water['features'])} features, "
                          f"{p.stat().st_size / 1e6:.1f} MB")

        self.stdout.write("=== linking areas to water ===")
        self.link_water(adm1, water)
        p = out_dir / "areas.geojson"
        p.write_text(json.dumps(adm1), encoding="utf-8")
        self.stdout.write(f"  -> {p.name}  {len(adm1['features'])} areas, "
                          f"{p.stat().st_size / 1e6:.1f} MB")
