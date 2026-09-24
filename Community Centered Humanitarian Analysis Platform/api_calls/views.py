"""Starting a job from a button, and watching it.

The launch pattern is the one insights/admin.py established: create the row, then
Popen the management command with start_new_session=True. That flag is not
optional - docker-compose.yml explains why at length: a detached child that
outlives its worker otherwise reparents to gunicorn's arbiter, which reads its
exit code as a worker boot failure and halts the server.
"""
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from datetime import timedelta

from django.utils import timezone

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.management.commands.load_workbooks import WORKBOOKS, file_changed
from external_data.models import SourceSync
from api_calls.locks import JobBusy, claim
from django.db.models import Q

from api_calls.models import ACTIVE, PullJob

# Which source_sync variants name a workbook load_workbooks knows how to read.
# Taken FROM the command rather than retyped here: a third workbook added there
# gets a working button with no edit to this file, and a variant renamed there
# cannot leave a button pointing at a --only value the command would reject.
WORKBOOK_VARIANTS = {key["variant"] for *_, key in WORKBOOKS}

# Sources refreshed from a file on disk instead of an API. What this changes is
# only the wording - "re-read the workbook" rather than "fetch from the API" -
# but a confirmation page that promises an API call for a file read is a page an
# operator learns to stop reading.
FILE_SOURCES = {"excel"}


def _log_path(job):
    """Where this job's output goes. Under /app, because /work is read-only."""
    # `PullJob.log_path` stores the ABSOLUTE path, so this folder cannot be moved
    # by a `mv` alone - the rows already written would point at nothing. It was
    # api_cache/mcp/ until 2026-09-24; migration 0003 rewrote the 17 rows that
    # named it, and must be extended the same way if it moves again.
    directory = Path(settings.API_CACHE_DIR) / "api"
    # Created here rather than by the command: on a fresh setup the very first
    # press would otherwise fail opening the file before the command could run.
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"job-{job.id}.log"


def _launch(job, argv):
    """Run a management command detached, with its output going to the job log.

    A FAILURE TO LAUNCH FAILS THE JOB. Without this the row stays 'queued' with
    no process behind it, holding its source - or, for a rebuild, holding every
    source - against every future press. No path that has finished may leave a
    job in an active status.
    """
    try:
        path = _log_path(job)
        job.log_path = str(path)
        job.save(update_fields=["log_path"])
        with open(path, "wb") as log_file:
            subprocess.Popen(
                [sys.executable, "manage.py", *argv],
                cwd=settings.BASE_DIR,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
    except Exception as exc:
        job.status = "failed"
        job.finished_at = timezone.now()
        job.message = f"could not start: {exc}"[:4000]
        job.save(update_fields=["status", "finished_at", "message"])
        raise


def refresh_argv(row, job_id):
    """The management command that refreshes this row, or None if nothing does.

    THE ONE PLACE THAT DECIDES. Three callers need the same answer - the button
    on the list, the confirmation view, and pull_batch - and when that answer was
    "does fetcher_for() return something?" repeated in each of them, adding a
    second kind of refresh meant finding all three. A row now either names a
    command or it does not.

    An Excel row is refreshed from the WORKBOOK ON DISK, under /work, not from an
    API: the two files are maintained by hand, so "pull the latest" means re-read
    the file the analyst has just saved. `--only` is what keeps one row's button
    to one workbook; see load_workbooks.
    """
    if fetcher_for(row.source, row.dataset, row.variant) is not None:
        argv = ["refresh_external", row.source, row.dataset, "--job", str(job_id)]
        if row.iso3:
            argv += ["--iso3", row.iso3]
        if row.variant:
            argv += ["--variant", row.variant]
        return argv

    if row.source == "excel" and row.variant in WORKBOOK_VARIANTS:
        return ["load_workbooks", "--only", row.variant, "--job", str(job_id)]

    return None


def pull(request, pk):
    """Start a pull for one source_sync row."""
    row = SourceSync.objects.filter(pk=pk).first()
    if row is None:
        raise Http404("no such data source")

    why = pullable(row)
    if why:
        messages.error(request, f"{row.source}/{row.dataset} cannot be refreshed: {why}")
        return redirect("admin:api_calls_datasource_changelist")

    if request.method != "POST":
        # A pull changes the database and an IPC one moves 8-15 MB per analysis,
        # so it is never started by following a link. The GET is a confirmation
        # page whose form POSTs back here with a CSRF token.
        return render(request, "api_calls/confirm.html",
                      {"row": row, "from_file": row.source in FILE_SOURCES})

    try:
        job = claim("pull", source=row.source, dataset=row.dataset, iso3=row.iso3,
                    variant=row.variant, user=request.user)
    except JobBusy as exc:
        messages.warning(request, str(exc))
        return redirect("admin:api_calls_datasource_changelist")

    argv = refresh_argv(row, job.id)
    try:
        _launch(job, argv)
    except Exception as exc:
        messages.error(request, f"job {job.id} could not start: {exc}")
        return redirect("admin:api_calls_datasource_changelist")

    verb = "re-reading" if row.source in FILE_SOURCES else "pulling"
    messages.success(request, f"job {job.id}: {verb} {row.source}/{row.dataset} "
                              f"{row.iso3 or 'global'} in the background.")
    return redirect("admin:api_calls_datasource_changelist")


def job_page(request, job_id):
    """One job, with its log."""
    job = PullJob.objects.filter(pk=job_id).first()
    if job is None:
        raise Http404("no such job")
    log = ""
    if job.log_path and Path(job.log_path).is_file():
        log = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
    return render(request, "api_calls/job.html", {"job": job, "log": log})


def job_status(request, job_id):
    """Just enough for the page to poll without reloading everything."""
    job = PullJob.objects.filter(pk=job_id).first()
    if job is None:
        raise Http404("no such job")
    return JsonResponse({"status": job.status, "rows": job.rows_written,
                         "message": job.message})


def pullable(row):
    """Can this row be refreshed right now? Returns None, or the reason it cannot.

    A KEY IS ONLY EVER ASKED OF A FETCHER. `missing_keys` reads a fetcher class's
    own list of required settings, so a workbook row - which has no fetcher - must
    not be put through it.
    """
    fetcher_cls = fetcher_for(row.source, row.dataset, row.variant)
    if fetcher_cls is not None:
        absent = missing_keys(fetcher_cls)
        return f"{absent[0]} is not set" if absent else None

    if refresh_argv(row, 0) is None:
        return "no API and no file command for this row"
    return None


def stale_rows():
    """The rows "pull everything out of date" should actually pull.

    OUT OF DATE, NOT SIMPLY PULLABLE. Anything already pulled today is left
    alone, so pressing the button twice in a row costs nothing the second time -
    which is the difference between a refresh button and a re-download button.
    Rows with no API and no file command, and rows whose key is missing, are never
    included: there is nothing to ask.

    A WORKBOOK ROW IS JUDGED BY ITS FILE, not by that date. An API asked twice in
    one day gives the same answer; a workbook saved an hour after the last load
    does not, and the date rule would skip exactly the edit the operator pressed
    the button for. `file_changed` compares the sha1 already held in `params`.
    """
    today = timezone.now().date()
    out = []
    for row in SourceSync.objects.all():
        if pullable(row) is not None:
            continue
        if row.source in FILE_SOURCES:
            if file_changed(row):
                out.append(row)
            continue
        if not (row.last_pulled_at and row.last_pulled_at.date() >= today):
            out.append(row)
    return out


def start_batch(request, rows):
    """Claim a batch job for these rows and launch it detached."""
    job = claim("batch", user=request.user)
    job.progress_total = len(rows)
    job.save(update_fields=["progress_total"])
    _launch(job, ["pull_batch", "--job", str(job.id),
                  "--rows", ",".join(str(r.pk) for r in rows)])
    return job


def pull_all(request):
    """One press: bring every out-of-date source up to date, one at a time."""
    rows = stale_rows()
    if request.method != "POST":
        return render(request, "api_calls/confirm_batch.html",
                      {"rows": rows, "heading": "Pull everything out of date"})

    if not rows:
        messages.info(request, "Everything with an API was already pulled today.")
        return redirect("admin:api_calls_datasource_changelist")

    try:
        job = start_batch(request, rows)
    except JobBusy as exc:
        messages.warning(request, str(exc))
        return redirect("admin:api_calls_datasource_changelist")
    except Exception as exc:
        messages.error(request, f"could not start: {exc}")
        return redirect("admin:api_calls_datasource_changelist")

    messages.success(request, f"job {job.id}: pulling {len(rows)} sources, one at a time.")
    return redirect("admin:api_calls_datasource_changelist")


def activity(request):
    """What is happening, and what just happened - the banner's only source.

    Finished jobs are included for THIRTY MINUTES after they end. That window is
    the point of the banner: a pull that failed while you were on another tab is
    still on the page when you come back, so the Pull jobs list is somewhere you
    go to read a log, not somewhere you go to find out whether anything worked.
    """
    cutoff = timezone.now() - timedelta(minutes=30)
    jobs = PullJob.objects.filter(
        Q(status__in=ACTIVE) | Q(finished_at__gte=cutoff)
    ).order_by("-requested_at")[:12]

    def one(job):
        return {
            "id": job.id,
            "kind": job.kind,
            "target": job.target,
            "status": "stuck" if job.is_stale else job.status,
            "done": job.progress_done,
            "total": job.progress_total,
            "note": job.progress_note,
            "rows": job.rows_written,
            "message": job.message[:200],
            "url": f"job/{job.id}/",
        }

    payload = [one(j) for j in jobs]
    return JsonResponse({
        "running": [j for j in payload if j["status"] in ACTIVE or j["status"] == "stuck"],
        "finished": [j for j in payload if j["status"] in ("succeeded", "failed")],
    })


def pulls_since_last_rebuild():
    """How many successful pulls the dashboard has not been rebuilt for.

    The button works with zero; the count is what tells an operator whether it is
    worth pressing. FAILED PULLS DO NOT COUNT - a pull that failed changed
    nothing, so it is not a reason to rebuild anything.
    """
    last = (PullJob.objects.filter(kind="rebuild", status="succeeded")
            .order_by("-finished_at").first())
    pulls = PullJob.objects.filter(kind="pull", status="succeeded")
    if last and last.finished_at:
        pulls = pulls.filter(finished_at__gt=last.finished_at)
    return pulls.count()


def rebuild(request):
    """Rebuild the dashboard's external layers from what is now in the database.

    SEPARATE FROM A PULL, deliberately. A pull updates the database and stops
    there; rebuilding the map is the operator's call, made after they have looked
    at what arrived. Chaining the two would widen a refresh button's blast radius
    to a pipeline that rewrites dashboard files.

    The steps are s06 and s07 - the same pair the updater page's own rebuild runs.
    """
    if request.method != "POST":
        return render(request, "api_calls/confirm_rebuild.html",
                      {"pulls": pulls_since_last_rebuild()})

    try:
        job = claim("rebuild", user=request.user)
    except JobBusy as exc:
        messages.warning(request, str(exc))
        return redirect("admin:api_calls_datasource_changelist")

    # run_rebuild, NOT run_pipeline: the pipeline takes no --job and would leave
    # this row at 'queued' forever, blocking every pull on every source. See the
    # docstring of api_calls/management/commands/run_rebuild.py.
    try:
        _launch(job, ["run_rebuild", "--job", str(job.id)])
    except Exception as exc:
        messages.error(request, f"job {job.id} could not start: {exc}")
        return redirect("admin:api_calls_datasource_changelist")

    messages.success(request, f"job {job.id}: rebuilding the dashboard layers.")
    return redirect("admin:api_calls_datasource_changelist")
