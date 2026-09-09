"""Turning a shapefile into rows, and rows back into GeoJSON.

Everything that touches an actual shape lives here, so the rest of the app can
stay ordinary Django. Two directions:

    read_shapes()    shapefile -> (attribute record, WKB bytes) pairs to insert
    feature_rows()   a SELECT that hands back finished GeoJSON out of PostGIS

WHY THE DATABASE BUILDS THE GeoJSON
PostGIS can write GeoJSON itself, simplify on the way out and round the
coordinates while it does it - in C, over an indexed column. Doing the same in
Python means pulling every polygon across the wire only to reshape it. So the
queries below ask for finished text and the view passes it straight on.
"""
import shapefile
from shapely.geometry import shape as shapely_shape
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import make_valid

from .sources import (COORD_PRECISION, DEFAULT_TOLERANCE, SIMPLIFY_TOLERANCE,
                      detect_srid, read_encoding)


class SourceProblem(Exception):
    """A source file cannot be trusted. Always fatal - never a warning."""


def read_shapes(base_path, want_polygons=True):
    """Read one shapefile. Yields (record dict, WKB bytes, srid) for every feature.

    Refuses any coordinate system it does not recognise, and decodes the
    attribute table strictly with whatever character set the publisher declared.
    Both refusals are deliberate: a mystery projection or a mis-decoded name
    loads perfectly happily and is wrong in a way nobody notices for months.

    The srid comes back with each row rather than being assumed, because two of
    the office's layers are in Web Mercator; PostGIS reprojects them on insert.
    """
    srid = detect_srid(base_path)
    encoding = read_encoding(base_path)
    try:
        reader = shapefile.Reader(base_path, encoding=encoding, encodingErrors="strict")
    except UnicodeDecodeError as exc:
        raise SourceProblem(
            f"{base_path}: attribute table is not {encoding} as declared ({exc}). "
            f"Fix the .cpg rather than decoding loosely - a wrong guess corrupts "
            f"place names silently."
        ) from exc

    fields = [f[0] for f in reader.fields[1:]]
    for sr in reader.iterShapeRecords():
        geom = sr.shape.__geo_interface__
        if not geom or not geom.get("coordinates"):
            continue                                    # a record with no shape
        g = shapely_shape(geom)
        if want_polygons:
            g = _as_multipolygon(g)
            if g is None:
                continue
        yield dict(zip(fields, sr.record)), g.wkb, srid


def _as_multipolygon(g):
    """Repair a polygon and give it a consistent type.

    Two things happen to shapes on their way through GIS software: rings cross
    themselves, and a single-part shape gets stored as Polygon while its
    neighbours are MultiPolygon. PostGIS rejects both - an invalid geometry on
    insert, and the wrong type against a typed column. make_valid() fixes the
    first (it is the modern replacement for the buffer(0) trick, and unlike
    buffer(0) it does not quietly delete slivers), and everything is promoted to
    MultiPolygon so one column type fits every row.
    """
    if not g.is_valid:
        g = make_valid(g)
    # make_valid on a broken polygon can return a collection with stray lines
    # and points in it. Keep the polygons; a boundary is an area.
    if g.geom_type == "GeometryCollection":
        parts = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
        if not parts:
            return None
        g = MultiPolygon([q for p in parts
                          for q in (p.geoms if p.geom_type == "MultiPolygon" else [p])])
    if isinstance(g, Polygon):
        g = MultiPolygon([g])
    if g.geom_type != "MultiPolygon" or g.is_empty:
        return None
    return g


def union_wkb(parts):
    """Merge several polygon records that are one place into a single shape.

    Some publishers store a district that comes in several pieces - an island,
    a detached ward - as several rows sharing one p-code and one name. They are
    not different places and must not become different rows: the p-code is the
    identity the whole library is joined on.

    unary_union also dissolves the shared edge where two parts touch, so a
    district split down the middle comes back as the single polygon it always
    was, rather than two halves with a seam.
    """
    from shapely import wkb as shapely_wkb
    from shapely.ops import unary_union

    merged = unary_union([shapely_wkb.loads(bytes(p)) for p in parts])
    out = _as_multipolygon(merged)
    if out is None:
        raise SourceProblem("merging the parts of one place produced no polygon")
    return out.wkb


def tolerance_for(level):
    """How much detail a polygon at this level can afford to lose."""
    return SIMPLIFY_TOLERANCE.get(level, DEFAULT_TOLERANCE)


# --------------------------------------------------------------- writing back
# Filling in everything that can be derived from the shape itself, in one
# statement per source rather than one per polygon.

DERIVE_SQL = """
UPDATE admin_areas SET
    geom_web = ST_Multi(ST_CollectionExtract(
                   ST_MakeValid(ST_SimplifyPreserveTopology(geom, %(tol)s)), 3)),
    bbox_w   = ST_XMin(geom), bbox_s = ST_YMin(geom),
    bbox_e   = ST_XMax(geom), bbox_n = ST_YMax(geom),
    -- PointOnSurface, not Centroid: the centre of a crescent-shaped district
    -- falls outside it, and a symbol drawn there sits in the neighbouring one.
    center_lon = COALESCE(center_lon, ST_X(ST_PointOnSurface(geom))),
    center_lat = COALESCE(center_lat, ST_Y(ST_PointOnSurface(geom))),
    area_sqkm  = COALESCE(area_sqkm, ST_Area(geom::geography) / 1000000.0)
WHERE source_id = %(source_id)s;
"""

# Simplifying can, on a very thin polygon, collapse it to nothing. Where that
# happened, fall back to the full shape: a heavy polygon beats an absent one.
DERIVE_FALLBACK_SQL = """
UPDATE admin_areas SET geom_web = geom
WHERE source_id = %(source_id)s AND (geom_web IS NULL OR ST_IsEmpty(geom_web));
"""

# The IFRC Areas of Interest have no country of their own. Give each one the
# country whose outline contains it. This is the fix for the fault that let
# Sudanese reporting highlight an Ethiopian region: with a country on every
# polygon, the matcher's "same country" rule finally applies to all of them.
LOCATE_AOI_SQL = """
UPDATE admin_areas aoi SET iso3 = c.iso3, country_name = c.country_name
FROM admin_areas c
WHERE aoi.kind = 'aoi' AND c.kind = 'admin' AND c.level = 0
  AND ST_Contains(c.geom, ST_PointOnSurface(aoi.geom));
"""

# GADM's Sudan ADM3 cannot be joined to OCHA's ADM2 by name - the two
# publishers transliterate differently ("Al Jazirah" against "Aj Jazirah") - so
# each locality is given the district that actually contains it.
LINK_PARENT_SPATIAL_SQL = """
UPDATE admin_areas child
SET parent_pcode = parent.pcode,
    name_path    = parent.name_path || ' > ' || child.name,
    parent_method = 'spatial'
FROM admin_areas parent
WHERE child.source_id = %(source_id)s
  AND parent.iso3 = child.iso3 AND parent.kind = 'admin'
  AND parent.level = %(parent_level)s
  AND ST_Contains(parent.geom, ST_PointOnSurface(child.geom));
"""


# --------------------------------------------------------------- reading out
def features_sql(where, simplify=True):
    """A query returning one finished GeoJSON Feature per row.

    ST_AsGeoJSON writes the geometry; the properties are assembled beside it and
    the view only has to join the pieces with commas. Coordinates are rounded on
    the way out - five places is about a metre, and anything beyond that is
    bytes spent on precision no screen can render.
    """
    geom_col = "geom_web" if simplify else "geom"
    return f"""
        SELECT pcode,
               json_build_object(
                   'type', 'Feature',
                   'id', pcode,
                   'geometry', ST_AsGeoJSON({geom_col}, {COORD_PRECISION})::json,
                   'properties', json_build_object(
                       'id', pcode, 'pcode', pcode, 'name', name,
                       'level', level, 'kind', kind,
                       'iso3', iso3, 'country', country_name,
                       'parent', parent_pcode, 'path', name_path,
                       'lat', center_lat, 'lon', center_lon
                   )
               )::text
        FROM admin_areas
        WHERE {where} AND {geom_col} IS NOT NULL
    """
