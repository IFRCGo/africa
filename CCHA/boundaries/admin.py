"""The boundary tables at /admin/, so they can be browsed without SQL.

Read-only on purpose. These rows come from files, and the way to change them is
to fix the file and run `manage.py load_boundaries` again - not to hand-edit a
polygon's name and leave the database disagreeing with its own source.
"""
from django.contrib import admin

from .models import AdminArea, BoundarySource, MapFeature


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BoundarySource)
class BoundarySourceAdmin(ReadOnly):
    list_display = ("source_label", "publisher", "schema", "valid_on", "feature_count",
                    "ingested_at")
    list_filter = ("publisher", "schema")
    search_fields = ("path", "source_label")


@admin.register(AdminArea)
class AdminAreaAdmin(ReadOnly):
    list_display = ("pcode", "name", "level", "iso3", "parent_pcode", "area_sqkm")
    list_filter = ("iso3", "level", "kind")
    search_fields = ("pcode", "name", "ref_name", "name_path")


@admin.register(MapFeature)
class MapFeatureAdmin(ReadOnly):
    list_display = ("layer", "name", "kind", "iso3")
    list_filter = ("layer", "kind")
    search_fields = ("name",)
