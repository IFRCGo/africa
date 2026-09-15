"""HDX HAPI -> IDP localities and refugee stocks.

ONE KEY COVERS TWO SOURCES. `hdx/idps` is obviously HAPI's. `unhcr/refugees` is
too: RefugeeLoader records source='unhcr' because the figures are UNHCR's, but the
tool behind it is HAPI's `get_refugees`. So both need HDX_API_TOKEN and there is
no UNHCR key at all.

PAGINATION IS NOT OPTIONAL HERE. HAPI's `limit` defaults to 100 and Sudan's IDP
series is 5,686 rows. A fetcher that takes the first page would write 100 rows
over the top of 5,686 and report a successful refresh.
"""
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, http_get_json

BASE = "https://hapi.humdata.org/api/v1"

# HAPI's documented maximum for these endpoints. Larger is rejected; smaller
# just means more round trips.
PAGE_SIZE = 1000


def fetch_all_pages(url, params):
    """Follow `offset` until a short page, and return one combined payload.

    The saved file then has the shape the loader expects - a single {"data": [...]}
    - as though it had been one call. The loader has no idea pagination happened,
    which is the point: paging is a property of the API, not of the data.
    """
    rows = []
    offset = 0
    while True:
        page = http_get_json(url, {**params, "limit": PAGE_SIZE, "offset": offset})
        batch = page.get("data", []) if isinstance(page, dict) else (page or [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            # A short page is the last page. An EMPTY first page also stops here
            # and returns empty, which is correct: emptiness is the loader's to
            # judge, and EmptyPayload is where it gets judged.
            return {"data": rows}
        offset += PAGE_SIZE


class _HapiFetcher(Fetcher):
    """Shared: the token, and the paginating call."""

    requires = ("HDX_API_TOKEN",)

    def _params(self, extra):
        return {**extra, "app_identifier": settings.HDX_API_TOKEN,
                "output_format": "json"}


@register
class IdpsFetcher(_HapiFetcher):
    """`get_idps` at admin 2 - the locality series the dashboard draws."""

    source = "hdx"
    dataset = "idps"
    variant = "admin2-overview"
    tool = "get_idps"

    def plan(self, sync):
        # assessment_type='BA' IS PART OF WHAT "admin2-overview" MEANS, not a
        # refinement of it. All 5,686 rows already held are Baseline assessments
        # of the "Armed Clashes in Sudan (Overview)" operation. Asking for admin
        # level 2 alone also returns DTM's ETT (Emergency Tracking) and SA (Site
        # Assessment) rounds, which count different things on different dates -
        # and because the loader's key includes the date and place, those would
        # be ADDED to the series rather than replace anything. A refresh would
        # then silently inflate the IDP figures the dashboard draws.
        yield Call(
            url=f"{BASE}/affected-people/idps",
            params=self._params({"location_code": sync.iso3, "admin_level": 2,
                                 "assessment_type": "BA"}),
            cache_path=Path("hdx_idps") / f"{sync.iso3}-admin2-overview.json",
            loader_dataset="idps",
            context={},
            paginated=True,
        )

    def params_record(self):
        return {"tool": self.tool, "admin_level": 2,
                "assessment_type": "BA", "paginated": True}


@register
class RefugeesFetcher(_HapiFetcher):
    """`get_refugees` - Sudanese refugees, by country of asylum.

    ORIGIN IS PINNED TO SUDAN, and that is not a detail. RefugeeLoader files every
    row it writes under population_group 'sudanese_refugees'. A request without
    origin_location_code returns every refugee in the asylum country, whoever they
    are, and the loader would label them all Sudanese.
    """

    source = "unhcr"
    dataset = "refugees"
    variant = ""
    tool = "get_refugees"

    def plan(self, sync):
        # THREE PINS, ALL ABOUT MEANING. Found by the first real pull, which
        # failed outright with "ON CONFLICT DO UPDATE command cannot affect row
        # a second time".
        #
        # gender/age_range='all': HAPI answers with 611 rows for one country -
        #   every combination of f/m/all and 0-4 ... all - and MovementPattern
        #   has no gender or age column, so the loader collapses all of them
        #   onto one key per year and the upsert collides with itself.
        #
        # population_group='REF': asylum seekers (ASY) would otherwise land
        #   under metric='refugees' beside the refugee rows for the same country
        #   and date. build_refugees() in s06_mcp_layers keeps ONE value per
        #   (country, date) and does not sum, so Chad's 1,330,950 refugees could
        #   be overwritten on the dashboard by its 3,645 asylum seekers.
        #   Asylum seekers are a different quantity; movement_patterns has a
        #   documented 'asylum_seekers' metric for them, and pulling them is a
        #   separate job nobody has asked for yet.
        yield Call(
            url=f"{BASE}/affected-people/refugees",
            params=self._params({"origin_location_code": "SDN",
                                 "asylum_location_code": sync.iso3,
                                 "population_group": "REF",
                                 "gender": "all", "age_range": "all"}),
            cache_path=Path("hdx_refugees") / f"{sync.iso3}.json",
            loader_dataset="refugees",
            context={},
            paginated=True,
        )

    def params_record(self):
        return {"tool": self.tool, "origin_location_code": "SDN",
                "population_group": "REF", "gender": "all", "age_range": "all",
                "paginated": True}
