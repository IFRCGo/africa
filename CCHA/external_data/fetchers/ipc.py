"""IPC and Cadre Harmonise -> food security areas.

THE ONE WITH REAL LOGIC, and three traps that reconnaissance found rather than
review. The listings behind them are saved at api_cache/ipc/analyses-CAF.json and
analyses-TCD.json; the CAF one is this module's test fixture.

1. THE LISTING GOES BACK TO 2013. CAF returns 22 analyses; four are held. A diff
   of "published minus held" queues eighteen pulls of 8-15 MB each on the first
   press - the load profile that closed the IPC connection and took the server
   down for a session. CRISIS_START is the floor.

2. known_ids MEANS HELD, AND THE DIFF NEEDS "CONSIDERED". Analyses a person
   deliberately excluded are in neither list, so they would be pulled straight
   back in; analyses that publish no geometry would fail on every press forever.
   Chad is the proof: its March 2024 displaced-population analysis is inside the
   crisis window, so only skipped_ids keeps it out. note_empty() grows that list.

3. THERE IS NO PERIOD DATE IN THE RESPONSE. The record carries id, title,
   country, year, condition, created and modified - and no analysis period. The
   period is in the title, so it is parsed from there, and a title that yields
   nothing is passed over rather than guessed at.
"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import (Call, Fetcher, crisis_floor, http_get_json,
                                         save_payload)
from external_data.loaders.seasonal import ISO3_TO_ISO2

BASE = "https://api.ipcinfo.org"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Longest-first alternation matters: "September" must win over "Sep", or every
# September analysis parses as one and leaves "tember 2025" behind.
_MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b[\s.,-]*(\d{4})",
    re.IGNORECASE,
)


def period_from_title(title):
    """The first day of the period the title names, or None.

    None is a refusal, not a default. `_period_date` in load_external keeps the
    same rule and states the reason: a wrong period silently files an analysis
    under the wrong month, which is worse than a load that stops.
    """
    match = _MONTH_YEAR.search(title or "")
    if not match:
        return None
    return date(int(match.group(2)), MONTHS[match.group(1).lower()], 1)


@register
class FoodSecurityFetcher(Fetcher):
    """`list_analyses`, then `get_areas_by_analysis` for each one not considered.

    Registered twice - see CadreHarmoniseFetcher at the bottom of this file.
    """

    source = "ipc"
    dataset = "food_security"
    variant = ""
    tool = "get_areas_by_analysis"
    requires = ("IPC_API_KEY",)

    def plan(self, sync):
        iso2 = ISO3_TO_ISO2.get(sync.iso3)
        if not iso2:
            raise KeyError(
                f"{sync.iso3} is not in ISO3_TO_ISO2 (external_data/loaders/"
                "seasonal.py). IPC takes a two-letter country code."
            )

        analyses = http_get_json(
            f"{BASE}/analyses",
            {"country": iso2, "type": "A", "format": "json",
             "key": settings.IPC_API_KEY},
        )
        # Saved as evidence of what was OFFERED, which is a different fact from
        # what was taken, and the only record of why an analysis was passed over.
        save_payload(Path("ipc") / f"analyses-{sync.iso3}.json", analyses)

        considered = set(sync.known_ids or [])
        considered |= {s.get("id") for s in (sync.skipped_ids or [])}
        floor = crisis_floor()

        for record in analyses:
            analysis_id = str(record.get("id") or "")
            if not analysis_id or analysis_id in considered:
                continue

            title = record.get("title") or ""
            period = period_from_title(title)
            if period is None:
                # Every analysis inside the crisis window has a parseable title;
                # the ones that do not are all from 2013-2014. Passing them over
                # quietly is right, because the floor would drop them anyway.
                continue
            if period < floor:
                continue

            yield Call(
                url=f"{BASE}/areas/{analysis_id}/C",
                params={"format": "geojson", "key": settings.IPC_API_KEY},
                # The existing naming, unchanged: every file already in
                # api_cache/ipc/ is <ISO3>-<id>-C.geojson.
                cache_path=Path("ipc") / f"{sync.iso3}-{analysis_id}-C.geojson",
                loader_dataset="food_security",
                context={"analysis_id": analysis_id, "analysis_title": title,
                         "period_date": period},
            )

    def note_empty(self, sync, call):
        """Record that this analysis published nothing, so it is asked once only.

        Called by the runner when a Call trips EmptyPayload. The title is kept as
        the reason because "87143421" tells a later reader nothing and
        "Analysis Update CF May 2026" tells them what to go and look at.
        """
        analysis_id = call.context.get("analysis_id")
        if not analysis_id:
            return
        existing = sync.skipped_ids or []
        if analysis_id in {s.get("id") for s in existing}:
            return
        title = call.context.get("analysis_title") or "no title"
        sync.skipped_ids = existing + [{
            "id": analysis_id,
            "reason": f"returned no areas when pulled: {title}",
        }]
        sync.save(update_fields=["skipped_ids"])

    def params_record(self):
        return {"tool": self.tool, "listing": "list_analyses", "period": "C",
                "floor": settings.CRISIS_START}


# Chad's analyses are Cadre Harmonise, published through the same IPC API. The
# loader already varies `source` by country (food_security.source_for); the fetch
# is identical, so the same class is registered under both names rather than
# copied.
@register
class CadreHarmoniseFetcher(FoodSecurityFetcher):
    source = "ch"
