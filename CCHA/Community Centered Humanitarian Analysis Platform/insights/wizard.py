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
from django.core.files.base import ContentFile
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from data_track.models import Document
from insights import retention, review, weblink
from insights.extractors import get_extractor
from insights.forms import InsightInlineEditForm
from insights.intake import SUFFIXES, catalogue_file
from insights.models import ExtractionJob, Insight, InsightCoding, InsightUpload

RECENT_JOBS = 20
LOG_TAIL_BYTES = 4096

CodingFormSet = inlineformset_factory(
    Insight, InsightCoding, fields=("dimension", "tag"), extra=1, can_delete=True)


STEPS = (
    (1, "Bring documents in"),
    (2, "Read these documents"),
    (3, "Extract"),
    (4, "Review and publish"),
)

# The statuses step 2 owns: files are in, and the reading has not yet been
# signed off. Named because four call sites test the same membership.
READ_STATUSES = ("collected", "converting", "converted", "convert_failed")


def step_links(job, current):
    """The four steps, each with the URL that reaches it right now - or None.

    WHERE A STEP LEADS IS THE JOB'S STATUS, NOT A ROUTE OF ITS OWN. job_step
    serves whichever page the status puts the batch at, so a button for step 3
    on a batch that has already loaded would not go back to the extract page -
    it would bounce straight to review. A step that cannot honestly be reached
    from here therefore gets no URL and is rendered inert, rather than a link
    that lies about where it goes.

    Step 2 is a page of its own: Docling converts each document to per-page
    markdown there, and the text it produces is what the model reads and what
    verify.quote_is_verbatim checks a quote against. It leads somewhere only
    while the batch is still at that stage - once a batch is extracting, going
    "back" to the read step would offer to replace the text under insights
    already being written against it. Step 1 always has one - the way to bring
    in more documents is a new batch, whatever this one is doing.
    """
    job_url = reverse("admin:insights_wizard_job", args=[job.id]) if job else None
    status = job.status if job else None
    urls = {
        1: job_url if status == "collecting" else reverse("admin:insights_wizard_start"),
        2: job_url if status in READ_STATUSES else None,
        3: job_url if status in ("queued", "running", "failed") else None,
        4: job_url if status == "loaded" else None,
    }
    return [{
        "number": number,
        "label": label,
        "url": None if number == current else urls[number],
        "state": ("is-current" if number == current
                  else "is-done" if current and number < current else ""),
    } for number, label in STEPS]


def page(request, **extra):
    """The context every wizard page needs.

    each_context() is what supplies the admin's header, breadcrumbs, site title
    and the user menu. admin_view() does NOT add it - it wraps a view in the
    permission check and the login redirect and nothing else - so a page that
    forgets this renders as an unstyled orphan with no way back to the admin.
    """
    return {
        **django_admin.site.each_context(request),
        "wizard_steps": step_links(extra.get("job"), extra.get("wizard_step", 0)),
        **extra,
    }


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

    return JsonResponse(_accept(job, upload, label))


@require_POST
def batch_url(request, job_id):
    """Take exactly one link, fetch what is behind it, and catalogue that.

    THE SAME BATCH AS THE FILE PICKERS, and the same row shape back, so a
    batch can mix documents off the operator's disk with documents off the web
    and the preview table needs no second way to draw a result.

    Fetched server-side rather than in the browser because the browser cannot:
    a cross-origin PDF is not readable by script, and the file has to reach
    this container to be catalogued at all. weblink.fetch is what decides the
    document's type, from the bytes - see that module.
    """
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    url = (request.POST.get("url") or "").strip()
    if not url:
        return JsonResponse({"error": "No link was sent."}, status=400)

    try:
        name, payload = weblink.fetch(url)
    except weblink.NotADocument as exc:
        # Not a failure: the same outcome as a photograph inside a chosen
        # folder, and reported the same way.
        return JsonResponse({"name": url, "outcome": "skipped", "message": str(exc)})
    except weblink.BadLink as exc:
        # Already a sentence for a person, so it is not prefixed with a type.
        return JsonResponse({"name": url, "outcome": "failed", "message": str(exc)})
    except Exception as exc:                      # noqa: BLE001 - reported per link
        # A refused connection or a 404 is an expected input here, not an
        # exceptional one: one dead link in a pasted list of thirty must not
        # take the other twenty-nine down.
        return JsonResponse({
            "name": url, "outcome": "failed",
            "message": f"{type(exc).__name__}: {exc}",
        })

    # THE LINK IS THE LABEL. Where a document came from is the whole provenance
    # story for a link, and `label` is already the column that means that - so
    # this needs no column of its own, and therefore no migration.
    return JsonResponse(_accept(job, ContentFile(payload, name=name), url))


def _accept(job, upload, label):
    """Store, catalogue and attach one document. Returns the row to report.

    THE ONE PLACE A DOCUMENT JOINS A BATCH, whether it was picked off the
    operator's disk or fetched from a link. Shared rather than written twice
    because the de-duplication below is a guarantee, and a guarantee kept in
    two places is a guarantee kept in one of them.

    HASHED BEFORE IT IS SAVED, AND MATCHED ON THE HASH. catalogue_file
    de-duplicates on rel_path, which for an upload is
    "media/<sha1[:12]>-<stored name>" - and the STORED name is whatever
    Django's storage settled on, which uniquifies a collision to
    "report_AbCdEf.pdf". So the same report sent twice, or sent under two
    names, lands on two rel_paths and is catalogued twice. Matching on
    Document.sha1 is what actually answers "is this file already in the
    database". File.chunks() seeks to 0 first, so the upload is still
    readable afterwards.
    """
    digest = hashlib.sha1()
    for chunk in upload.chunks():
        digest.update(chunk)
    fingerprint = digest.hexdigest()

    existing = Document.objects.filter(sha1=fingerprint).first()
    if existing is not None:
        # Normally nothing is written: a second copy on disk of a file already
        # catalogued is pure cost. The document is attached to this batch so
        # it is extracted with the rest of it.
        #
        # UNLESS ITS COPY HAS BEEN RELEASED. insights.retention deletes the
        # uploaded file once the reading is done or the retention cap passes,
        # and a document with no file left is one step 2 cannot read: Docling
        # would fail on every page and the document would silently keep
        # whatever text it already had. So the bytes are stored again here, on
        # a fresh clock, and this import can be read like any other.
        job.documents.add(existing)
        restored = _restore_file(existing, upload, label)
        moved = _adopt_pending(existing, job)
        return {
            "name": label, "outcome": "duplicate", "pages": existing.pages,
            "document_id": existing.id,
            "message": _duplicate_message(restored, moved),
        }

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
        return {
            "name": label, "outcome": "failed",
            "message": f"{type(exc).__name__}: {exc}",
        }

    row.document = document
    row.save(update_fields=["document"])
    job.documents.add(document)

    return {
        "name": label, "outcome": "catalogued", "pages": document.pages,
        "document_id": document.id, "message": "",
    }


def _restore_file(document, upload, label):
    """Store this document's bytes again if nothing holds them any more.

    The upload was read once already, to fingerprint it; chunks() seeks to 0
    first, so it is still readable here.
    """
    if InsightUpload.objects.filter(document=document).exclude(file="").exists():
        return False
    InsightUpload.objects.create(file=upload, label=label, document=document)
    return True


def _adopt_pending(document, job):
    """Move this document's un-reviewed statements to the batch re-importing it.

    A REVIEW QUEUE BELONGS TO THE BATCH A PERSON IS LOOKING AT. The review step
    lists Insight.objects.filter(job=job), so statements left pending on an
    abandoned batch would be invisible to the batch that imported the same
    document again - and the person would pay the model to extract them a
    second time, to read the same quotes off the same pages.

    Only pending rows move. A published or rejected statement is a decision,
    and a decision stays with the run that produced it.
    """
    return (Insight.objects.filter(document=document, status="pending")
            .exclude(job=job).update(job=job))


def _duplicate_message(restored, moved):
    """What the row on the intake screen says about a file already catalogued."""
    parts = ["Already catalogued - the same file is in the database."]
    if restored:
        parts.append("Its copy had been released, so it was stored again for this batch.")
    if moved:
        parts.append(f"{moved} statement{'' if moved == 1 else 's'} still awaiting "
                     f"review moved to this batch.")
    return " ".join(parts)


@require_POST
def batch_ready(request, job_id):
    """Close the batch and queue it for extraction.

    A BATCH WITH NOTHING IN IT IS NOT CLOSED. Every file skipped, or - far more
    likely now that links are a source - every link a web page rather than the
    attachment on it, leaves a job with no documents. Closed anyway, that job
    walks the whole wizard looking like a real one and has nothing in it to
    read, while the per-item reasons it is empty are gone: they were rows on a
    page that has navigated away. Refused here as well as in the browser,
    because this is what makes that state unreachable from any client.

    A duplicate counts. _accept attaches an already-catalogued document to this
    job, so a batch of nothing but duplicates is a full batch.
    """
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    total = job.documents.count()
    if total == 0:
        return JsonResponse({
            "closed": False, "documents_total": 0,
            "message": ("Nothing in this batch could be read, so it was not "
                        "started. Each row above says why."),
        })

    job.documents_total = total
    job.status = "collected"
    job.save(update_fields=["documents_total", "status"])
    return JsonResponse({"closed": True, "documents_total": job.documents_total})


@require_POST
def read(request, job_id):
    """Launch the Docling conversion as a detached background process.

    Detached for the same two reasons extraction is: a gunicorn worker
    recycling mid-run must not kill it, and closing this tab must not either.
    With OCR on every page this is the LONGER of the two runs, not the shorter.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)

    if job.status == "converting":
        # A double click must not run two conversions of the same job: both
        # delete and rebuild the same DocumentText rows, and the loser could
        # commit its delete after the winner's insert - leaving the document
        # textless, which is the one state s02 cannot recover for an upload.
        return JsonResponse({"started": False, "message": "This batch is already being read."})

    # A batch whose files the retention sweep took cannot be read, and the
    # failure without this is silent: every document would come back badged
    # "Docling failed" and quietly keep its weaker intake text.
    if retention.released_documents(job):
        return JsonResponse({"started": False, "message": retention.released_sentence()})

    path = log_path(job, "convert")
    path.parent.mkdir(parents=True, exist_ok=True)

    # Set and saved BEFORE launching: this request returns at once, and the
    # child is what moves the job on to "converted" - or leaves it at
    # "converting" if it dies, which is visible either way.
    job.status = "converting"
    job.save(update_fields=["status"])

    with open(path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "manage.py", "convert_documents", "--job", str(job.id)],
            cwd=settings.BASE_DIR,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    return JsonResponse({"started": True, "message": "Reading started."})


@require_POST
def read_done(request, job_id):
    """The Continue button: the operator has looked at the text, so queue it.

    This, and not the end of the conversion, is what reaches "queued". If the
    command set it directly, reopening the batch would route straight past this
    page to the extract step, and step 2 would once again be a step nobody can
    stand on.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status != "converted":
        return JsonResponse({"moved": False, "message": "This batch has not been read yet."})
    job.status = "queued"
    job.save(update_fields=["status"])
    return JsonResponse({"moved": True})


def start(request):
    """Step 1: the two pickers. No job exists until a file is actually sent.

    AND THE ONE PLACE THE RETENTION SWEEP IS SURE TO RUN. There is no scheduler
    in this deployment - compose runs db, web and pgadmin - so the sweep rides
    on the wizard's own front door, which is the page anybody who uploads
    documents passes through. `manage.py prune_uploads` is the same sweep for a
    host cron.
    """
    retention.sweep()
    return render(request, "insights/wizard_intake.html", page(request, wizard_step=1))


def job_step(request, job_id):
    """Whichever step this job's status puts it at.

    Read off the job rather than kept in the session, so closing the tab loses
    nothing: the same URL reopens the batch where it actually is.
    """
    retention.sweep()
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status == "collecting":
        return render(request, "insights/wizard_intake.html",
                      page(request, job=job, wizard_step=1))
    if job.status in READ_STATUSES:
        return render(request, "insights/wizard_read.html",
                      page(request, job=job, wizard_step=2,
                           documents=_job_documents(job),
                           released=retention.released_documents(job),
                           released_sentence=retention.released_sentence()))
    if job.status in ("queued", "running", "failed"):
        return render(request, "insights/wizard_extract.html",
                      page(request, job=job, wizard_step=3))
    return render(request, "insights/wizard_review.html",
                  page(request, job=job, wizard_step=4, insights=_job_insights(job)))


def _job_documents(job):
    """This batch's documents with how each was read, and the text itself.

    The text is shown AS STORED, not rendered: the promise of this page is
    "what the model will read", and rendering the markdown to HTML would show
    something else - the one thing a preview must not do.
    """
    documents = (job.documents.select_related("conversion")
                 .prefetch_related("texts").order_by("file_name"))
    return [{
        "document": document,
        "conversion": getattr(document, "conversion", None),
        "text": "\n\n".join(
            f"--- page {row.page} ---\n{row.text or ''}"
            for row in sorted(document.texts.all(), key=lambda r: r.page)),
    } for document in documents]


def _job_insights(job):
    """This job's statements, grouped the way they are read: by document, by page."""
    return (Insight.objects.filter(job=job)
            .select_related("document")
            .prefetch_related("codings", "figures", "movements")
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


def log_path(job, stage="extract"):
    """Where a detached run writes its output. One file per stage.

    Separate files because the two stages have separate failure stories, and a
    reader of the extract log should not have to scroll past an OCR run to
    find where the model refused a chunk. The default keeps every existing
    caller meaning what it meant.
    """
    name = f"job-{job.id}.log" if stage == "extract" else f"job-{job.id}-{stage}.log"
    return Path(settings.API_CACHE_DIR) / "insights" / name


def _stage_of(job):
    """Which run's log this job's page should be watching."""
    return "convert" if job.status in READ_STATUSES else "extract"


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
    path = log_path(job, _stage_of(job))
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
        # run by an agent on the host, writing payloads into api_cache/insights/
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
