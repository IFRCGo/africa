"""FEWS NET -> seasonal calendars and IPC-compatible phases.

The easy source: no key, one call each, and a published API that filters by
country. Both fetchers exist mainly to prove the contract before the keyed and
paginated ones arrive.

ISO2, NOT ISO3. `source_sync` keys countries on ISO3 and FEWS NET's
`country_code` is ISO 3166-1 alpha-2. The map is imported from the seasonal
loader rather than re-typed, because two copies of a country table is how one of
them silently goes stale.
"""
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher
from external_data.loaders.seasonal import ISO3_TO_ISO2

BASE = "https://fdw.fews.net"


def _iso2(iso3):
    """The two-letter code, or KeyError naming the country we cannot place.

    Deliberately not `.get()`: a missing country must stop the pull. Falling back
    to the ISO3 sends a valid-looking request that FEWS NET answers with an empty
    result set, which the loader then reports as an empty payload - a confusing
    way to learn that a country is simply not in the map.
    """
    try:
        return ISO3_TO_ISO2[iso3]
    except KeyError:
        raise KeyError(
            f"{iso3} is not in ISO3_TO_ISO2 (external_data/loaders/seasonal.py). "
            "Add it there rather than guessing a two-letter code here."
        ) from None


@register
class SeasonsFetcher(Fetcher):
    """`get_seasons` - the lean, harvest and rainy bands for one country."""

    source = "fewsnet"
    dataset = "seasonal_calendar"
    variant = ""
    tool = "get_seasons"
    requires = ()

    def plan(self, sync):
        # NEVER NARROWED, and there is nothing to narrow with: FEWS NET's season
        # endpoint has no date filter, and a country's calendar is six bands.
        # A full pull is cheaper than the code it would take to avoid one.
        #
        # page_size 50 matches the MCP tool's own default. One country's seasons
        # are a few dozen rows even counting the historical unit versions the
        # loader discards, so this is one page in practice.
        yield Call(
            url=f"{BASE}/api/season/",
            params={"country_code": _iso2(sync.iso3), "page_size": 50},
            cache_path=Path("fewsnet_seasons") / f"{sync.iso3}.json",
            loader_dataset="seasonal_calendar",
            context={},
        )


@register
class PhasesFetcher(Fetcher):
    """`get_ipc_phases` - FEWS NET's own assessment, where IPC has published none.

    NOTE THE THREE NAMES, which are all different and all correct: the row's
    dataset is 'food_security', its variant is 'fewsnet-phases', and the loader
    that parses the payload is registered under 'fewsnet_phases'. The variant is
    why this fetcher is findable at all, and loader_dataset is why the right
    parser is used.
    """

    source = "fewsnet"
    dataset = "food_security"
    variant = "fewsnet-phases"
    tool = "get_ipc_phases"
    requires = ()

    def plan(self, sync):
        # THE FLOOR IS STILL THE FLOOR. A watermark walked back by the lookback
        # can land before the crisis start - and would if anyone ever backfills
        # older phases - so the later of the two wins. Asking FEWS NET for 2019
        # would pull years of pre-crisis assessments this project does not want.
        since = self.since(sync)
        start = settings.CRISIS_START
        narrowed = False
        if since and since.isoformat() > start:
            start = since.isoformat()
            narrowed = True

        yield Call(
            url=f"{BASE}/api/ipcphase/",
            params={"country_code": _iso2(sync.iso3), "start_date": start},
            cache_path=Path("fewsnet_phases") / f"{sync.iso3}.json",
            loader_dataset="fewsnet_phases",
            context={},
            narrowed=narrowed,
        )
