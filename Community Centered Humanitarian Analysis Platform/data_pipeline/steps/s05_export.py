"""Step 5 of 7 - export the database into the JSON files the dashboard reads.

The map is a plain static page: it cannot query PostgreSQL directly, so this
step writes small, ready-to-draw files into dashboard/data/:

  meta.json       how big the corpus is and which dates it spans
  flows.json      corridor geometry plus its cleaned cumulative series
  headline.json   the regional headline metrics over time
  events.json     the timeline
  tags.json       monthly counts per theme (what the toggles show)
  documents.json  the catalogue of source PDFs

The interesting part is clean_series() below: extracted numbers always contain
some misreads, and this is where they are filtered out before publication.
"""
import json
from collections import defaultdict
from datetime import datetime

from django.db.models import F, Max, Min

from data_pipeline.common import DASHBOARD_DATA, load_gazetteer
from data_track.models import Document, DocumentText, Event, MovementFlow, NarrativeTag, PopulationFigure

GAZ = load_gazetteer()


def clean_series(points, monotone=True):
    """Turn raw (date, value) pairs into a trustworthy time series.

    points -> sorted, de-duplicated, with obvious parser mistakes removed.

    Pass 1 collapses several readings on the same date to their median.
    Pass 2 depends on the kind of metric:

      monotone=False (IDP counts, total displaced)
        These can genuinely fall as people return home, so we only reject a
        value that is wildly different from its immediate neighbours.

      monotone=True (cumulative arrivals, returns)
        A cumulative total can never fall. We reject any drop, and we accept a
        sudden jump only if later reports confirm the new level - genuine
        revisions persist, parser glitches do not.
    """
    by_date = defaultdict(list)
    for d, v in points:
        if d and v:
            by_date[d].append(v)

    merged = []
    for d in sorted(by_date):
        values = sorted(by_date[d])
        merged.append((d, values[len(values) // 2]))     # the median reading

    if not monotone:
        # Rolling-median filter: tolerant of gradual change, intolerant of a
        # single point that is twice (or half) its neighbours.
        values = [v for _, v in merged]
        out = []
        for i, (d, v) in enumerate(merged):
            window = sorted(values[max(0, i - 2):i + 3])
            median = window[len(window) // 2]
            if median and (v > median * 2.0 or v < median * 0.5):
                continue
            out.append({"date": d.isoformat(), "value": v})
        return out

    out, running_max = [], 0
    for i, (d, v) in enumerate(merged):
        if running_max and v < running_max * 0.9:
            continue                                   # cumulative totals do not fall
        if running_max >= 100_000 and v > running_max * 1.5:
            following = [x for _, x in merged[i + 1:i + 4]]
            needed = min(2, len(following))
            # Only believe a big jump if the next reports stay near the new level.
            if needed == 0 or sum(1 for x in following if x >= v * 0.75) < needed:
                continue
        out.append({"date": d.isoformat(), "value": v})
        running_max = max(running_max, v)
    return out


def run():
    """Write every dashboard file. Existing files are overwritten."""
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)

    def dump(name, obj):
        """Write one JSON file compactly and report its size."""
        path = DASHBOARD_DATA / name
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {name:16} {path.stat().st_size / 1024:8.1f} KB")

    # ---- flows: one entry per corridor, with its cleaned series -----------
    corridors = defaultdict(list)
    geometry = {}
    for row in MovementFlow.objects.order_by("corridor", "report_date", "id"):
        corridors[row.corridor].append((row.report_date, row.value))
        # The origin/destination points are the same on every row of a
        # corridor, so remember the first one we see.
        geometry.setdefault(row.corridor, {
            "origin": {"name": row.origin, "lat": row.origin_lat, "lon": row.origin_lon},
            "destination": {"name": row.destination, "lat": row.dest_lat, "lon": row.dest_lon},
            "flow_type": row.flow_type,
        })

    flows = {}
    for corridor, points in corridors.items():
        series = clean_series(points)
        if len(series) < 2:
            continue                                   # a single dot draws no arrow
        flows[corridor] = {**geometry[corridor], "series": series}
    dump("flows.json", flows)

    # ---- headline series -------------------------------------------------
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
    # These four are already country-wide totals, so we take every row.
    # The others only make sense as the "Regional" roll-up.
    ALL_COUNTRIES = ("idps", "total_displaced", "returns_to_sudan_total", "arrivals_from_south_sudan")

    headline = {}
    for metric, label in metrics.items():
        rows = PopulationFigure.objects.filter(metric=metric)
        if metric not in ALL_COUNTRIES:
            rows = rows.filter(country="Regional")
        points = list(rows.order_by("report_date").values_list("report_date", "value"))
        # IDP and total-displaced counts can genuinely fall, so no monotonicity.
        series = clean_series(points, monotone=metric not in ("idps", "total_displaced"))
        if series:
            headline[metric] = {"label": label, "series": series}
    dump("headline.json", headline)

    # ---- events ----------------------------------------------------------
    events = [
        {"date": e.event_date.isoformat(), "title": e.title, "description": e.description,
         "category": e.category, "location": e.location, "lat": e.lat, "lon": e.lon,
         "severity": e.severity, "source": e.source}
        for e in Event.objects.exclude(event_date=None).order_by("event_date", "id")
    ]
    dump("events.json", events)

    # ---- tags: monthly counts per dimension/tag, plus a sample sentence ---
    counts = defaultdict(int)
    snippets = {}
    # Ordering by id matters: the "sample sentence" below is simply the first
    # suitable one we meet, so without a fixed order the example would change
    # from one run to the next even though the data had not changed.
    tag_rows = (NarrativeTag.objects.exclude(report_date=None).order_by("id")
                .values_list("dimension", "tag", "country", "report_date", "snippet",
                             "area_id", "area_name"))
    area_names = {}
    rows = tag_rows.iterator(chunk_size=5000)
    for dimension, tag, country, report_date, snippet, area_id, area_name in rows:
        month = report_date.strftime("%Y-%m")
        # area_id is None for the majority of rows, where the report named no
        # place. Those still count for the country; they simply cannot be put
        # on a particular polygon.
        counts[(dimension, tag, country, month, area_id)] += 1
        if area_id and area_name:
            area_names.setdefault(area_id, area_name)
        # Keep the first reasonably long sentence as the example for that
        # month AND that country. The country belongs in the key because the
        # dashboard can be filtered to one country, and a quote from the Chad
        # reporting must not be shown as evidence about Egypt.
        key = (dimension, tag, month, country)
        if key not in snippets and snippet and len(snippet) > 60:
            snippets[key] = snippet

    tags_out = defaultdict(lambda: defaultdict(lambda: {"monthly": [], "snippets": {}}))
    for (dimension, tag, country, month, area_id), n in sorted(
            counts.items(), key=lambda kv: tuple("" if x is None else x for x in kv[0])):
        row = {"month": month, "country": country, "count": n}
        if area_id:
            row["area"] = area_id
        tags_out[dimension][tag]["monthly"].append(row)
    # snippets is written as {month: {country: sentence}}. The dashboard also
    # still reads the older {month: sentence} shape, so an existing tags.json
    # keeps working until this step is next run.
    for (dimension, tag, month, country), snippet in snippets.items():
        tags_out[dimension][tag]["snippets"].setdefault(month, {})[country] = snippet
    dump("tags.json", {dim: dict(tags) for dim, tags in tags_out.items()})
    # What each area id was called in the reports, for the map's labels.
    dump("tag_areas.json", area_names)

    # ---- documents catalogue ---------------------------------------------
    documents = [
        {"id": d.id, "file": d.file_name, "family": d.family, "country": d.country_focus,
         "date": d.report_date.isoformat() if d.report_date else None,
         "collection": d.source_collection, "pages": d.pages}
        # nulls_first keeps any undated document at the top of the list.
        for d in Document.objects.order_by(F("report_date").asc(nulls_first=True), "id")
    ]
    dump("documents.json", documents)

    # ---- meta ------------------------------------------------------------
    span = Document.objects.aggregate(first=Min("report_date"), last=Max("report_date"))
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "documents": Document.objects.count(),
        "pages": DocumentText.objects.count(),
        "figures": PopulationFigure.objects.count(),
        "tags": NarrativeTag.objects.count(),
        "events": Event.objects.count(),
        # The timeline always starts on the day the war began, whatever the
        # earliest document happens to be.
        "date_min": "2023-04-15",
        "date_max": span["last"].isoformat() if span["last"] else None,
    }
    dump("meta.json", meta)
