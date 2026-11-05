"""IPC `get_areas_by_analysis` GeoJSON -> food_security rows.

Two rules are carried over verbatim from s06_mcp_layers.build_foodsec, because
changing either would change what the map has shown since it was built:

  * an area with no overall_phase is skipped entirely
  * phase 3+ is phase3_percent + phase4_percent + phase5_percent, rounded to 3dp

The property names are IPC's own and are not what you would guess: the analysis is
`anl_id`, the area is `aar_id`, the period is `ipc_period`, and `estimated_population`
arrives as a STRING. The payload does not name the period it describes at all -
that lives in the filename the pull was saved under - so the command passes it in
rather than this parser inventing a date.

Geometry goes in through raw SQL after the upsert, simplified at the same tolerance
the boundary library uses for a district.
"""
from datetime import date

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import FoodSecurityArea

# Sahel analyses are Cadre Harmonise; elsewhere the same API serves IPC proper.
# Same five-phase scale, different process and different authors - so the rows are
# labelled apart rather than pooled.
CH_COUNTRIES = {"TCD", "MLI", "NER", "BFA", "SEN", "MRT", "NGA"}

# IPC's single-letter period codes.
PERIOD_TYPES = {"C": "current", "P": "projection", "A": "second_projection"}


def _int_or_none(value):
    """IPC sends populations as strings ('92902') and sometimes as null."""
    if value in (None, "", "null"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@register
class FoodSecurityLoader(Loader):
    dataset = "food_security"
    model = FoodSecurityArea
    tool = "get_areas_by_analysis"
    unique_fields = ["source", "analysis_id", "period_type", "area_id"]
    update_fields = [
        "analysis_title", "condition", "iso3", "period_date", "area_title",
        "phase", "phase3_pct", "phase4_pct", "phase5_pct", "phase3plus_pct",
        "phase5_population", "total_population", "colour",
    ]

    def source_for(self, iso3):
        """`source` varies by country, so it cannot be a fixed class attribute."""
        return "ch" if iso3 in CH_COUNTRIES else "ipc"

    def sync_key(self, iso3, context=None):
        return {
            "source": self.source_for(iso3), "dataset": self.dataset,
            "iso3": iso3, "variant": "",
        }

    def parse(self, payload, iso3, context=None):
        context = context or {}
        period_date = context.get("period_date") or date(1900, 1, 1)
        source = self.source_for(iso3)

        rows = []
        for ft in payload.get("features", []):
            p = ft.get("properties", {})
            phase = p.get("overall_phase")
            if phase is None:
                continue                      # same rule as build_foodsec
            p3 = p.get("phase3_percent") or 0
            p4 = p.get("phase4_percent") or 0
            p5 = p.get("phase5_percent") or 0
            rows.append({
                "source": source,
                "analysis_id": str(p.get("anl_id") or ""),
                "analysis_title": context.get("analysis_title") or "",
                "condition": (context.get("condition") or "A")[:1],
                "iso3": iso3,
                "period_date": period_date,
                "period_type": PERIOD_TYPES.get(p.get("ipc_period"), "current"),
                "area_id": str(p.get("aar_id") or (p.get("title") or "").strip()),
                "area_title": (p.get("title") or "").strip(),
                "admin_pcode": None,
                "phase": phase,
                "phase3_pct": p.get("phase3_percent"),
                "phase4_pct": p.get("phase4_percent"),
                "phase5_pct": p.get("phase5_percent"),
                "phase3plus_pct": round(p3 + p4 + p5, 3),
                "phase5_population": _int_or_none(p.get("phase5_population")),
                "total_population": _int_or_none(p.get("estimated_population")),
                "colour": p.get("color") or "#cccccc",
                # Carried out of band to _write_geometry; not a model field.
                "_geometry": ft.get("geometry"),
            })
        return rows

    def known_ids(self, rows):
        return [r["analysis_id"] for r in rows if r["analysis_id"]]

    def high_water(self, rows):
        return max((r["period_date"] for r in rows if r["period_date"]), default=None)
