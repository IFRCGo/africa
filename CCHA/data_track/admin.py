"""Registers every table with the Django admin site at /admin/.

The admin is a ready-made web interface for looking at, searching and editing
the database. Each `list_display` below decides which columns you see, each
`list_filter` adds a sidebar filter, and `search_fields` adds a search box.

This is the easiest way to audit a number: search the figure, open the row,
read its `snippet` and jump to the document it came from.
"""
from django.contrib import admin

from .models import (
    Document,
    DocumentText,
    Event,
    Location,
    MovementFlow,
    NarrativeTag,
    PopulationFigure,
)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "file_name", "family", "country_focus", "report_date", "pages")
    list_filter = ("family", "country_focus", "source_collection", "date_source")
    search_fields = ("file_name", "rel_path")
    date_hierarchy = "report_date"     # adds year/month/day drill-down links


@admin.register(DocumentText)
class DocumentTextAdmin(admin.ModelAdmin):
    list_display = ("document", "page")
    search_fields = ("text",)          # full-text search across the whole corpus
    # There are hundreds of thousands of pages, so pick the document by id
    # instead of loading a giant drop-down list.
    raw_id_fields = ("document",)


@admin.register(PopulationFigure)
class PopulationFigureAdmin(admin.ModelAdmin):
    list_display = ("report_date", "country", "metric", "value", "method", "confidence")
    list_filter = ("metric", "country", "confidence", "method")
    search_fields = ("snippet",)
    date_hierarchy = "report_date"
    raw_id_fields = ("document",)


@admin.register(MovementFlow)
class MovementFlowAdmin(admin.ModelAdmin):
    list_display = ("report_date", "corridor", "origin", "destination", "flow_type", "value")
    list_filter = ("corridor", "flow_type")
    date_hierarchy = "report_date"
    raw_id_fields = ("document",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("event_date", "title", "category", "location", "severity", "source")
    list_filter = ("category", "source", "severity")
    search_fields = ("title", "description")
    date_hierarchy = "event_date"
    raw_id_fields = ("document",)


@admin.register(NarrativeTag)
class NarrativeTagAdmin(admin.ModelAdmin):
    list_display = ("report_date", "dimension", "tag", "country")
    list_filter = ("dimension", "tag", "country")
    search_fields = ("snippet",)
    date_hierarchy = "report_date"
    raw_id_fields = ("document",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "kind", "lat", "lon")
    list_filter = ("kind", "country")
    search_fields = ("name", "aliases")


# Titles in the browser tab, on the login page and above the table list.
# These deliberately mirror the dashboard's own heading (the <h1> in
# dashboard/templates/dashboard/index.html) so the admin and the map read as one product.
# index_title is word-for-word the server name registered in pgAdmin
# (docker/pgadmin_servers.json), so the same database is called the same thing
# whether you open it here or there.
admin.site.site_header = "Sudan & Neighbouring countries - Community Centered Humanitarian Analysis"
admin.site.site_title = "Sudan & Neighbouring Countries"
admin.site.index_title = "Sudan and Neighbouring countries population movement"
