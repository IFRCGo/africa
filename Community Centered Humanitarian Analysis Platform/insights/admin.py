"""The review queue, and the form for typing one in by hand.

They are the same screen deliberately: once saved, a reviewed AI insight and a
hand-keyed one should be indistinguishable, because they are.

The reviewer reads the quote FIRST - it is the top fieldset, alone - and only
then sees what the model made of it. That ordering is the whole point of the
screen, so do not fold it into a general "details" block.
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from data_track.models import Document
from insights.contract import ContractError
from insights.intake import catalogue_file, catalogue_folder
from insights.loader import load
from insights.models import (
    ExtractionJob, Insight, InsightCoding, InsightFolder, InsightUpload,
)


class InsightCodingInline(admin.TabularInline):
    model = InsightCoding
    extra = 1
    fields = ("dimension", "tag", "tag_raw")
    readonly_fields = ("tag_raw",)


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    inlines = [InsightCodingInline]
    list_display = ("opening", "iso3", "place_name_as_written", "voice_type",
                    "themes", "status", "stated_on", "method")
    list_filter = ("status", "voice_type", "channel", "method", "iso3", "match_method", "job")
    search_fields = ("quote", "quote_translated", "place_name_as_written")
    date_hierarchy = "stated_on"
    actions = ["publish_selected", "reject_selected"]
    readonly_fields = ("quote_sha1", "source_link", "reviewed_by", "reviewed_at", "created_at")
    fieldsets = (
        ("The statement", {
            "fields": ("quote", "quote_language", "quote_translated"),
            "description": "Read this first. Edit only to repair an OCR artefact.",
        }),
        ("What it is", {"fields": ("voice_type", "channel", "stated_on")}),
        ("Where", {"fields": ("iso3", "place_name_as_written", "admin_pcode",
                              "admin_level", "match_method", "lat", "lon")}),
        ("Scale (usually blank)", {"fields": ("people_affected", "severity")}),
        ("Source", {"fields": ("source_link", "document", "page")}),
        ("Provenance", {"fields": ("method", "model_used", "confidence", "job",
                                   "quote_sha1", "created_at")}),
        ("Review", {"fields": ("status", "rejection_reason", "reviewed_by", "reviewed_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("document").prefetch_related("codings")

    @admin.display(description="Statement")
    def opening(self, obj):
        return obj.quote[:90] + ("…" if len(obj.quote) > 90 else "")

    @admin.display(description="Themes")
    def themes(self, obj):
        return ", ".join(f"{c.dimension}:{c.tag}" for c in obj.codings.all()) or "—"

    @admin.display(description="Document")
    def source_link(self, obj):
        if not obj.document_id:
            return "— typed by hand, no source document"
        return format_html("{} (page {})", obj.document.file_name, obj.page or "?")

    @admin.action(description="Publish selected insights")
    def publish_selected(self, request, queryset):
        updated = queryset.update(
            status="published", reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f"{updated} published.", messages.SUCCESS)

    @admin.action(description="Reject selected insights")
    def reject_selected(self, request, queryset):
        updated = queryset.update(
            status="rejected", reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(
            request,
            f"{updated} rejected. Add a reason on each one - a rejected extraction is "
            f"evidence about the model, not rubbish.",
            messages.WARNING,
        )


@admin.register(InsightFolder)
class InsightFolderAdmin(admin.ModelAdmin):
    list_display = ("label", "path", "default_iso3", "reachable", "recursive")
    actions = ["catalogue_selected"]

    @admin.display(boolean=True, description="Reachable")
    def reachable(self, obj):
        return Path(obj.path).is_dir()

    @admin.action(description="Catalogue and queue for extraction")
    def catalogue_selected(self, request, queryset):
        for folder in queryset:
            try:
                job = catalogue_folder(folder)
            except FileNotFoundError as exc:
                self.message_user(request, str(exc), messages.ERROR)
                continue
            self.message_user(
                request,
                f"{folder.label}: {job.documents_total} documents catalogued, job {job.id} queued. "
                f"Run your extraction agent, then use 'Load payloads' on the job.",
                messages.SUCCESS,
            )


@admin.register(InsightUpload)
class InsightUploadAdmin(admin.ModelAdmin):
    """The single-document route. Saving one catalogues it there and then.

    Spec §7 asks for a file field on the intake screen, and this is it: the third
    way in beside a registered folder and the typed form. Cataloguing on save is
    what makes it a route rather than a filing cabinet - an uploaded file nobody
    catalogued would sit in MEDIA_ROOT doing nothing.
    """

    list_display = ("__str__", "iso3", "report_date", "document", "uploaded_at")
    readonly_fields = ("document", "uploaded_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.document_id:
            return
        try:
            document = catalogue_file(
                Path(obj.file.path), iso3=obj.iso3, report_date=obj.report_date)
        except Exception as exc:                      # noqa: BLE001 - surfaced to the user
            self.message_user(
                request, f"Uploaded, but could not be read: {exc}", messages.ERROR)
            return
        obj.document = document
        obj.save(update_fields=["document"])
        self.message_user(
            request,
            f"{document.file_name}: {document.pages} pages catalogued. Run your "
            f"extraction agent, then use 'Load payloads' on a job.",
            messages.SUCCESS,
        )


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = ("id", "folder", "producer", "status", "documents_total",
                    "insights_proposed", "insights_rejected_unverifiable",
                    "insights_skipped_reviewed")
    list_filter = ("status", "producer")
    readonly_fields = ("insights_proposed", "insights_rejected_unverifiable",
                       "insights_skipped_reviewed", "log", "started_at", "finished_at")
    actions = ["load_payloads_for_job"]

    @admin.action(description="Load payloads written by the agent")
    def load_payloads_for_job(self, request, queryset):
        folder = Path(settings.MCP_CACHE_DIR) / "insights"
        files = sorted(folder.glob("*.json"))
        if not files:
            self.message_user(request, f"No payloads in {folder}.", messages.WARNING)
            return

        for job in queryset:
            for path in files:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rel = (payload.get("source") or {}).get("rel_path")
                document = Document.objects.filter(rel_path=rel).first() if rel else None
                if rel and document is None:
                    self.message_user(
                        request, f"{path.name}: no document with rel_path {rel!r}.",
                        messages.ERROR)
                    continue
                try:
                    report = load(payload, document, job=job)
                except ContractError as exc:
                    self.message_user(request, f"{path.name}: {exc}", messages.ERROR)
                    continue
                self.message_user(
                    request,
                    f"{path.name}: {report.written} pending, "
                    f"{report.rejected_unverifiable} unverifiable, "
                    f"{report.skipped_reviewed} already reviewed.",
                    messages.SUCCESS,
                )
            job.status = "loaded"
            job.save(update_fields=["status"])
