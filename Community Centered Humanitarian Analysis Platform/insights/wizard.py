"""The guided route from documents to published insights.

FOUR STEPS, ONE JOB. Every step reads its state off one ExtractionJob row:
"collecting" is a batch whose files are still arriving, "queued" is ready to
extract, "running" is extracting, "loaded" is ready to review. Nothing is kept
in the session, so closing the tab loses nothing and reopening the wizard
rejoins the batch wherever it got to.

WHY THESE ARE NOT IN insights/urls.py. That file is the public read API. These
are mounted inside the admin site (DocumentsToInsightsAdmin.get_urls) and
wrapped in admin_view(), so they carry the same staff-only check and login
redirect as every other admin page - exactly as place_options and
folder_browse already are.
"""
import hashlib
import subprocess
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib import messages
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from data_track.models import Document
from insights import review
from insights.extractors import get_extractor
from insights.forms import InsightInlineEditForm
from insights.intake import SUFFIXES, catalogue_file
from insights.models import ExtractionJob, Insight, InsightCoding, InsightUpload

RECENT_JOBS = 20
LOG_TAIL_BYTES = 4096

CodingFormSet = inlineformset_factory(
    Insight, InsightCoding, fields=("dimension", "tag"), extra=1, can_delete=True)


def page(request, **extra):
    """The context every wizard page needs.

    each_context() is what supplies the admin's header, breadcrumbs, site title
    and the user menu. admin_view() does NOT add it - it wraps a view in the
    permission check and the login redirect and nothing else - so a page that
    forgets this renders as an unstyled orphan with no way back to the admin.
    """
    return {**django_admin.site.each_context(request), **extra}


def job_list(request):
    """Recent batches and how far each one got."""
    return render(request, "insights/wizard_jobs.html", page(
        request,
        wizard_step=0,
        jobs=ExtractionJob.objects.order_by("-id")[:RECENT_JOBS],
    ))


@require_POST
def batch_open(request):
    """Start a batch. One job for the whole drop, not one per file."""
    job = ExtractionJob.objects.create(
        status="collecting", producer="external",
        label=(request.POST.get("label") or "").strip() or None,
    )
    return JsonResponse({"job_id": job.id})


@require_POST
def batch_file(request, job_id):
    """Take exactly one file, catalogue it, attach it, and say what happened.

    ONE FILE PER REQUEST, deliberately. Django 5.0's
    DATA_UPLOAD_MAX_NUMBER_FILES defaults to 100, so a folder of 300 reports
    posted in one go is rejected outright - and a single failure inside a
    300-file request loses the other 299 results. This way a corrupt PDF is one
    row with a reason on it.
    """
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "No file was sent."}, status=400)

    # Client-controlled, and it stays a label: joined onto a directory, a value
    # of "../../etc/passwd" is a traversal. Nothing needs it on disk, because
    # duplicates are caught on the content's sha1 just below.
    label = (request.POST.get("relative_path") or "").strip() or upload.name

    suffix = Path(upload.name).suffix.lower()
    if suffix not in SUFFIXES:
        return JsonResponse({
            "name": label, "outcome": "skipped",
            "message": f"{suffix or 'no extension'} is not a PDF or Word document.",
        })

    # HASHED BEFORE IT IS SAVED, AND MATCHED ON THE HASH. catalogue_file
    # de-duplicates on rel_path, which for an upload is
    # "media/<sha1[:12]>-<stored name>" - and the STORED name is whatever
    # Django's storage settled on, which uniquifies a collision to
    # "report_AbCdEf.pdf". So the same report sent twice, or sent under two
    # names, lands on two rel_paths and is catalogued twice. Matching on
    # Document.sha1 is what actually answers "is this file already in the
    # database". File.chunks() seeks to 0 first, so the upload is still
    # readable afterwards.
    digest = hashlib.sha1()
    for chunk in upload.chunks():
        digest.update(chunk)
    fingerprint = digest.hexdigest()

    existing = Document.objects.filter(sha1=fingerprint).first()
    if existing is not None:
        # Nothing is written: a second copy on disk of a file already
        # catalogued is pure cost. The document is attached to this batch so
        # it is extracted with the rest of it.
        job.documents.add(existing)
        return JsonResponse({
            "name": label, "outcome": "duplicate", "pages": existing.pages,
            "document_id": existing.id,
            "message": "Already catalogued - the same file is in the database.",
        })

    row = InsightUpload.objects.create(file=upload, label=label)
    stored = Path(row.file.path)

    try:
        document = catalogue_file(stored)
    except Exception as exc:                      # noqa: BLE001 - reported per file
        # An unreadable file is an expected input here, not an exceptional one:
        # a password-protected or truncated PDF in a folder of 200 must not take
        # the other 199 down. Type and message only, never the repr.
        row.delete()
        stored.unlink(missing_ok=True)
        return JsonResponse({
            "name": label, "outcome": "failed",
            "message": f"{type(exc).__name__}: {exc}",
        })

    row.document = document
    row.save(update_fields=["document"])
    job.documents.add(document)

    return JsonResponse({
        "name": label, "outcome": "catalogued", "pages": document.pages,
        "document_id": document.id, "message": "",
    })


@require_POST
def batch_ready(request, job_id):
    """Close the batch and queue it for extraction."""
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    job.documents_total = job.documents.count()
    job.status = "queued"
    job.save(update_fields=["documents_total", "status"])
    return JsonResponse({"documents_total": job.documents_total})


def start(request):
    """Step 1: the two pickers. No job exists until a file is actually sent."""
    return render(request, "insights/wizard_intake.html", page(request, wizard_step=1))


def job_step(request, job_id):
    """Whichever step this job's status puts it at.

    Read off the job rather than kept in the session, so closing the tab loses
    nothing: the same URL reopens the batch where it actually is.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status == "collecting":
        return render(request, "insights/wizard_intake.html",
                      page(request, job=job, wizard_step=1))
    if job.status in ("queued", "running", "failed"):
        return render(request, "insights/wizard_extract.html",
                      page(request, job=job, wizard_step=3))
    return render(request, "insights/wizard_review.html",
                  page(request, job=job, wizard_step=4, insights=_job_insights(job)))


def _job_insights(job):
    """This job's statements, grouped the way they are read: by document, by page."""
    return (Insight.objects.filter(job=job)
            .select_related("document")
            .prefetch_related("codings")
            .order_by("document__file_name", "page", "id"))


@require_POST
def decide(request, job_id):
    """Publish or reject the selected statements.

    SCOPED TO THIS JOB. The ids come from a form, so they are the client's to
    choose; filtering on the job as well means a tampered form cannot publish
    somebody else's pending review queue.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    chosen = Insight.objects.filter(job=job, id__in=request.POST.getlist("selected"))

    if request.POST.get("decision") == "publish":
        moved = review.publish(chosen, request.user)
        messages.success(request, f"{moved} published.")
    else:
        moved = review.reject(chosen, request.user)
        messages.warning(
            request,
            f"{moved} rejected. Add a reason on each one - a rejected extraction "
            f"is evidence about the model, not rubbish.")

    return redirect(reverse("admin:insights_wizard_job", args=[job.id]))


def edit(request, insight_id):
    """One statement's editor, and the save behind it.

    An inlineformset_factory rather than the admin's TabularInline: that class
    only exists inside an admin change view and leans on admin's own inlines.js.
    Outside it, empty_form plus a few lines of JavaScript is the whole feature.

    The form is InsightPlaceForm's subclass, so the rules that keep a place
    derived rather than typed are inherited rather than restated - including the
    one that leaves an untouched location exactly as the extractor wrote it.
    """
    insight = get_object_or_404(Insight, id=insight_id)
    prefix = f"insight-{insight.id}"
    coding_prefix = f"{prefix}-codings"

    if request.method == "POST":
        form = InsightInlineEditForm(request.POST, instance=insight, prefix=prefix)
        formset = CodingFormSet(request.POST, instance=insight, prefix=coding_prefix)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            insight.refresh_from_db()
            return JsonResponse({
                "saved": True,
                "row": render_to_string(
                    "insights/_review_row.html", {"insight": insight}, request=request),
            })
        return JsonResponse({
            "saved": False,
            "panel": render_to_string(
                "insights/_edit_panel.html",
                {"insight": insight, "form": form, "formset": formset}, request=request),
        })

    return render(request, "insights/_edit_panel.html", {
        "insight": insight,
        "form": InsightInlineEditForm(instance=insight, prefix=prefix),
        "formset": CodingFormSet(instance=insight, prefix=coding_prefix),
    })


def log_path(job):
    """Where the detached extraction writes its output."""
    return Path(settings.MCP_CACHE_DIR) / "insights" / f"job-{job.id}.log"


def _tail(path):
    """The last few KB of a file, or "" if there is no file yet.

    Seeked, not read: a long run's log grows without bound and this endpoint is
    polled every two seconds. The first line of the block is dropped when the
    file is longer than the window, because it is half a line.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            block = handle.read()
    except OSError:
        return ""
    text = block.decode("utf-8", errors="replace")
    return text if size <= LOG_TAIL_BYTES else text.split("\n", 1)[-1]


def _last_change(path):
    """When the extraction last wrote anything, as an ISO timestamp.

    THE LOG FILE'S MTIME, not a column on the job. ExtractionJob has no
    updated_at, and adding one with auto_now=True would not work: the command
    saves with update_fields=["documents_done"] and update_fields=["log"], and
    an auto_now field is only touched when it is among the fields listed. The
    child writes to this file as each document finishes, which is exactly the
    signal the stall warning needs, and it costs no model change.
    """
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=dt_timezone.utc).isoformat()


def progress(request, job_id):
    """Everything the extract step redraws itself from."""
    job = get_object_or_404(ExtractionJob, id=job_id)
    path = log_path(job)
    return JsonResponse({
        "status": job.status,
        "done": job.documents_done,
        "total": job.documents_total,
        "proposed": job.insights_proposed,
        "unverifiable": job.insights_rejected_unverifiable,
        "skipped_reviewed": job.insights_skipped_reviewed,
        "log_tail": _tail(path),
        "last_change": _last_change(path),
    })


@require_POST
def extract(request, job_id):
    """Launch the extraction as a detached background process.

    Detached (start_new_session=True) so a gunicorn worker recycling mid-run
    does not kill a paid-for extraction, and so closing this tab does not
    either. docker-compose.yml's web service sets init: true for the other half
    of that: an orphaned child exiting 3 or 4 reparents to gunicorn's own
    Arbiter.reap_workers() and can halt the whole web server.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)

    if job.status == "running":
        # A double click must not run two extractions of the same job - the
        # second pass would double every insight the first one wrote, since the
        # loader's conflict gate only protects rows a reviewer has touched.
        return JsonResponse({
            "started": False,
            "message": "This batch is already extracting.",
        })

    try:
        get_extractor()
    except ValueError as exc:
        # The normal state for the route CLAUDE.md documents first: extraction
        # run by an agent on the host, writing payloads into mcp_cache/insights/
        # for "Load payloads" to pick up. Not an error, so it is not reported
        # as one.
        return JsonResponse({
            "started": False,
            "message": (
                f"No in-container model is configured ({exc}). Run the extraction "
                f"with an agent on the host, then use “Load payloads written "
                f"by the agent” on this job."
            ),
        })

    path = log_path(job)
    # Only exists once something has written a payload into it, so on a fresh
    # setup the very first click here would otherwise fail opening the log.
    path.parent.mkdir(parents=True, exist_ok=True)

    # Set to running and saved BEFORE launching: this request returns at once,
    # and the child is what moves the job on to "loaded" - or leaves it at
    # "running" if it dies, which is visible either way.
    job.status = "running"
    job.save(update_fields=["status"])

    with open(path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "manage.py", "extract_insights", "--job", str(job.id)],
            cwd=settings.BASE_DIR,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    return JsonResponse({"started": True, "message": "Extraction started."})
