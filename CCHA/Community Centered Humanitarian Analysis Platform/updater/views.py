"""The one-click updater page at /updater/.

What it does
------------
1. Counts how many new UNHCR PDFs have been dropped into the two source folders
   (a PDF is "new" when its path is not yet a row in the documents table).
2. On "Update now", runs the pipeline as a background process and streams the
   progress back to the browser live, so you watch a real progress bar.
3. Shows how fresh each external map layer is, and can rebuild those layers
   from the cached MCP pulls.

How the live progress works
---------------------------
The browser opens an EventSource (Server-Sent Events). Django answers with a
StreamingHttpResponse that never finishes until the pipeline does; each line the
pipeline prints is forwarded as one "data: {...}" message. The functions that
produce those messages are Python generators - they `yield` a message instead of
returning once.

Important: fetching *brand new* data from the humanitarian MCP servers cannot
happen in this container. It needs the Claude Code client and API keys, so it is
run by an analyst on the host; that step refreshes api_cache/. The button
here only re-applies whatever is already in that cache.
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from data_pipeline.management.commands.run_pipeline import STEPS as PIPELINE_STEPS
from data_track.models import Document
from api_calls.locks import JobBusy, claim
from api_calls.models import ACTIVE, PullJob

# Only one update may run at a time - and "one" has to mean one across the whole
# deployment, not one per web worker.
#
# WHY NOT threading.Lock, WHICH IS WHAT THIS USED TO BE. gunicorn runs two
# workers (see the Dockerfile), and a module-level lock lives in one process. Two
# browsers landing on two workers each took their own copy of it and both started
# a pipeline, whose first act is to delete every row in population_figures. The
# lock could not be seen from api_calls/locks.py either, so an Admin -> MCP rebuild and
# an "Update now" rebuilt the same tables at the same time.
#
# A PullJob claimed through api_calls.locks.claim() is the gate every other route into
# those tables already uses: a PostgreSQL advisory lock serialises the claim, and
# the uniq_active_rebuild constraint is the database's own guarantee behind it.
# "rebuild" is the right kind for both buttons here, because both read and write
# every table a pull writes, so both must wait for the pulls and block them.

# run_pipeline prints "=== sNN_name ===" between steps. Each step is given a
# slice of the 0-100% bar, so the bar moves smoothly through the whole run.
STEP_BANDS = {
    "s01_catalog": (0, 8),
    "s02_extract_text": (8, 60),   # the slow step - PDF text extraction
    "s03_parse": (60, 80),
    "s04_events": (80, 85),
    "s05_export": (85, 92),
    "s06_mcp_layers": (92, 97),
    "s07_xlsx": (97, 100),
}

# The keys above are the step *file names* in data_pipeline/steps/. If one is
# renamed and this dictionary is not updated, the bar silently stops moving
# (STEP_BANDS.get returns None) instead of failing. This check turns that into
# an immediate, obvious error at start-up.
_STEP_FILES = {module.rsplit(".", 1)[-1] for _, module, _ in PIPELINE_STEPS}
if _STEP_FILES != set(STEP_BANDS):
    raise ImproperlyConfigured(
        "updater STEP_BANDS is out of step with data_pipeline's STEPS: "
        f"only in the pipeline: {sorted(_STEP_FILES - set(STEP_BANDS))}, "
        f"only in STEP_BANDS: {sorted(set(STEP_BANDS) - _STEP_FILES)}"
    )


# ---------------------------------------------------------------- helpers
def list_new_files():
    """Return the PDFs in the source folders that the database has never seen."""
    seen = {p.replace("\\", "/") for p in Document.objects.values_list("rel_path", flat=True)}
    new = []
    for base in settings.SOURCE_COLLECTIONS.values():
        if not base.exists():
            continue
        for pdf in sorted(base.rglob("*.pdf")):
            rel = pdf.relative_to(settings.SOURCE_ROOT).as_posix()
            if rel not in seen:
                new.append(rel)
    return new


def _sse(payload: dict) -> str:
    """Format one Server-Sent Event line the way browsers expect it."""
    return f"data: {json.dumps(payload)}\n\n"


def _manage_py() -> list:
    """The command that runs a manage.py command in a separate process."""
    return [sys.executable, "-u", str(Path(settings.BASE_DIR) / "manage.py")]


def _modified_date(path: Path):
    """The day a file was last written, as 'YYYY-MM-DD' (or None if missing)."""
    if not path or not Path(path).exists():
        return None
    return datetime.date.fromtimestamp(Path(path).stat().st_mtime).isoformat()


def external_layers():
    """Freshness of every external map layer: when it was pulled, when it was built."""
    cache = Path(settings.API_CACHE_DIR)
    data = Path(settings.DASHBOARD_DATA_DIR)
    ipc_files = sorted(cache.glob("ipc_area_*.geojson"))
    periods = [m.group(1) for f in ipc_files if (m := re.search(r"(\d{4}-\d{2})", f.name))]
    return [
        {"label": "IDP localities (admin2)", "source": "IOM-DTM - HDX", "kind": "MCP cache",
         "detail": "per-locality DTM Overview series",
         "cached": _modified_date(cache / "idps_admin2_overview.json"),
         "built": _modified_date(data / "idp_localities.json")},
        {"label": "Food insecurity (IPC areas)", "source": "IPC", "kind": "MCP cache",
         "detail": (f"{len(periods)} analysis periods, latest {periods[-1]}"
                    if periods else "no periods cached"),
         "cached": _modified_date(ipc_files[-1]) if ipc_files else None,
         "built": _modified_date(data / "ipc_areas_fs.geojson")},
        {"label": "IFRC Areas of Interest - IPC phase", "source": "IPC + HSP boundaries",
         "kind": "MCP cache", "detail": "worst IPC phase per area (point-in-polygon)",
         "cached": _modified_date(cache / "aoi_ipc_phases.json"),
         "built": _modified_date(data / "aoi_ipc.geojson")},
        {"label": "Refugee totals + camps", "source": "UNHCR - HDX + Excel", "kind": "MCP + Excel",
         "detail": "country totals (step 6) + Excel snapshots (step 7)",
         "cached": _modified_date(Path(settings.POP_MOVEMENT_XLSX)),
         "built": _modified_date(data / "refugee_camps.json")},
        {"label": "Seasonal calendar", "source": "FEWS NET", "kind": "curated in step 6",
         "detail": "lean / rainy / harvest bands",
         "cached": None, "built": _modified_date(data / "seasonal.json")},
        {"label": "Border crossings", "source": "curated", "kind": "curated in step 6",
         "detail": "authoritative crossings tagged to corridors",
         "cached": None, "built": _modified_date(data / "crossings.json")},
    ]


def _stream_command(args, band_lookup=None, outcome=None):
    """Run a command and yield each of its output lines as an SSE message.

    band_lookup: optional function turning a printed step name into a (start,
    end) percentage band, so the progress bar can follow the pipeline.
    outcome:     a dict the caller passes in; we set outcome["ok"] to True or
                 False when the command finishes, because a generator cannot
                 return a value to the code that is looping over it.
    """
    outcome = outcome if outcome is not None else {}
    outcome["ok"] = False
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        args, cwd=str(settings.BASE_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    band = (0, 100)
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if not line.strip():
            continue

        # A step header moves the bar to the start of that step's band.
        step = re.search(r"=== (\w+) ===", line)
        if step and band_lookup and (found := band_lookup(step.group(1))):
            band = found
            yield _sse({"type": "progress", "pct": band[0], "msg": step.group(1)})

        # Inside the slow text-extraction step, lines look like "  120/900".
        prog = re.match(r"\s*(\d+)/(\d+)\s*$", line)
        if prog and band == STEP_BANDS["s02_extract_text"]:
            done, total = int(prog.group(1)), int(prog.group(2))
            if total:
                pct = band[0] + (band[1] - band[0]) * done / total
                yield _sse({"type": "progress", "pct": round(pct, 1),
                            "msg": f"extracting text {done}/{total}"})

        yield _sse({"type": "log", "msg": line})

    proc.wait()
    if proc.returncode != 0:
        yield _sse({"type": "error",
                    "msg": f"Command failed (exit {proc.returncode}). See the log above."})
        return
    outcome["ok"] = True
    yield _sse({"type": "progress", "pct": 100, "msg": "complete"})


def _close_job(job, status, message):
    """Mark a job finished. Called once, from the stream's finally block."""
    job.status = status
    job.finished_at = timezone.now()
    job.message = message[:4000]
    job.save(update_fields=["status", "finished_at", "message"])


def _gated_stream(argv, scope, done_message, preamble=None):
    """Claim the rebuild gate, stream the command, and always close the job.

    The finally block matters more here than in run_rebuild: this generator is
    driven by a browser, and Django closes it when the client goes away. Without
    the release, one navigation away mid-run would leave a job at 'running'
    holding every table against every later press - with nobody watching the run
    it is protecting. A worker killed outright still leaves the row behind, which
    is what PullJob.is_stale and the reset affordance exist for.
    """
    try:
        job = claim("rebuild", dataset=scope)
    except JobBusy as exc:
        yield _sse({"type": "error", "msg": str(exc)})
        return

    job.status = "running"
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    # Only now that the run is actually going. Counting the waiting PDFs before
    # the claim told the browser a run was starting that was then refused.
    if preamble is not None:
        yield _sse(preamble())

    outcome = {}
    try:
        yield from _stream_command(argv, STEP_BANDS.get, outcome)
        if outcome["ok"]:
            yield _sse({"type": "done", "msg": done_message})
    finally:
        if outcome.get("ok"):
            _close_job(job, "succeeded", done_message)
        else:
            _close_job(job, "failed", "the run did not finish - see the log")


def run_pipeline_stream():
    """Full update: ingest new PDFs, re-parse, rebuild every dashboard file."""
    def starting():
        return {"type": "progress", "pct": 0,
                "msg": f"Starting - {len(list_new_files())} new PDF(s) to ingest"}

    yield from _gated_stream(
        _manage_py() + ["run_pipeline"],
        "full pipeline",
        "Update complete - dashboard refreshed.",
        preamble=starting,
    )


def rebuild_external_stream():
    """Rebuild only the external map layers from the caches already on disk."""
    yield from _gated_stream(
        _manage_py() + ["run_pipeline", "--only", "s06,s07"],
        "external layers",
        "External layers rebuilt - dashboard refreshed.",
    )


def _event_stream(generator):
    """Wrap a generator in the HTTP response type browsers use for live updates."""
    response = StreamingHttpResponse(generator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"   # tells any proxy not to hold the stream back
    return response


# ---------------------------------------------------------------- pages and endpoints
def index(request):
    """The updater page itself."""
    return render(request, "updater/index.html", {"dashboard_url": settings.DASHBOARD_URL})


def status(request):
    """How many new PDFs are waiting, and how many documents are already stored.

    `running` is read from the job table, not from a flag in this process. The
    two workers do not share memory, so the old _lock.locked() answered "idle"
    from whichever worker had not started the run - the page said nothing was
    happening while a pipeline was halfway through. Any active job counts, not
    only a rebuild: while a pull holds its source, pressing Update now is refused
    by claim(), so reporting idle would be a lie the button then contradicts.
    """
    new = list_new_files()
    blocker = PullJob.objects.filter(status__in=ACTIVE).order_by("requested_at").first()
    return JsonResponse(
        {
            "new_count": len(new),
            "new_files": [Path(p).name for p in new[:60]],
            "more": max(0, len(new) - 60),
            "db_total": Document.objects.count(),
            "running": blocker is not None,
            "running_detail": blocker.target if blocker else "",
        }
    )


def external(request):
    """Freshness table for the external map layers."""
    return JsonResponse({"layers": external_layers()})


def update(request):
    """Start a full update and stream its progress."""
    return _event_stream(run_pipeline_stream())


def rebuild_external(request):
    """Start an external-layers-only rebuild and stream its progress."""
    return _event_stream(rebuild_external_stream())
