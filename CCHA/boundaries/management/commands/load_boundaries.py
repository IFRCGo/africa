"""Fill the boundary library from the office's own map files.

    python manage.py load_boundaries               # everything
    python manage.py load_boundaries --only SDN    # one country
    python manage.py load_boundaries --skip-features   # admin areas only
    python manage.py load_boundaries --dry-run     # read and report, write nothing

Run it once. The polygons then live in the database and neither the dashboard
nor the pipeline ever opens these folders again.

WHAT IT DOES, IN ORDER
  1. Every admin file in the registry, one transaction each: read, repair,
     insert, then derive the simplified copy, the bounding box and the centre
     point in SQL.
  2. The IFRC Areas of Interest, from the one GeoJSON that holds them.
  3. Give every AOI a country, by asking which country outline contains it.
     THIS IS THE FIX for reporting about one country highlighting another.
  4. Give Sudan's GADM localities a parent district, by containment, because
     their names cannot be joined to OCHA's.
  5. The physical and operational layers - rivers, lakes, capitals, roads.

SAFE TO RUN AGAIN. Each file's rows are deleted and rewritten inside one
transaction, so a re-run replaces exactly what that file put there and a
failure part-way leaves the previous load untouched.
"""
import hashlib
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from boundaries import geo
from boundaries.models import AdminArea, BoundarySource, MapFeature
from boundaries.sources import (ADAPTERS, ADMIN_SOURCES, EXPECTED_COUNTS,
                                FEATURE_SOURCES_OPS, FEATURE_SOURCES_PHYSICAL,
                                read_encoding)

INSERT_AREA_SQL = """
INSERT INTO admin_areas
    (source_id, kind, iso3, country_name, level, pcode, name, ref_name, name_alt,
     parent_pcode, name_path, parent_method, valid_on, version, area_sqkm,
     center_lat, center_lon, geom)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s,
        ST_Multi(ST_Transform(ST_GeomFromWKB(%s, %s), 4326)))
"""

INSERT_FEATURE_SQL = """
INSERT INTO map_features (source_id, layer, name, kind, iso3, props, geom, geom_web)
VALUES (%s, %s, %s, %s, %s, %s::jsonb,
        ST_Transform(ST_GeomFromWKB(%s, %s), 4326),
        ST_SimplifyPreserveTopology(ST_Transform(ST_GeomFromWKB(%s, %s), 4326), 0.002))
"""


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Command(BaseCommand):
    help = "Load admin boundaries and map layers from the office's shapefiles."

    def add_arguments(self, parser):
        parser.add_argument("--only", help="One ISO3 code, e.g. SDN")
        parser.add_argument("--skip-features", action="store_true",
                            help="Admin boundaries only")
        parser.add_argument("--dry-run", action="store_true",
                            help="Read and report; write nothing")

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        self.dry = opts["dry_run"]
        admin_dir = str(settings.BOUNDARY_ADMIN_DIR)
        layers_dir = str(settings.BOUNDARY_LAYERS_DIR)

        self.stdout.write(self.style.MIGRATE_HEADING("=== administrative boundaries ==="))
        total = 0
        for rel, iso3, country, level, schema, publisher in ADMIN_SOURCES:
            if opts["only"] and iso3 != opts["only"].upper():
                continue
            total += self.load_admin(admin_dir, rel, iso3, country, level, schema, publisher)

        if not opts["only"]:
            self.stdout.write(self.style.MIGRATE_HEADING("=== IFRC areas of interest ==="))
            total += self.load_aoi()
            self.locate_aois()

        self.link_gadm_parents(opts.get("only"))

        if not opts["skip_features"] and not opts["only"]:
            self.stdout.write(self.style.MIGRATE_HEADING("=== physical and operational layers ==="))
            for rel, layer, kind, iso3, publisher in FEATURE_SOURCES_PHYSICAL:
                self.load_features(layers_dir, rel, layer, kind, iso3, publisher)
            for rel, layer, kind, iso3, publisher in FEATURE_SOURCES_OPS:
                self.load_features(admin_dir, rel, layer, kind, iso3, publisher)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{total} boundary polygons {'read (dry run)' if self.dry else 'in the library'}"))
        if not self.dry:
            self.stdout.write("Check it with:  python manage.py check_boundaries")

    # ------------------------------------------------------- admin boundaries
    def load_admin(self, base_dir, rel, iso3, country, level, schema, publisher):
        path = os.path.join(base_dir, rel.replace("/", os.sep))
        shp = path + ".shp"
        if not os.path.exists(shp):
            raise FileNotFoundError(f"{shp} is in the registry but not on disk")

        adapt = ADAPTERS[schema]
        # Keyed by p-code, because a p-code names a PLACE and some files store
        # one place as several polygon records - Uganda's Ibanda arrives as
        # three, Bayanga in CAR as two, all with the same code and name. They
        # are parts of one district, so they are collected here and merged into
        # a single multipolygon below rather than fighting the unique
        # constraint or, worse, being thrown away.
        by_pcode, order, skipped = {}, [], 0
        for rec, wkb, srid in geo.read_shapes(path):
            a = adapt(rec, level)
            if not a["name"] or not a["pcode"]:
                skipped += 1
                continue
            if a["pcode"] not in by_pcode:
                by_pcode[a["pcode"]] = (a, [])
                order.append(a["pcode"])
            by_pcode[a["pcode"]][1].append(wkb)

        rows, merged = [], 0
        for pcode in order:
            a, parts = by_pcode[pcode]
            if len(parts) > 1:
                wkb = geo.union_wkb(parts)
                merged += len(parts) - 1
            else:
                wkb = parts[0]
            ancestors = [x for x in a["ancestors"] if x]
            rows.append((
                None, AdminArea.KIND_ADMIN, iso3, country, level, pcode, a["name"],
                a["ref_name"], json.dumps(a["name_alt"], ensure_ascii=False),
                a["parent_pcode"],
                " > ".join(ancestors + [a["name"]]),
                "attribute" if a["parent_pcode"] else None,
                a["valid_on"], a["version"], a["area_sqkm"],
                a["center_lat"], a["center_lon"], wkb, srid,
            ))

        label = f"{country} ADM{level}"
        expected = EXPECTED_COUNTS.get((iso3, level))
        flag = ""
        if expected is not None and len(rows) != expected:
            flag = self.style.WARNING(f"  != {expected} expected")
        notes = []
        if merged:
            notes.append(f"{merged} extra part(s) merged into their own place")
        if skipped:
            notes.append(f"{skipped} without a name or p-code skipped")
        self.stdout.write(f"  {label:28s} {len(rows):6d} polygons"
                          f"{'  (' + '; '.join(notes) + ')' if notes else ''}{flag}")
        if self.dry:
            return len(rows)

        with transaction.atomic():
            src, _ = BoundarySource.objects.update_or_create(
                path=shp,
                defaults=dict(
                    publisher=publisher, source_label=f"{country} ADM{level}",
                    schema=schema, encoding=read_encoding(path),
                    feature_count=len(rows), sha1=sha1_of(shp),
                    valid_on=rows[0][12] if rows else None,
                    version=rows[0][13] if rows else None,
                ),
            )
            # Replace exactly this file's rows, so a re-run is a refresh and not
            # a duplication.
            AdminArea.objects.filter(source=src).delete()
            with connection.cursor() as cur:
                cur.executemany(INSERT_AREA_SQL, [(src.id,) + r[1:] for r in rows])
                cur.execute(geo.DERIVE_SQL,
                            {"tol": geo.tolerance_for(level), "source_id": src.id})
                cur.execute(geo.DERIVE_FALLBACK_SQL, {"source_id": src.id})
        return len(rows)

    # ------------------------------------------------------ areas of interest
    def load_aoi(self):
        """The 14 IFRC Areas of Interest.

        These are not an administrative level in any country - Kiryandongo is a
        settlement, Abyei is disputed - but they are exactly what the IFRC
        reporting is about, so the map has to be able to draw them. There is no
        shapefile for them; the only copy the project has is the GeoJSON that
        came with the HSP dashboard, so that file becomes a registered source
        like any other.
        """
        from shapely.geometry import shape as shapely_shape

        path = settings.DASHBOARD_DATA_DIR / "boundaries" / "aoi.geojson"
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"  {path} not found - skipped"))
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for f in data["features"]:
            name = (f["properties"].get("name") or "").strip()
            if not name or not f.get("geometry"):
                continue
            g = geo._as_multipolygon(shapely_shape(f["geometry"]))
            if g is None:
                continue
            rows.append((
                None, AdminArea.KIND_AOI, "???", "unknown", None, f"AOI:{name}", name,
                None, json.dumps([]), None, name, None, None, None, None, None, None,
                g.wkb, 4326,
            ))
        self.stdout.write(f"  {'IFRC areas of interest':28s} {len(rows):6d} polygons")
        if self.dry:
            return len(rows)
        with transaction.atomic():
            src, _ = BoundarySource.objects.update_or_create(
                path=str(path),
                defaults=dict(publisher="IFRC", source_label="IFRC areas of interest",
                              schema="geojson", encoding="utf-8",
                              feature_count=len(rows), sha1=sha1_of(path)),
            )
            AdminArea.objects.filter(source=src).delete()
            with connection.cursor() as cur:
                cur.executemany(INSERT_AREA_SQL, [(src.id,) + r[1:] for r in rows])
                cur.execute(geo.DERIVE_SQL, {"tol": 0.002, "source_id": src.id})
                cur.execute(geo.DERIVE_FALLBACK_SQL, {"source_id": src.id})
        return len(rows)

    def locate_aois(self):
        """Give every area of interest the country that contains it.

        Small query, large consequence. While these polygons had no country, the
        place-name matcher could not apply its "a sentence about Sudan may only
        highlight somewhere in Sudan" rule to them - which is how 20 rows of
        Sudanese reporting ended up drawn on Amhara, in Ethiopia.
        """
        if self.dry:
            return
        with connection.cursor() as cur:
            cur.execute(geo.LOCATE_AOI_SQL)
            cur.execute("SELECT count(*) FROM admin_areas WHERE kind='aoi' AND iso3='???'")
            stranded = cur.fetchone()[0]
        located = AdminArea.objects.filter(kind="aoi").exclude(iso3="???").count()
        self.stdout.write(f"  {'located in a country':28s} {located:6d}")
        if stranded:
            self.stdout.write(self.style.WARNING(
                f"  {stranded} area(s) of interest sit outside every country outline - "
                f"they will not be matched to any reporting"))

    def link_gadm_parents(self, only):
        """Sudan's GADM localities: find the OCHA district that contains each."""
        if self.dry:
            return
        for rel, iso3, _c, level, schema, _p in ADMIN_SOURCES:
            if schema != "gadm" or (only and iso3 != only.upper()):
                continue
            src = BoundarySource.objects.filter(path__endswith=os.path.basename(rel) + ".shp").first()
            if not src:
                continue
            with connection.cursor() as cur:
                cur.execute(geo.LINK_PARENT_SPATIAL_SQL,
                            {"source_id": src.id, "parent_level": level - 1})
                linked = cur.rowcount
            total = AdminArea.objects.filter(source=src).count()
            self.stdout.write(
                f"  {'Sudan ADM3 -> ADM2 (spatial)':28s} {linked:6d} of {total} linked")

    # -------------------------------------------------------- other map layers
    def load_features(self, base_dir, rel, layer, kind, iso3, publisher):
        path = os.path.join(base_dir, rel.replace("/", os.sep))
        shp = path + ".shp"
        if not os.path.exists(shp):
            self.stdout.write(self.style.WARNING(f"  {layer:28s} missing: {shp}"))
            return
        rows = []
        for rec, wkb, srid in geo.read_shapes(path, want_polygons=False):
            name = None
            for key in ("name", "NAME", "Name", "name_en", "NAME_EN", "adm0_name", "CITY_NAME"):
                if rec.get(key):
                    name = str(rec[key]).strip()
                    break
            rows.append((None, layer, name, kind, iso3,
                         json.dumps({k: str(v) for k, v in rec.items() if v not in (None, "")},
                                    ensure_ascii=False),
                         wkb, srid, wkb, srid))
        self.stdout.write(f"  {layer:28s} {len(rows):6d} features")
        if self.dry:
            return
        with transaction.atomic():
            src, _ = BoundarySource.objects.update_or_create(
                path=shp,
                defaults=dict(publisher=publisher, source_label=layer, schema="feature",
                              encoding=read_encoding(path), feature_count=len(rows),
                              sha1=sha1_of(shp)),
            )
            MapFeature.objects.filter(source=src).delete()
            with connection.cursor() as cur:
                cur.executemany(INSERT_FEATURE_SQL, [(src.id,) + r[1:] for r in rows])
