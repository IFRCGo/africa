"""IFRC Montandon -> hazard events, their severity and their impacts.

THREE CALLS PER COUNTRY, AND THE ORDER IS LOAD-BEARING:

    events    the what, where and when   -> hazard_events rows
    hazards   the severity               -> applied onto those rows by corr_id
    impacts   the people                 -> hazard_impacts rows, then
                                            significance is classified

Severity has to land on rows that already exist, and `significance` needs both
severity and impacts to have arrived. plan() is a generator and the runner
consumes it with a plain for-loop, which is what makes the order safe.

NOT AN OPEN API. A direct request to the staging host answers
{"detail": "Not authenticated"}; it answers the `monty` MCP server only because
that server holds IFRC_API_TOKEN. This project needs the same token in .env.

COUNTRY FILTERING NEEDS POST. GET /search offers bbox and nothing else, so the
country filter is a CQL2 expression and every call here is a POST.

`monty:country_codes` IS NOT TIGHT. A Sudan-filtered query returns
"Flood - Kemashi, Benshangul-Gumaz, Ethiopia", and the Egypt rows include
"Dense Fog - Negev, Israel". Those are kept: the filter is Montandon's own
judgement about which countries an event concerns, and overriding it here would
be this project second-guessing the registry from a distance. `title` carries
the published wording, so a reader can see exactly what happened.

WHY THESE THREE COLLECTION FAMILIES AND NOT THE OTHERS. EM-DAT, GLIDE, IFRC-GO
and DesInventar publish the whole country as their geometry, which on a map
lights Sudan entire and defeats the point of a layer whose job is to say WHERE.
GDACS, PDC and IDMC-IDU publish located points - IDMC-IDU down to "North Darfur
(Tawila Locality)".
"""
from datetime import date
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, crisis_floor

EVENT_COLLECTIONS = ["gdacs-events", "pdc-events", "idmc-idu-events"]
# idmc-idu-hazards DOES NOT EXIST. IDMC-IDU rows therefore carry no severity at
# all, which the popup handles by omitting the section rather than printing
# "unknown" - and which hazards.is_detection must never read as "no alert".
HAZARD_COLLECTIONS = ["gdacs-hazards", "pdc-hazards"]
IMPACT_COLLECTIONS = ["gdacs-impacts", "pdc-impacts", "idmc-idu-impacts"]

# Montandon's documented maximum for /search.
PAGE_SIZE = 500

# What every call needs regardless of kind. `geometry` is in because the point
# is the whole value of these three sources; `properties.description` is out
# because one item carries kilobytes of Word-exported HTML.
BASE_INCLUDE = ["id", "collection", "geometry", "bbox",
                "properties.title", "properties.datetime",
                "properties.start_datetime", "properties.end_datetime",
                "properties.monty:hazard_codes", "properties.monty:country_codes",
                "properties.monty:corr_id"]
BASE_EXCLUDE = ["properties.description", "assets", "properties.keywords",
                "stac_extensions"]


@register
class MontandonFetcher(Fetcher):
    """One press: events, then severity, then impacts, for one country."""

    source = "montandon"
    dataset = "hazard_events"
    variant = ""
    tool = "monty__search_items"
    requires = ("IFRC_API_TOKEN",)

    def since(self, sync):
        """None, always. The window is fixed and never narrows.

        The office asked for 15 Apr 2023 to today on every pull, so the
        inherited 90-day-lookback behaviour is switched off here. The
        consequence is deliberate: `narrowed` stays False, so under the loaders'
        "empty is a failure" guarantee a country that returns nothing fails
        loudly instead of being quietly recorded as up to date.
        """
        return None

    def _window(self):
        return (f"{crisis_floor().isoformat()}T00:00:00Z"
                f"/{date.today().isoformat()}T23:59:59Z")

    def _headers(self):
        """The token as a header, not a query parameter.

        HAPI's token travels in the URL, which is half the reason redact()
        exists - it turns up in requests' own exception messages. A header keeps
        it out of the URL in the first place. IFRC_API_TOKEN is in
        SECRET_SETTINGS regardless, because belt and braces costs nothing.
        """
        return {"Authorization": f"Bearer {settings.IFRC_API_TOKEN}"}

    def _call(self, sync, collections, extra_include, kind, loader_dataset):
        return Call(
            url=f"{settings.MONTANDON_STAC_URL}/search",
            params={},
            body={
                "collections": collections,
                "datetime": self._window(),
                "limit": PAGE_SIZE,
                "filter": {"op": "a_contains",
                           "args": [{"property": "monty:country_codes"}, [sync.iso3]]},
                "filter-lang": "cql2-json",
                "fields": {"include": BASE_INCLUDE + extra_include,
                           "exclude": BASE_EXCLUDE},
            },
            headers=self._headers(),
            cache_path=Path("montandon") / f"{sync.iso3}-{kind}.json",
            loader_dataset=loader_dataset,
            context={"iso3": sync.iso3},
            method="POST",
            paginated=True,
            narrowed=False,
        )

    def plan(self, sync):
        yield self._call(sync, EVENT_COLLECTIONS, [], "events", "montandon_events")
        yield self._call(sync, HAZARD_COLLECTIONS, ["properties.monty:hazard_detail"],
                         "hazards", "montandon_severity")
        yield self._call(sync, IMPACT_COLLECTIONS, ["properties.monty:impact_detail"],
                         "impacts", "montandon_impacts")

    def params_record(self):
        return {"tool": self.tool, "window_start": crisis_floor().isoformat(),
                "window_end": "today", "collections": EVENT_COLLECTIONS,
                "paginated": True, "page_size": PAGE_SIZE}
