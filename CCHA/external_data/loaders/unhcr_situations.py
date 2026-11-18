"""UNHCR situations CSV -> movement_patterns, Sudanese by country of asylum.

SOURCE IS 'unhcr-odp', NOT 'unhcr', and that matters. movement_patterns
already holds a `unhcr/refugees` series - UNHCR's ANNUAL stocks via HDX HAPI,
mid-year dated - and `excel/refugees` from the office's own workbook.
s06.build_refugees() reads metric='refugees' and merges what it finds. Landing
a third, sub-monthly series under the same metric without saying so would
silently rewrite the refugee totals the dashboard has always drawn, so this
loader takes its own source and build_refugees() names the two it wants.

ONE VALUE PER COUNTRY PER DATE, NEVER A SUM. UNHCR reclassifies a population
between 'Asylum-Seekers' and 'Refugees' as status determination catches up, and
publishes BOTH types on the changeover date. Checked across the whole Sudan
series: Kenya 2026-02-28 carries 13,433 under each label, Uganda 2026-03-16
carries 183,215 under each, South Sudan 2025-12-01 carries 1,013,746 and
1,016,692. They are the same people relabelled. Summing would double-count
every country once, at the one date a reader is most likely to be looking at.
So the two types are collapsed by taking the LARGER, which keeps the restated
figure where the pair disagrees.
"""
from datetime import datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import MovementPattern

# The two labels that describe the same displaced population at different
# points in its status determination.
COLLAPSED_TYPES = {"Refugees", "Asylum-Seekers"}


def _as_date(value):
    """'2026-09-07' -> date. Anything unparseable is skipped by the caller."""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@register
class UnhcrSituationsLoader(Loader):
    """Sudanese refugees and asylum-seekers, by country of asylum, over time."""

    # THE SAME NAME THE FETCHER USES. Loader.sync_key() keys the watermark on
    # the LOADER's dataset, so a loader named differently from its fetcher
    # writes to a source_sync row nobody is looking at - leaving the seeded row
    # the Pull now button owns reading "never pulled" for ever.
    dataset = "situations"
    source = "unhcr-odp"
    model = MovementPattern
    tool = "package_show + csv"
    unique_fields = ["source", "metric", "iso3", "admin_pcode", "place_name",
                     "date", "population_group"]
    update_fields = ["admin_level", "value", "unit", "source_dataset",
                     "reference_period_start", "reference_period_end", "lat", "lon"]

    def parse(self, payload, iso3, context=None):
        records = payload.get("rows") or []

        # Collapse to one figure per (asylum country, date) before building
        # rows - see the module docstring on why this is a max and not a sum.
        best = {}
        for r in records:
            if (r.get("ISO3 of Origin") or "").strip() != "SDN":
                continue
            if (r.get("Population type") or "").strip() not in COLLAPSED_TYPES:
                continue
            asylum_iso3 = (r.get("ISO3") or "").strip()
            country = (r.get("Country") or "").strip()
            on = _as_date(r.get("Date"))
            if not (asylum_iso3 and country and on):
                continue
            # SUDAN AS ITS OWN COUNTRY OF ASYLUM IS EXCLUDED. Those rows count
            # Sudanese who never left, or who came back and are still counted
            # as of concern; either way they are not "where people went", and
            # putting them in a panel about countries of asylum would invite
            # the reading that Sudan hosts its own refugees abroad.
            if asylum_iso3 == "SDN":
                continue
            try:
                value = int(float(r.get("Individuals") or 0))
            except (TypeError, ValueError):
                continue
            key = (asylum_iso3, country, on)
            best[key] = max(best.get(key, 0), value)

        return [{
            "date": on, "iso3": asylum_iso3,
            "admin_pcode": None, "admin_level": 0, "place_name": country,
            "metric": "refugees", "population_group": "sudanese_refugees",
            "value": value, "unit": "individuals",
            "source": self.source, "source_dataset": "unhcr-situations",
            "reference_period_start": None, "reference_period_end": on,
            "lat": None, "lon": None,
        } for (asylum_iso3, country, on), value in sorted(best.items())]

    def count_scope(self, key):
        """Every row this source holds, whatever country it is about.

        This sync row has no iso3 - one CSV covers every country of asylum -
        so the default (source, iso3) scope would count rows with a null iso3
        and report 0.
        """
        return {"source": self.source}

    def high_water(self, rows):
        return max((r["date"] for r in rows if r["date"]), default=None)
