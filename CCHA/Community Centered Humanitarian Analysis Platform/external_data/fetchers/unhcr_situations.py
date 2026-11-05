"""UNHCR Operational Data Portal situations -> where Sudanese have gone.

WHAT THIS IS FOR. IOM DTM says how many people returned to each Sudanese
locality from outside the country, and never which country they came from.
This is the other end of that movement: UNHCR's count of Sudanese refugees and
asylum-seekers held in each country of asylum, sub-monthly, so a reader can see
where the population that is now coming home had been.

It is national-level and it stays that way. Nothing here may be attributed to a
Sudanese locality - that join does not exist in either source, and inventing it
is the failure this project's evidence trail exists to prevent.

ONE RESOURCE, WHOLE SERIES, EVERY TIME. The CSV is ~2,750 rows for every
country UNHCR tracks and there is no date parameter, so a pull takes the lot
and the loader upserts. It is about 200 KB; narrowing it would buy nothing and
cost the ability to see a restated figure.
"""
from pathlib import Path

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, http_get_json

DATASET_STUB = "unhcr-situations"
PACKAGE_URL = "https://data.humdata.org/api/3/action/package_show"


@register
class UnhcrSituationsFetcher(Fetcher):
    """The single situations CSV, resolved through the catalogue each time.

    The download URL carries a resource id that changes when UNHCR replaces the
    file, so it is looked up rather than hardcoded - the same reason the DTM
    fetcher lists its dataset instead of naming eight URLs.
    """

    source = "unhcr-odp"
    dataset = "situations"
    variant = ""
    tool = "package_show + csv"
    requires = ()

    def plan(self, sync):
        package = http_get_json(PACKAGE_URL, {"id": DATASET_STUB})
        resources = (package.get("result") or {}).get("resources") or []
        csvs = [r for r in resources
                if str(r.get("format", "")).upper() == "CSV"]
        if not csvs:
            raise ValueError(
                f"{DATASET_STUB}: the catalogue listed {len(resources)} resources "
                "and none of them is a CSV. The dataset may have been renamed or "
                "republished in another format; nothing was pulled.")

        resource = csvs[0]
        yield Call(
            url=resource["url"],
            params={},
            cache_path=Path("unhcr_situations") / "sudan-situation.json",
            loader_dataset="situations",
            context={"resource_id": resource["id"],
                     "resource_url": resource["url"]},
            format="csv",
            paginated=False,
            # The whole series comes back every time, so an empty answer is
            # never "nothing new" - it is a fault.
            narrowed=False,
        )

    def params_record(self):
        return {"tool": "package_show", "dataset_stub": DATASET_STUB,
                "row_filter": "ISO3 of Origin == SDN",
                "note": "national level only; never joined to a Sudanese locality"}
