"""FEWS NET `get_seasons` -> seasonal_calendar rows.

THE DE-DUPLICATION IS THE WHOLE JOB, and it is subtler than it first looks.

FEWS NET returns seasons once per historical version of the geographic unit they
apply to. Chad's six real seasons arrive as fifteen records - six under fnid "TD"
and three more each under "TD1960A0", "TD2008A0" and "TD2012A0", the country's 1960,
2008 and 2012 unit definitions - carrying identical months. Keeping them all would
draw every band three times over.

The obvious rule, "keep only the plain country fnid", is WRONG. Sudan's
"Traditional rainfed harvest", "Mechanized rainfed harvest" and "Irrigated harvest"
exist only under SD2014A0 and appear nowhere under "SD" - and those three are the
bands the dashboard has always drawn. That rule would have deleted them while
looking like it was removing duplicates.

So the key is the SEASON - (purpose, name) - not the fnid. Where one season appears
under several definitions, the country's current one wins; failing that, the most
recent versioned one, fnids sorting chronologically (SD1960A0 < SD2014A0).
"""
from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import SeasonalCalendar

# FEWS NET speaks ISO 3166-1 alpha-2; everything else in this project speaks alpha-3.
ISO3_TO_ISO2 = {
    "SDN": "SD", "TCD": "TD", "EGY": "EG", "ETH": "ET", "LBY": "LY",
    "SSD": "SS", "UGA": "UG", "CAF": "CF", "ERI": "ER",
}


def _months_between(start, end):
    """The months a span covers, wrap included: (11, 2) -> [11, 12, 1, 2]."""
    if not start or not end:
        return []
    out, m = [], start
    while True:
        out.append(m)
        if m == end or len(out) >= 12:
            break
        m = 1 if m == 12 else m + 1
    return out


@register
class SeasonalLoader(Loader):
    dataset = "seasonal_calendar"
    source = "fewsnet"
    model = SeasonalCalendar
    tool = "get_seasons"
    # source_ref (the fnid) is part of the key because the constraint includes it
    # for ACAPS's sake. For FEWS NET the parser has already reduced each season to
    # one winning definition, so adding it changes nothing here - but the declared
    # key MUST match the constraint or Postgres refuses the upsert outright.
    unique_fields = ["source", "iso3", "admin_pcode", "purpose", "label", "source_ref"]
    update_fields = [
        "country_name", "season_type", "months", "start_month", "end_month",
        "alignment", "description", "aliases", "display_order",
    ]

    def parse(self, payload, iso3, context=None):
        iso2 = ISO3_TO_ISO2.get(iso3)
        results = payload.get("results", []) if isinstance(payload, dict) else payload

        # De-duplicate by SEASON, not by fnid. Chad's versioned rows are exact
        # copies, so either rule works there - but Sudan's are not: its
        # "Traditional rainfed harvest", "Mechanized rainfed harvest" and
        # "Irrigated harvest" exist ONLY under SD2014A0, and those three are the
        # bands the dashboard has always drawn. Filtering on fnid would have
        # deleted them while looking like it was removing duplicates.
        best = {}
        for r in results:
            if r.get("unit_type") != "Admin 0":
                continue                      # national calendars only
            key = (r.get("purpose"), (r.get("name") or "").strip())
            fnid = str(r.get("fnid") or "")
            is_current = fnid == (iso2 or r.get("country_code"))
            kept = best.get(key)
            if kept is None:
                best[key] = (is_current, fnid, r)
                continue
            kept_current, kept_fnid, _ = kept
            # The country's current definition wins; failing that, the most
            # recent versioned one (fnids sort chronologically: SD1960 < SD2014).
            if (is_current, fnid) > (kept_current, kept_fnid):
                best[key] = (is_current, fnid, r)

        rows = []
        for _, _, r in best.values():
            rows.append({
                "iso3": iso3,
                "country_name": r.get("country") or "",
                "admin_pcode": None,
                "source": self.source,
                "source_ref": r.get("fnid"),
                "label": r.get("name") or "",
                "season_type": r.get("season_type"),
                "purpose": r.get("purpose"),
                "start_month": r.get("start_month"),
                "end_month": r.get("end_month"),
                "months": _months_between(r.get("start_month"), r.get("end_month")),
                "alignment": r.get("alignment"),
                "description": r.get("description") or "",
                "aliases": r.get("aliases") or [],
                "display_order": r.get("order") or 0,
            })
        return rows
