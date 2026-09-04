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
run by an analyst on the host; that step refreshes mcp_cache/. The button
here only re-applies whatever is already in that cache.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render

from data_pipeline.management.commands.run_pipeline import STEPS as PIPELINE_STEPS
from data_track.models import Document

# Only one update may run at a time. A lock is a flag that a second request
# cannot take while the first one holds it.
_lock = threading.Lock()

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
    cache = Path(settings.MCP_CACHE_DIR)
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


def run_pipeline_stream():
    """Full update: ingest new PDFs, re-parse, rebuild every dashboard file."""
    if not _lock.acquire(blocking=False):
        yield _sse({"type": "error", "msg": "An update is already running."})
        return
    try:
        new = list_new_files()
        yield _sse({"type": "progress", "pct": 0,
                    "msg": f"Starting - {len(new)} new PDF(s) to ingest"})
        outcome = {}
        yield from _stream_command(_manage_py() + ["run_pipeline"], STEP_BANDS.get, outcome)
        if outcome["ok"]:
            yield _sse({"type": "done", "msg": "Update complete - dashboard refreshed."})
    finally:
        _lock.release()


def rebuild_external_stream():
    """Rebuild only the external map layers from the caches already on disk."""
    if not _lock.acquire(blocking=False):
        yield _sse({"type": "error", "msg": "An update is already running."})
        return
    try:
        outcome = {}
        yield from _stream_command(
            _manage_py() + ["run_pipeline", "--only", "s06,s07"], STEP_BANDS.get, outcome
        )
        if outcome["ok"]:
            yield _sse({"type": "done", "msg": "External layers rebuilt - dashboard refreshed."})
    finally:
        _lock.release()


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
    """How many new PDFs are waiting, and how many documents are already stored."""
    new = list_new_files()
    return JsonResponse(
        {
            "new_count": len(new),
            "new_files": [Path(p).name for p in new[:60]],
            "more": max(0, len(new) - 60),
            "db_total": Document.objects.count(),
            "running": _lock.locked(),
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
