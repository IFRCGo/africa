"""The contract every loader keeps, and the one function that applies it.

A loader is a small class that knows how to turn one recorded payload into rows. It
does not know where the payload came from, which is the point: the assistant pulls
through MCP today and something else might fetch the same JSON tomorrow.

Four guarantees, enforced here rather than left to each parser:

  idempotent     upsert on the natural key, so loading a file twice is a no-op
  transactional  one file is one transaction; a bad record aborts the whole load
  ordered        source_sync is written LAST, inside that transaction, so the
                 watermark can never claim data the tables do not have
  loud on empty  an MCP error serialised as [] is a failed load, never 'up to date'

Two escape hatches, both used by the Montandon loaders and by nothing else yet:
`_insert_rows` lets a loader insert nothing and apply its payload onto rows
another loader wrote, and `after_insert` is where raw SQL goes that needs those
rows to already exist - parse() is pure, so it cannot reach the database.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from django.db import connection, transaction

from external_data.models import SourceSync


class EmptyPayload(Exception):
    """The payload held no usable rows. Never treated as success."""


@dataclass
class LoadResult:
    written: int
    high_water_date: object
    sync: object


class Loader:
    """Subclass, set the class attributes, and implement parse()."""

    dataset = ""          # 'seasonal_calendar' - also the command-line name
    source = ""           # 'fewsnet'
    model = None          # the Django model rows are written to
    unique_fields = []    # the natural key, matching the model's UniqueConstraint
    update_fields = []    # everything else, overwritten on conflict
    tool = ""             # the MCP tool this payload came from, for the record

    # Whether load() should write sync.row_count from this loader's model.
    #
    # THREE LOADERS SHARE ONE SYNC ROW for Montandon - events, severity and
    # impacts - and load() overwrites row_count from its own model every time.
    # Without this flag the last loader to run would win, and the freshness
    # table would report the impact count as the number of events held.
    counts_rows = True

    def parse(self, payload, iso3, context=None):
        """Return a list of dicts, one per model row. Pure - no database access.

        `context` carries what the payload itself does not. IPC's GeoJSON, for
        instance, names its analysis but not the period that analysis describes -
        that lives in the filename the pull was saved under - so the command passes
        it in rather than the parser guessing a date.
        """
        raise NotImplementedError

    def sync_key(self, iso3, context=None):
        """Which source_sync row this load belongs to.

        The call's ARGUMENTS ARE NEVER PART OF THIS. start_date lives in params, so
        including it would give every incremental pull its own row and the
        watermark would never accumulate.
        """
        return {"source": self.source, "dataset": self.dataset, "iso3": iso3, "variant": ""}

    def high_water(self, rows):
        """The newest DATA date in these rows, or None for a dateless source."""
        return None

    def known_ids(self, rows):
        """Identities now held, for sources with no date filter. Merged, not replaced."""
        return []

    def _insert_rows(self, rows):
        """The model instances to upsert. Override to insert nothing.

        MontandonSeverityLoader overrides it: a severity item has its own STAC
        id and is not an event, so upserting them into hazard_events would
        double every row that has a severity. It applies its payload onto rows
        another loader already wrote, in after_insert.
        """
        return [self.model(**row) for row in rows]

    def count_scope(self, key):
        """Which rows row_count counts for this source.

        Source and country by default, which is right for every per-country
        pull. A source whose sync row has NO country - one file covering every
        country of asylum, say - must drop iso3 or it counts rows whose iso3 is
        null, of which there are none, and the admin page reads 0 beside a
        table full of data.
        """
        return {k: v for k, v in key.items() if k in ("source", "iso3")}

    def after_insert(self, rows):
        """Optional: raw SQL that needs the rows to already exist.

        Called inside load()'s transaction, after bulk_create and after the
        geometry pass. This is where work belongs that parse() cannot do,
        because parse() is pure - resolving a point to a p-code, or applying a
        severity onto rows keyed by something other than the natural key.
        """
        return None


@transaction.atomic
def load(loader, payload, iso3, dry_run=False, context=None):
    """Parse, upsert, then write the watermark - all or nothing."""
    rows = loader.parse(payload, iso3, context or {})
    if not rows:
        # Deliberately an exception. Recording an empty pull as a successful one
        # would advance the watermark past data we do not have, and every later
        # refresh would skip it.
        raise EmptyPayload(
            f"{loader.dataset}: the payload produced no rows. "
            "An MCP error serialised as an empty list looks exactly like this - "
            "check the pull before treating it as 'nothing new'."
        )

    if dry_run:
        return LoadResult(written=len(rows), high_water_date=loader.high_water(rows), sync=None)

    # Geometry travels beside the row rather than in it: the geom columns are
    # invisible to Django, so they are written separately, in SQL.
    geometries = [row.pop("_geometry", None) for row in rows]

    # A loader that inserts nothing says so by overriding _insert_rows.
    # Everything else gets the ordinary upsert.
    objects = loader._insert_rows(rows)
    if objects:
        loader.model.objects.bulk_create(
            objects,
            update_conflicts=True,
            unique_fields=loader.unique_fields,
            update_fields=loader.update_fields,
        )

        if any(g is not None for g in geometries):
            _write_geometry(loader, rows, geometries)

    # After the rows exist, and still inside this transaction.
    loader.after_insert(rows)

    key = loader.sync_key(iso3, context or {})
    sync, _ = SourceSync.objects.get_or_create(**key)
    sync.tool = loader.tool
    sync.last_pulled_at = datetime.now(timezone.utc)

    hw = loader.high_water(rows)
    # Only ever move forward. A backfill of older data must not rewind the mark.
    if hw and (sync.high_water_date is None or hw > sync.high_water_date):
        sync.high_water_date = hw

    new_ids = loader.known_ids(rows)
    if new_ids:
        sync.known_ids = sorted(set(sync.known_ids or []) | set(new_ids))

    # Only the loader that OWNS this sync row writes its count. See counts_rows.
    if loader.counts_rows:
        sync.row_count = loader.model.objects.filter(**loader.count_scope(key)).count()
    sync.save()

    return LoadResult(written=len(rows), high_water_date=sync.high_water_date, sync=sync)


def _write_geometry(loader, rows, geometries):
    """Set geom and geom_web by raw SQL, keyed on the natural key.

    Raw SQL because these columns are invisible to Django - see the migration that
    adds them. ST_Multi wraps a plain Polygon so the MultiPolygon column accepts it,
    and ST_MakeValid repairs the self-intersections publishers' polygons carry.

    A POINT AND A BROKEN POLYGON LOOK ALIKE AFTER REPAIR, AND MUST NOT BE TREATED
    ALIKE. ST_MakeValid on a degenerate polygon - a sliver, a zero-area ring -
    returns whatever survives, sometimes a MultiPoint; extracting dimension 3 is
    what discards that rubbish. But IPC genuinely publishes some analysis units as
    Points - camps and urban areas, Zamzam IDP Camp among them - and running the
    same extraction over those deletes real data.

    So the shape is inspected first: a point stays a point, and only polygonal
    input is repaired and polygon-extracted. The columns are typed
    `geometry(Geometry, 4326)` to hold both, as map_features already is.
    """
    where = " AND ".join(f"{f} = %s" for f in loader.unique_fields)
    sql = f"""
        UPDATE {loader.model._meta.db_table}
           SET geom = CASE
                   WHEN GeometryType(ST_GeomFromGeoJSON(%s)) IN ('POINT', 'MULTIPOINT')
                   THEN ST_GeomFromGeoJSON(%s)
                   ELSE ST_Multi(ST_CollectionExtract(
                            ST_MakeValid(ST_GeomFromGeoJSON(%s)), 3))
               END,
               geom_web = CASE
                   WHEN GeometryType(ST_GeomFromGeoJSON(%s)) IN ('POINT', 'MULTIPOINT')
                   THEN ST_GeomFromGeoJSON(%s)
                   ELSE ST_Multi(ST_CollectionExtract(ST_MakeValid(
                            ST_SimplifyPreserveTopology(
                                ST_MakeValid(ST_GeomFromGeoJSON(%s)), %s)), 3))
               END
         WHERE {where}
    """
    with connection.cursor() as cur:
        for row, geom in zip(rows, geometries):
            if geom is None:
                continue
            gj = json.dumps(geom)
            # gj appears five times in the CASE expressions above, then the
            # simplification tolerance, then the natural key.
            cur.execute(sql, [gj, gj, gj, gj, gj, gj, 0.002]
                        + [row[f] for f in loader.unique_fields])
