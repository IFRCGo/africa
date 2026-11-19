"""ACAPS -> the Seasonal Events Calendar, straight from api.acaps.org.

THE ONLY ROUTE IN. The CSV export this replaced was removed on 2026-11-19;
`loaders/acaps_seasonal.py` parses what this fetcher brings back.

ONE CALL PER COUNTRY ROW, filtered by `iso`. A row with no country asks for
everything and lets the loader keep the nine countries this platform covers.
Either way the answer is paged with a complete `next` URL, which is followed
verbatim - Kobo's pager.

NEVER NARROWED. The calendar has no date to filter on: an event is a set of
months, and ACAPS revises a record in place. Every pull asks for the whole
country, so an empty answer is always a fault and never "nothing new".

The token travels only in the Authorization header, and ACAPS_TOKEN is in
SECRET_SETTINGS, so it is redacted from any error that reaches a job log.
"""
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher

ENDPOINT = "seasonal-events-calendar/seasonal-calendar/"


@register
class SeasonalCalendarFetcher(Fetcher):
    """`list_seasonal_calendar` - ACAPS's events, with crop, regions and source."""

    source = "acaps"
    dataset = "seasonal_calendar"
    variant = "acaps-events"     # matches AcapsSeasonalLoader.sync_key
    tool = "acaps list_seasonal_calendar"
    requires = ("ACAPS_TOKEN",)

    def plan(self, sync):
        params = {"iso": sync.iso3} if sync.iso3 else {}
        yield Call(
            url=f"{settings.ACAPS_URL}/{ENDPOINT}",
            params=params,
            cache_path=Path("acaps_seasonal") / f"{sync.iso3 or 'all'}.json",
            loader_dataset="acaps_seasonal",
            headers={"Authorization": f"Token {settings.ACAPS_TOKEN}"},
            paginated=True,
            pager="next_url",
        )
