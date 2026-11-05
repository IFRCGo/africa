"""FEWS NET `get_ipc_phases` -> food_security rows, tagged source='fewsnet'.

WHY THIS EXISTS. IPC and FEWS NET do not cover the same countries, and where one
stops the other often continues. Ethiopia is the case that forced this: IPC has
published no analysis for it since May 2021 - nothing at all inside the crisis
window - while FEWS NET carries thousands of current-situation classifications for
it running to June 2026. Without this loader, Ethiopia is simply blank.

THEY ARE NOT THE SAME PRODUCT AND ARE NEVER POOLED. An IPC or Cadre Harmonise
analysis is a consensus exercise between agencies; a FEWS NET classification is
FEWS NET's own judgement on the IPC scale. Both are legitimate, they can disagree
about the same district in the same month, and `food_security.source` keeps them
apart so a reader always knows whose number they are looking at.

TWO THINGS FEWS NET DOES NOT GIVE US, both recorded rather than papered over:

  no geometry   these rows carry FEWS NET's own `fnid` unit codes, not p-codes and
                not polygons, so they are tabular until FEWS NET's geographic units
                are pulled separately. admin_pcode stays null.
  no phase mix  pct_phase3/4/5 come back null on this endpoint, so phase3plus_pct
                is null too. The overall phase is what this source publishes.

Records also arrive twice per unit and period - once "allowing for assistance" and
once not. The standard current-situation reading is WITHOUT assistance, so that one
wins where both exist; where only the assisted reading exists it is kept, and the
`assistance` flag on the row says which you have.
"""
from datetime import datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import FoodSecurityArea

SCENARIO_TO_PERIOD = {
    "CS": "current",
    "ML1": "projection",
    "ML2": "second_projection",
}


def _as_date(value):
    if not value:
        return None
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


@register
class FewsNetPhaseLoader(Loader):
    dataset = "fewsnet_phases"
    source = "fewsnet"
    model = FoodSecurityArea
    tool = "get_ipc_phases"
    unique_fields = ["source", "analysis_id", "period_type", "area_id"]
    update_fields = [
        "analysis_title", "condition", "iso3", "period_date", "area_title",
        "phase", "phase3_pct", "phase4_pct", "phase5_pct", "phase3plus_pct",
        "phase5_population", "total_population", "colour",
    ]

    def sync_key(self, iso3, context=None):
        # A separate row from the IPC watermark for the same country: they are
        # different sources with different ceilings, and merging their freshness
        # would hide whichever is staler.
        return {
            "source": self.source, "dataset": "food_security",
            "iso3": iso3, "variant": "fewsnet-phases",
        }

    def parse(self, payload, iso3, context=None):
        results = payload.get("results", []) if isinstance(payload, dict) else payload

        best = {}
        for r in results:
            reported = _as_date(r.get("reporting_date")) or _as_date(r.get("projection_start"))
            fnid = r.get("fnid")
            phase = r.get("value")
            if reported is None or not fnid or phase is None:
                continue
            period_type = SCENARIO_TO_PERIOD.get(r.get("scenario"), "current")
            key = (fnid, reported, period_type)
            assisted = bool(r.get("is_allowing_for_assistance"))
            kept = best.get(key)
            # Keep it if nothing is held yet, or if what is held allows for
            # assistance and this one does not - the unassisted reading is the
            # standard current situation.
            if kept is None or (kept[0] and not assisted):
                best[key] = (assisted, r)

        rows = []
        for (fnid, reported, period_type), (assisted, r) in best.items():
            phase = r.get("value")
            rows.append({
                "source": self.source,
                # One "analysis" per reporting date, which is how FEWS NET
                # publishes: a Food Security Outlook covering the whole country.
                "analysis_id": f"fewsnet-{r.get('country_code') or iso3}-{reported:%Y-%m}",
                "analysis_title": (r.get("source_document")
                                   or "FEWS NET Food Security Outlook"),
                "condition": "A",
                "iso3": iso3,
                "period_date": reported,
                "period_type": period_type,
                "area_id": fnid,
                "area_title": (r.get("geographic_unit_name") or "").strip(),
                "admin_pcode": None,        # fnid is not a p-code
                "phase": int(phase),
                "phase3_pct": r.get("pct_phase3"),
                "phase4_pct": r.get("pct_phase4"),
                "phase5_pct": r.get("pct_phase5"),
                # Null rather than 0: this endpoint publishes no phase mix, and a
                # zero here would read as "nobody in phase 3+", which is a claim
                # the source never made.
                "phase3plus_pct": None,
                "phase5_population": None,
                "total_population": None,
                "colour": IPC_COLOURS.get(int(phase)),
            })
        return rows

    def high_water(self, rows):
        return max((r["period_date"] for r in rows if r["period_date"]), default=None)

    def known_ids(self, rows):
        return sorted({r["analysis_id"] for r in rows})



# IPC's published phase colours, so a FEWS NET row draws the same as an IPC one.
IPC_COLOURS = {
    1: "#CDFACD", 2: "#FAE61E", 3: "#E67800", 4: "#C80000", 5: "#640000",
}
