"""HDX IOM-DTM and UNHCR stocks -> movement_patterns rows.

Two loaders, one table. They differ in exactly one interesting way: DTM publishes
dated rounds, so its watermark is a real high-water date and the next pull can ask
for everything after it. UNHCR's stock figures are annual, so its watermark barely
moves and `notes` carries the ceiling - otherwise a refresh that correctly returns
nothing looks like a broken one.

DTM's `admin2_code` is an OCHA p-code (SD01001), which is what makes these rows
joinable to the boundary library without any name matching at all.
"""
from datetime import date, datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import MovementPattern


def _as_date(value):
    """'2025-12-31T00:00:00' or '2025-12-31' -> date. None stays None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


class _MovementLoader(Loader):
    model = MovementPattern
    unique_fields = [
        "source", "metric", "iso3", "admin_pcode", "date", "population_group",
    ]
    update_fields = [
        "admin_level", "place_name", "value", "unit", "source_dataset",
        "reference_period_start", "reference_period_end", "lat", "lon",
    ]

    def high_water(self, rows):
        return max((r["date"] for r in rows if r["date"]), default=None)


@register
class IdpLoader(_MovementLoader):
    """IOM-DTM cumulative IDP counts by admin2, via HDX HAPI `get_idps`."""

    dataset = "idps"
    source = "hdx"
    tool = "get_idps"

    def sync_key(self, iso3, context=None):
        # The variant matters: the same country's IDPs at admin1 are a different
        # thing to pull, and must not share this row's watermark.
        return {
            "source": self.source, "dataset": self.dataset,
            "iso3": iso3, "variant": "admin2-overview",
        }

    def parse(self, payload, iso3, context=None):
        records = payload if isinstance(payload, list) else payload.get("data", [])
        rows = []
        for r in records:
            end = _as_date(r.get("reference_period_end"))
            if end is None or r.get("population") is None:
                continue
            rows.append({
                "date": end,
                "iso3": r.get("location_code") or iso3,
                "admin_pcode": r.get("admin2_code"),
                "admin_level": r.get("admin_level") or 2,
                "place_name": r.get("admin2_name"),
                "metric": "idps",
                "population_group": "idps",
                "value": int(r["population"]),
                "unit": "individuals",
                "source": self.source,
                "source_dataset": "iom-dtm",
                "reference_period_start": _as_date(r.get("reference_period_start")),
                "reference_period_end": end,
                "lat": None, "lon": None,
            })
        return rows


@register
class RefugeeLoader(_MovementLoader):
    """UNHCR registered refugee stocks by country of asylum, via HDX `get_refugees`."""

    dataset = "refugees"
    source = "unhcr"
    tool = "get_refugees"

    def parse(self, payload, iso3, context=None):
        records = payload if isinstance(payload, list) else payload.get("data", [])
        rows = []
        for r in records:
            year = r.get("year") or str(r.get("reference_period_end") or "")[:4]
            if not year or r.get("population") is None:
                continue
            asylum = (r.get("asylum_location_code") or r.get("location_code") or iso3)
            rows.append({
                # Mid-year, matching the series the dashboard already draws.
                "date": date(int(year), 7, 1),
                "iso3": asylum,
                "admin_pcode": None,
                "admin_level": 0,
                "place_name": r.get("asylum_location_name") or r.get("location_name"),
                "metric": "refugees",
                "population_group": r.get("population_group") or "sudanese_refugees",
                "value": int(r["population"]),
                "unit": "individuals",
                "source": self.source,
                "source_dataset": "get_refugees",
                "reference_period_start": None,
                "reference_period_end": None,
                "lat": None, "lon": None,
            })
        return rows
