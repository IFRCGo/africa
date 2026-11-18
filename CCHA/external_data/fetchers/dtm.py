"""IOM DTM Sudan snapshots, from HDX's CKAN catalogue.

NOT HAPI. The other HDX fetcher in this package talks to hapi.humdata.org,
which serves tidy JSON. This one talks to the CKAN catalogue that serves the
files themselves, and the files are workbooks - which is what Call.format
exists for.

NO KEY AND NO CUSTOM USER AGENT. Verified from inside the container on
2026-09-25: requests' default UA gets 200. (WebFetch gets 403 from the same
host, which is its own fetcher being blocked and not a fact about this one.)
"""
from pathlib import Path

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, http_get_json

DATASET_STUB = "sudan-displacement-situation-countrywide-idps-iom-dtm"
PACKAGE_URL = "https://data.humdata.org/api/3/action/package_show"


@register
class DtmSnapshotFetcher(Fetcher):
    """One Call per 'Displacement and Return Snapshot' not already held."""

    source = "dtm"
    dataset = "displacement_snapshot"
    variant = ""
    tool = "package_show + xlsx"
    requires = ()

    def plan(self, sync):
        package = http_get_json(PACKAGE_URL, {"id": DATASET_STUB})
        resources = (package.get("result") or {}).get("resources") or []

        # THE ONE PLACE THE OLDER FAMILY IS EXCLUDED. Twenty-three "Countrywide
        # Mobility Update" workbooks share this dataset and have a different
        # layout; the snapshot family is identified by its filename. The filter
        # is repeated in params_record() so a reader of the admin row can see
        # what was and was not asked for.
        snapshots = [r for r in resources
                     if str(r.get("format", "")).upper() == "XLSX"
                     and "snapshot" in str(r.get("url", "")).lower()]

        # A FIRST PULL THAT FINDS NOTHING IS A FAULT, NOT "UP TO DATE". If HDX
        # renames the dataset or the filename convention changes, zero
        # snapshots is what it looks like - and reporting that as success would
        # leave the table empty and the row claiming it was refreshed.
        if not snapshots and not sync.known_ids:
            raise ValueError(
                f"{DATASET_STUB}: the catalogue listed {len(resources)} resources "
                "and none of them is a snapshot workbook. The dataset may have "
                "been renamed or the filename convention changed; nothing was "
                "pulled.")

        held = set(sync.known_ids or [])
        for resource in snapshots:
            if resource["id"] in held:
                continue
            yield Call(
                url=resource["url"],
                params={},
                cache_path=Path("dtm_snapshots") / f"{sync.iso3}-{resource['id']}.json",
                loader_dataset="displacement_snapshot",
                # The workbook does not name the resource it came from, and
                # known_ids is keyed on exactly that.
                context={"resource_id": resource["id"],
                         "resource_url": resource["url"]},
                format="xlsx",
                paginated=False,
                # NEVER narrowed, even though `held` narrows which resources
                # are asked for. `narrowed` means "an empty answer here is
                # legitimately 'nothing since <date>'", which is true of a
                # date-filtered API request and false of this one: every Call
                # below is for a resource the catalogue JUST said exists, so a
                # payload that parses to nothing is a fault and must reach
                # EmptyPayload rather than being logged as "nothing new" and
                # having its id quietly recorded as held.
                narrowed=False,
            )

    def params_record(self):
        return {"tool": "package_show", "dataset_stub": DATASET_STUB,
                "resource_filter": "format == XLSX and 'snapshot' in url",
                "watermark": "known_ids (resource ids), not a date"}
