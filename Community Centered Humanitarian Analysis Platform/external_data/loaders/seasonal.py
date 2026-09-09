"""FEWS NET `get_seasons` -> seasonal_calendar rows.

THE DE-DUPLICATION IS THE WHOLE JOB. FEWS NET returns every season once per
historical version of the geographic unit it applies to, so Chad's six real seasons
arrive as fifteen records: six under fnid "TD", and three more each under
"TD1960A0", "TD2008A0" and "TD2012A0" - the country's 1960, 2008 and 2012 unit
definitions. They carry identical months. Keeping them all would draw every band
three times over.

The rule: keep the national record for the CURRENT definition - unit_type "Admin 0"
and an fnid equal to the plain country code - and discard the rest.
"""
from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import SeasonalCalendar

# FEWS NET speaks ISO 3166-1 alpha-2; everything else in this project speaks alpha-3.
ISO3_TO_ISO2 = {
    "SDN": "SD", "TCD": "TD", "EGY": "EG", "ETH": "ET", "LBY": "LY",
    "SSD": "SS", "UGA": "UG", "CAF": "CF", "ERI": "ER",
}


@register
class SeasonalLoader(Loader):
    dataset = "seasonal_calendar"
    source = "fewsnet"
    model = SeasonalCalendar
    tool = "get_seasons"
    unique_fields = ["source", "iso3", "admin_pcode", "purpose", "label"]
    update_fields = [
        "country_name", "source_ref", "season_type", "start_month", "end_month",
        "alignment", "description", "aliases", "display_order",
    ]

    def parse(self, payload, iso3, context=None):
        iso2 = ISO3_TO_ISO2.get(iso3)
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        rows = []
        for r in results:
            # The two conditions that drop the historical unit versions.
            if r.get("unit_type") != "Admin 0":
                continue
            if r.get("fnid") != (iso2 or r.get("country_code")):
                continue
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
                "alignment": r.get("alignment"),
                "description": r.get("description") or "",
                "aliases": r.get("aliases") or [],
                "display_order": r.get("order") or 0,
            })
        return rows
