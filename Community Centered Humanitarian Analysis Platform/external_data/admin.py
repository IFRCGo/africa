"""The external-source tables at /admin/, so they can be browsed without SQL.

Alongside what data_track and boundaries register. Without this file the admin
showed ten of the project's sixteen tables: the seven read out of the UNHCR
PDFs and the three that make up the map. The six below - the ones pulled from IPC,
FEWS NET, ACAPS, HDX, UNHCR and Kobo - existed in the database and were invisible
from the browser.

Read-only, for the same reason boundaries is. Every one of these tables is written
by a loader (`seed_external`, `load_hsps`, `load_workbooks`, `loaders/base`), so a
row hand-edited here is a row the next refresh silently overwrites. The way to
change a phase or a crossing's coordinates is to fix the source and re-run the
loader, not to leave the database disagreeing with the thing that fills it.
"""
from django.contrib import admin

from .models import (
    BorderCrossing,
    FoodSecurityArea,
    HumanitarianServicePoint,
    MovementPattern,
    SeasonalCalendar,
    SourceSync,
)


class ReadOnly(admin.ModelAdmin):
    """Look and search, but do not add or edit. See the note at the top."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SourceSync)
class SourceSyncAdmin(ReadOnly):
    """The freshness table. `notes` is where a no-op refresh explains itself, so
    it is worth having in the search box even though it is not a column."""

    list_display = ("source", "dataset", "iso3", "variant", "high_water_date",
                    "last_pulled_at", "row_count")
    list_filter = ("source", "dataset", "iso3")
    search_fields = ("source", "dataset", "variant", "tool", "notes")


@admin.register(SeasonalCalendar)
class SeasonalCalendarAdmin(ReadOnly):
    # source_org rather than source in the last column: `source` says which
    # publisher we pulled from, source_org says whose assessment it actually is.
    list_display = ("iso3", "label", "season_type", "event_type",
                    "start_month", "end_month", "source", "source_org")
    list_filter = ("iso3", "source", "season_type", "event_type", "purpose")
    search_fields = ("label", "event", "country_name", "description", "source_ref")


@admin.register(FoodSecurityArea)
class FoodSecurityAreaAdmin(ReadOnly):
    list_display = ("iso3", "area_title", "phase", "phase3plus_pct",
                    "period_date", "period_type", "source", "analysis_title")
    # phase is 1-5 and period_type is one of three values, so both make honest
    # sidebar filters. analysis_id and area_id do not - they are keys, not
    # categories, and would render a sidebar thousands of links long.
    list_filter = ("source", "iso3", "phase", "period_type", "condition")
    search_fields = ("area_title", "analysis_title", "area_id", "admin_pcode")
    date_hierarchy = "period_date"


@admin.register(MovementPattern)
class MovementPatternAdmin(ReadOnly):
    list_display = ("date", "iso3", "metric", "place_name", "admin_pcode",
                    "value", "unit", "source")
    list_filter = ("metric", "iso3", "source", "unit", "admin_level")
    search_fields = ("place_name", "admin_pcode", "source_dataset", "population_group")
    date_hierarchy = "date"


@admin.register(BorderCrossing)
class BorderCrossingAdmin(ReadOnly):
    list_display = ("name", "country", "iso3", "corridor", "return_corridor",
                    "lat", "lon")
    list_filter = ("country", "corridor")
    search_fields = ("name",)


@admin.register(HumanitarianServicePoint)
class HumanitarianServicePointAdmin(ReadOnly):
    # location_name and match_method sit together on purpose: a row whose
    # match_method is 'unmatched' has no p-code and no coordinates, and seeing
    # the two columns side by side is how you spot which districts never placed.
    list_display = ("date_reported", "country", "service", "location_name",
                    "scope", "match_method", "admin_pcode")
    list_filter = ("iso3", "service", "scope", "match_method")
    search_fields = ("location_name", "service", "admin_pcode", "source_file")
    date_hierarchy = "date_reported"
