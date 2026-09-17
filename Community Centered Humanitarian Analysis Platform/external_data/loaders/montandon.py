"""Montandon payloads -> hazard_events and hazard_impacts.

Three loaders, one sync row, and they run in the order the fetcher yields them:

    montandon_events    inserts the events, then places each point
    montandon_severity  does NOT insert - applies severity onto events by corr_id
    montandon_impacts   inserts the impacts, then classifies significance

Only the first counts rows. See Loader.counts_rows: load() overwrites
sync.row_count from its own model every time, so without that flag the last
loader to run would report the impact count as the number of events held.
"""
from datetime import datetime

from django.db import connection

from external_data import hazards
from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import HazardEvent, HazardImpact


def _family(collection):
    """gdacs-events -> gdacs.

    The row records the collection FAMILY. Which of the three calls it arrived
    in is not worth a column: the three land in different tables and different
    columns, so the suffix carries no information the row does not already have.
    """
    for suffix in ("-events", "-hazards", "-impacts"):
        if collection.endswith(suffix):
            return collection[: -len(suffix)]
    return collection


def _date(value):
    """An ISO timestamp to a date, or None."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _point(geometry):
    """(lon, lat) from a STAC Point, or (None, None).

    All three chosen collections publish points; anything else is a source
    behaving unexpectedly and is left unplaced rather than guessed at. An
    unplaced row still loads - match_method says so - because a hazard nobody
    can draw is still a hazard somebody published.
    """
    if not geometry or geometry.get("type") != "Point":
        return None, None
    coords = geometry.get("coordinates") or []
    return (coords[0], coords[1]) if len(coords) >= 2 else (None, None)


@register
class MontandonEventLoader(Loader):
    """The events. One row per (item x focus country named on the item)."""

    dataset = "montandon_events"
    source = "montandon"
    model = HazardEvent
    unique_fields = ["collection", "event_id", "iso3"]
    update_fields = ["corr_id", "event_date", "end_date", "title", "hazard_codes",
                     "hazard_category", "hazard_sub", "lat", "lon", "source_url",
                     "source"]
    tool = "monty__search_items"

    def sync_key(self, iso3, context=None):
        """All three loaders write the one montandon/hazard_events row."""
        return {"source": "montandon", "dataset": "hazard_events",
                "iso3": iso3, "variant": ""}

    def parse(self, payload, iso3, context=None):
        """Pure. No database access - see Loader.after_insert."""
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            # ONLY THIS COUNTRY. An item carrying ["ETH", "SDN"] becomes a row
            # under each, but only on that country's own pull - which is what
            # makes a per-country button mean what it says.
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            lon, lat = _point(feature.get("geometry"))
            codes = props.get("monty:hazard_codes") or []
            category, sub = hazards.for_hip(hazards.hip_from_codes(codes))
            rows.append({
                "source": "montandon",
                "collection": _family(feature.get("collection", "")),
                "event_id": feature.get("id"),
                "corr_id": props.get("monty:corr_id") or "",
                "iso3": iso3,
                "event_date": _date(props.get("start_datetime")
                                    or props.get("datetime")),
                "end_date": _date(props.get("end_datetime")),
                "title": props.get("title") or "",
                "hazard_codes": codes,
                "hazard_category": category,
                "hazard_sub": sub,
                "lat": lat,
                "lon": lon,
                # Defaults the after_insert pass overwrites where it can.
                "admin_pcode": None,
                "admin_level": None,
                "match_method": "unmatched",
                "source_url": None,
            })
        return rows

    def high_water(self, rows):
        dates = [r["event_date"] for r in rows if r["event_date"]]
        return max(dates) if dates else None

    def after_insert(self, rows):
        """Place every point, deepest admin level first.

        ST_Contains against admin_areas, which already carries a GIST index on
        geom from boundaries/migrations/0002_geometry_columns.py. DISTINCT ON
        with ORDER BY level DESC is the same "finest first, most precise wins"
        rule build_theme_areas() applies - a locality beats the state holding
        it, because "in El Fasher locality" and "somewhere in North Darfur" are
        different findings.

        Scoped to the rows this load actually touched, so a Chad pull does not
        re-place every Sudanese event.
        """
        if not rows:
            return
        iso3 = rows[0]["iso3"]
        collections = sorted({r["collection"] for r in rows})
        with connection.cursor() as cur:
            cur.execute("""
                UPDATE hazard_events h
                   SET admin_pcode  = m.pcode,
                       admin_level  = m.level,
                       match_method = 'point-in-polygon'
                  FROM (SELECT DISTINCT ON (e.id) e.id AS event_id, a.pcode, a.level
                          FROM hazard_events e
                          JOIN admin_areas a
                            ON a.iso3 = e.iso3
                           AND ST_Contains(
                                 a.geom,
                                 ST_SetSRID(ST_MakePoint(e.lon, e.lat), 4326))
                         WHERE e.iso3 = %s
                           AND e.collection = ANY(%s)
                           AND e.lon IS NOT NULL
                         ORDER BY e.id, a.level DESC) m
                 WHERE h.id = m.event_id
            """, [iso3, collections])
