"""The Model Context Protocol section: what is held, and the button to refresh it.

READ-ONLY APART FROM THE BUTTONS, and for the reason external_data/admin.py
already gives: every row here is written by a loader, so a row hand-edited in the
browser is a row the next refresh silently overwrites.
"""
from django.contrib import admin, messages
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from mcp import views
from mcp.models import ACTIVE, DataSource, PullJob

# What each source is CALLED, as opposed to what its column says. The office says
# "FEWS NET", not "fewsnet".
SOURCE_LABELS = {
    "fewsnet": "FEWS NET", "hdx": "HDX HAPI", "ipc": "IPC",
    "ch": "Cadre Harmonisé", "unhcr": "UNHCR", "acaps": "ACAPS",
    "excel": "Excel workbook", "kobo": "Kobo",
}

# Why a source has no button. Naming the command that DOES load it turns a dead
# end into an instruction.
FILE_BASED = {
    "excel": "file-based — manage.py load_workbooks",
    "kobo": "file-based — manage.py load_hsps",
    "acaps": "CSV export — manage.py load_external acaps_seasonal",
}


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("source_label", "dataset", "country", "last_pulled_at",
                    "high_water_date", "row_count", "job_status", "pull_button")
    list_filter = ("source", "dataset", "iso3")
    search_fields = ("source", "dataset", "variant", "tool", "notes")
    change_list_template = "admin/mcp/datasource/change_list.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path("pull/<int:pk>/", self.admin_site.admin_view(views.pull),
                 name="mcp_pull"),
            path("rebuild/", self.admin_site.admin_view(views.rebuild),
                 name="mcp_rebuild"),
            path("job/<int:job_id>/", self.admin_site.admin_view(views.job_page),
                 name="mcp_job"),
            path("job/<int:job_id>/status/",
                 self.admin_site.admin_view(views.job_status),
                 name="mcp_job_status"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["pulls_since_rebuild"] = views.pulls_since_last_rebuild()
        return super().changelist_view(request, extra_context)

    @admin.display(description="source", ordering="source")
    def source_label(self, obj):
        return SOURCE_LABELS.get(obj.source, obj.source)

    @admin.display(description="country", ordering="iso3")
    def country(self, obj):
        return obj.iso3 or "global"

    @admin.display(description="status")
    def job_status(self, obj):
        """The latest attempt for this row - including the ones that failed.

        This column is why PullJob exists: source_sync records what is HELD and
        says nothing about an attempt that did not land.
        """
        job = (PullJob.objects
               .filter(source=obj.source, dataset=obj.dataset, iso3=obj.iso3,
                       variant=obj.variant)
               .order_by("-requested_at").first())
        if job is None:
            return "—"
        label = "stuck" if job.is_stale else job.status
        detail = f": {job.message[:80]}" if job.status == "failed" else ""
        return format_html('<a href="job/{}/">{}{}</a>', job.id, label, detail)

    @admin.display(description="")
    def pull_button(self, obj):
        fetcher_cls = fetcher_for(obj.source, obj.dataset, obj.variant)
        if fetcher_cls is None:
            return mark_safe(
                '<span style="color:#888">'
                f'{FILE_BASED.get(obj.source, "no API behind this source")}</span>')

        absent = missing_keys(fetcher_cls)
        if absent:
            return format_html(
                '<span style="color:#888" title="Add it to .env and restart the '
                'web container">needs {} in .env</span>', absent[0])

        if PullJob.objects.filter(source=obj.source, status__in=ACTIVE).exists():
            return mark_safe('<span style="color:#888">source busy</span>')

        # A link to a confirmation page, whose form POSTs. The pull itself is
        # never a GET: it changes the database, and an IPC one moves 8-15 MB per
        # analysis, so nothing should be able to start one by prefetching a link.
        return format_html('<a class="button" href="pull/{}/">Pull now</a>', obj.pk)


@admin.register(PullJob)
class PullJobAdmin(admin.ModelAdmin):
    """The attempt log. Never edited; kept as an audit trail."""

    list_display = ("id", "kind", "target", "status", "rows_written",
                    "requested_by", "requested_at", "finished_at")
    list_filter = ("kind", "status", "source")
    search_fields = ("source", "dataset", "iso3", "message")
    date_hierarchy = "requested_at"
    actions = ["reset_stuck_job"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Reset a stuck job (release its source)")
    def reset_stuck_job(self, request, queryset):
        """Free a source held by a job whose process is gone.

        `docker compose up -d --build` mid-pull leaves a row at 'running' with
        nothing behind it, and that row then refuses every future press for its
        source. This is the way out, and it is the same affordance - and the same
        reasoning - as reset_stuck_job in insights/admin.py.

        ONLY ACTIVE JOBS ARE TOUCHED. Rewriting a succeeded job as failed would
        destroy the record of a pull that really happened.
        """
        stuck = queryset.filter(status__in=ACTIVE)
        count = stuck.count()
        for job in stuck:
            job.status = "failed"
            job.finished_at = timezone.now()
            job.message = f"reset by {request.user}"
            job.save(update_fields=["status", "finished_at", "message"])

        if hasattr(request, "_messages") and request._messages is not None:
            self.message_user(
                request,
                f"{count} job(s) reset; their sources can be pulled again."
                if count else "nothing to reset - none of those jobs was active.",
                messages.SUCCESS if count else messages.WARNING,
            )
