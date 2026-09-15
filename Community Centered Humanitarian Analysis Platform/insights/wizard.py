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
from pathlib import Path

from django.contrib import admin as django_admin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from data_track.models import Document
from insights.intake import SUFFIXES, catalogue_file
from insights.models import ExtractionJob, InsightUpload

RECENT_JOBS = 20


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
                  page(request, job=job, wizard_step=4))
