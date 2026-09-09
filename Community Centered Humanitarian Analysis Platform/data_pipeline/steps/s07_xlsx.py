"""Step 7 of 7 - the Excel layers, built FROM THE DATABASE.

The two workbooks an analyst maintains by hand beside the PDFs are no longer read
here. `manage.py load_workbooks` reads them into movement_patterns, and this step
draws from that table like everything else.

    neighbouring countries Pop movement data.xlsx  -> movement_patterns, refugees
    Sudan IDPs.xlsx                                -> movement_patterns, idps admin1

WHY THIS STEP GOT SMALLER. It used to rewrite refugee_camps.json after s06 had
already written it, merging the workbook's biweekly series into s06's annual one.
Two steps owning one file meant whichever ran last decided what the dashboard
showed, and moving s06 onto the database while leaving this alone would have had
step 7 quietly overwrite it on the next run. Both sources now sit in one table and
s06 reads them together, so this step owns exactly one output:

    idp_states.json    Sudan admin1 IDP bubbles, which s06 never touched

Run it with:  python manage.py run_pipeline --only s06,s07
"""
import collections
import json

from django.db import connection

from data_pipeline.common import DASHBOARD_DATA
from external_data.models import MovementPattern


def _dump(name, obj):
    """Write one file into dashboard/data/ and print its size."""
    p = DASHBOARD_DATA / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {name:30} {p.stat().st_size / 1024:8.1f} KB")


def build_idp_states():
    """Sudan admin1 IDP snapshots, placed by the boundary library.

    The state centroids used to come from a cached geoBoundaries file matched by
    name, with a small correction table for the two spellings that did not line up.
    The rows now carry OCHA p-codes - resolved when the workbook was loaded - so the
    placement is an exact join and no name has to be reconciled here at all.
    """
    rows = (MovementPattern.objects
            .filter(source="excel", metric="idps", iso3="SDN")
            .exclude(admin_pcode=None)
            .order_by("admin_pcode", "date"))

    with connection.cursor() as cur:
        cur.execute("""
            SELECT pcode, name, center_lon, center_lat
              FROM admin_areas
             WHERE iso3 = 'SDN' AND level = 1 AND kind = 'admin'
        """)
        places = {p: (n, lon, lat) for p, n, lon, lat in cur.fetchall()}

    states = collections.defaultdict(lambda: {"name": "", "series": []})
    for r in rows:
        d = states[r.admin_pcode]
        d["name"] = r.place_name or ""
        d["series"].append({"date": r.date.isoformat(), "value": int(r.value)})

    out, unmatched = [], []
    for pcode, d in states.items():
        place = places.get(pcode)
        if not place:
            unmatched.append(d["name"] or pcode)
            continue
        name, lon, lat = place
        out.append({
            "name": d["name"] or name, "pcode": pcode,
            "lon": round(lon, 4), "lat": round(lat, 4),
            "peak": max(p["value"] for p in d["series"]),
            "series": d["series"],
        })
    out.sort(key=lambda x: -x["peak"])

    dates = sorted({p["date"] for s in out for p in s["series"]})
    _dump("idp_states.json", {
        "source": "Sudan IDPs.xlsx, held in movement_patterns; states placed on OCHA "
                  "p-codes from the boundary library.",
        "metric": "IDP individuals by state (admin1)",
        "dates": dates,
        "states": out,
    })
    print(f"    {len(out)} states, {len(dates)} time points: {dates}")
    if unmatched:
        print(f"    {len(unmatched)} without a polygon: {', '.join(unmatched)}")


def run():
    """Rebuild the admin1 IDP layer from the database."""
    print("== Excel-sourced layers, from the database")
    build_idp_states()
