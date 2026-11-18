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
            category, sub = hazards.for_codes(codes)
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
        """Place every point, against every boundary, deepest level first.

        ST_Contains against admin_areas, which already carries a GIST index on
        geom from boundaries/migrations/0002_geometry_columns.py.

        THE MATCH IS NOT RESTRICTED TO THE FILING COUNTRY, and that is the whole
        point of admin_iso3. Montandon's country tags are loose: Sudan's first
        pull returned 813 events of which 527 had coordinates outside Sudan -
        fires in South Sudan, floods in Ethiopia, an earthquake in the Red Sea.
        Requiring a Sudanese polygon refused every one of them and the map lost
        two thirds of the layer. Matching against any boundary puts each event
        where it actually happened, which is what the layer is for, and
        admin_iso3 records whose polygon won.

        THE ORDER OF PREFERENCE, where a point could belong to more than one:
        the filing country's own polygon first - if Montandon says Sudan and the
        point IS in Sudan, that is the answer - then the deepest level, which is
        the same "finest first, most precise wins" rule build_theme_areas()
        applies, because "in El Fasher locality" and "somewhere in North Darfur"
        are different findings.

        ADMIN AREAS ONLY. The same table also holds 14 IFRC Areas of Operation
        under kind='aoi', and they have no level - which in Postgres sorts
        FIRST under `level DESC`, so every one of them beat every locality.
        Without this filter 493 of 2,422 events were placed onto one of those
        fourteen polygons instead of the district they were actually in.
        load_hsps.resolve_places() filters the same way, for the same reason.

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
                       admin_iso3   = m.iso3,
                       match_method = 'point-in-polygon'
                  FROM (SELECT DISTINCT ON (e.id)
                               e.id AS event_id, a.pcode, a.level, a.iso3
                          FROM hazard_events e
                          JOIN admin_areas a
                            ON a.kind = 'admin'
                           AND ST_Contains(
                                 a.geom,
                                 ST_SetSRID(ST_MakePoint(e.lon, e.lat), 4326))
                         WHERE e.iso3 = %s
                           AND e.collection = ANY(%s)
                           AND e.lon IS NOT NULL
                         ORDER BY e.id, (a.iso3 = e.iso3) DESC, a.level DESC) m
                 WHERE h.id = m.event_id
            """, [iso3, collections])


@register
class MontandonSeverityLoader(Loader):
    """The *-hazards items: severity, applied onto events that already exist.

    THIS LOADER INSERTS NOTHING. A hazard item has its own STAC id and is not an
    event; upserting them into hazard_events would double every row that has a
    severity. parse() returns the details as rows so the "empty is a failure"
    guarantee still catches a payload that came back broken, _insert_rows
    returns nothing, and after_insert does the real work with an UPDATE keyed on
    corr_id rather than on the natural key.

    A severity whose event never loaded matches nothing and is dropped. That is
    the right way round: an orphan severity says nothing on its own, whereas an
    orphan IMPACT is a figure somebody published and is kept.
    """

    dataset = "montandon_severity"
    source = "montandon"
    model = HazardEvent
    unique_fields = ["collection", "event_id", "iso3"]
    update_fields = []
    tool = "monty__search_items"
    counts_rows = False

    def sync_key(self, iso3, context=None):
        return {"source": "montandon", "dataset": "hazard_events",
                "iso3": iso3, "variant": ""}

    def parse(self, payload, iso3, context=None):
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            detail = props.get("monty:hazard_detail") or {}
            corr_id = props.get("monty:corr_id")
            if not corr_id or not detail:
                continue
            rows.append({
                "corr_id": corr_id,
                "iso3": iso3,
                "severity_value": detail.get("severity_value"),
                "severity_unit": detail.get("severity_unit"),
                "severity_label": detail.get("severity_label"),
                "severity_estimate_type": detail.get("estimate_type"),
            })
        return rows

    def _insert_rows(self, rows):
        """Nothing is inserted. See the class docstring."""
        return []

    def after_insert(self, rows):
        if not rows:
            return
        with connection.cursor() as cur:
            for row in rows:
                cur.execute("""
                    UPDATE hazard_events
                       SET severity_value = %s, severity_unit = %s,
                           severity_label = %s, severity_estimate_type = %s
                     WHERE corr_id = %s AND iso3 = %s
                """, [row["severity_value"], row["severity_unit"],
                      row["severity_label"], row["severity_estimate_type"],
                      row["corr_id"], row["iso3"]])


@register
class MontandonImpactLoader(Loader):
    """The *-impacts items, then the significance classification.

    LAST OF THE THREE, AND THAT IS THE POINT. significance needs severity and
    impacts both, so it is classified here - after the fetcher's third call has
    landed. plan() yields events, hazards, impacts in that order and the runner
    consumes the generator serially, which is what makes this safe.
    """

    dataset = "montandon_impacts"
    source = "montandon"
    model = HazardImpact
    unique_fields = ["collection", "impact_id", "iso3"]
    update_fields = ["corr_id", "event_date", "impact_type", "category",
                     "value", "unit", "estimate_type", "source"]
    tool = "monty__search_items"
    counts_rows = False

    def sync_key(self, iso3, context=None):
        return {"source": "montandon", "dataset": "hazard_events",
                "iso3": iso3, "variant": ""}

    def parse(self, payload, iso3, context=None):
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            detail = props.get("monty:impact_detail") or {}
            # A figure with no value is not a figure. value=0 IS one, and is
            # exactly what marks a GDACS fire detection - so test for None.
            if not detail or detail.get("value") is None:
                continue
            rows.append({
                "source": "montandon",
                "collection": _family(feature.get("collection", "")),
                "impact_id": feature.get("id"),
                "corr_id": props.get("monty:corr_id") or "",
                "iso3": iso3,
                "event_date": _date(props.get("datetime")),
                "impact_type": detail.get("type") or "unspecified",
                "category": detail.get("category"),
                "value": detail.get("value"),
                "unit": detail.get("unit"),
                "estimate_type": detail.get("estimate_type"),
            })
        return rows

    def after_insert(self, rows):
        """Classify every event in this country as event or detection.

        Read back and written in Python rather than as one clever UPDATE: the
        rule lives in hazard_codebook.json - which severity labels mean "no
        alert", per collection - and keeping it there is the point. Baking it
        into SQL would put a fact about GDACS inside a statement about hazards,
        where nobody maintaining the vocabulary would ever find it.
        """
        if not rows:
            return
        iso3 = rows[0]["iso3"]

        biggest = {}
        for impact in HazardImpact.objects.filter(iso3=iso3).values("corr_id", "value"):
            key = impact["corr_id"]
            biggest[key] = max(biggest.get(key, 0), impact["value"] or 0)

        detections, events = [], []
        for event in HazardEvent.objects.filter(iso3=iso3).values(
                "id", "collection", "severity_label", "corr_id"):
            bucket = (detections if hazards.is_detection(
                event["collection"], event["severity_label"],
                biggest.get(event["corr_id"])) else events)
            bucket.append(event["id"])

        if detections:
            HazardEvent.objects.filter(id__in=detections).update(significance="detection")
        if events:
            HazardEvent.objects.filter(id__in=events).update(significance="event")
