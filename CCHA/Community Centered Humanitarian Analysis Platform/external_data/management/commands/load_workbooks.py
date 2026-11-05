"""`python manage.py load_workbooks` - the two Excel workbooks into the database.

    docker compose exec web python manage.py load_workbooks
    docker compose exec web python manage.py load_workbooks --dry-run
    docker compose exec web python manage.py load_workbooks --only sudan-idps-workbook

These two files are maintained by hand beside the PDFs, so they have no MCP call
behind them and no date to ask a server for. Their watermark is the file itself:
`params` records each workbook's sha1 and modification time, which is how a later
run can tell "unchanged since last load" from "never loaded".

Both are read in full every time. They are small, and a full re-read is the only
way to notice that somebody corrected a figure in an old sheet.

`--only` AND `--job` EXIST FOR THE ADMIN BUTTON. The data sources page lists one
row per workbook, so its "Reload file" button has to be able to reload ONE of
them: without `--only`, pressing it on the Sudan IDPs row would also reload the
neighbours workbook, and would fail outright if that file happened to be absent.

`--job` is the contract refresh_external keeps - mark running, do the work, mark
succeeded or failed - and the job bookkeeping is kept OUTSIDE the transaction on
purpose. A failure recorded inside an atomic block is rolled back along with
everything else, leaving the job at 'queued'; 'queued' is an ACTIVE status, so
that row would then hold the 'excel' source against every future press. The
docstring of api_calls/management/commands/run_rebuild.py describes the same trap.
"""
import hashlib
from datetime import datetime, timezone

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from external_data.loaders.excel import parse_idp_states_sheet, parse_neighbours_sheet
from external_data.models import MovementPattern, SourceSync

UNIQUE_FIELDS = [
    "source", "metric", "iso3", "admin_pcode", "place_name", "date",
    "population_group",
]
UPDATE_FIELDS = [
    "admin_level", "value", "unit", "source_dataset",
    "reference_period_start", "reference_period_end", "lat", "lon",
]

# (filename, which parser, read every sheet?, source_sync identity)
WORKBOOKS = [
    ("neighbouring countries Pop movement data.xlsx", parse_neighbours_sheet, True,
     {"source": "excel", "dataset": "refugees", "iso3": None,
      "variant": "neighbours-workbook"}),
    ("Sudan IDPs.xlsx", parse_idp_states_sheet, False,
     {"source": "excel", "dataset": "idps", "iso3": "SDN",
      "variant": "sudan-idps-workbook"}),
]


# Workbook spellings the boundary library writes differently. Kept deliberately
# short: an alias here is a fact about one file, and every entry added without
# checking the library first is a place quietly filed under the wrong polygon.
WORKBOOK_ALIASES = {
    ("SDN", 1, "nile"): "river nile",
}


def resolve_pcodes(rows):
    """Fill admin_pcode from the boundary library, by name, within one country.

    The workbook names states and nothing else - "North Darfur", not "SD03". The
    library already holds those nineteen polygons with their p-codes and their
    alternate spellings, which is exactly what it was built for, so the join costs
    one query rather than another hand-maintained lookup table.

    A name that does not match is left with a null p-code and reported. It is not
    an error: the row is still a real observation, it simply cannot be drawn on a
    polygon until somebody reconciles the spelling.
    """
    from boundaries.models import AdminArea

    wanted = {(r["iso3"], r["admin_level"]) for r in rows if r.get("place_name")}
    lookup = {}
    for iso3, level in wanted:
        for area in AdminArea.objects.filter(iso3=iso3, level=level):
            lookup[(iso3, level, area.name.strip().lower())] = area.pcode
            for alt in area.name_alt or []:
                if alt:
                    lookup.setdefault((iso3, level, str(alt).strip().lower()), area.pcode)

    unmatched = set()
    for r in rows:
        if r.get("admin_pcode") or not r.get("place_name"):
            continue
        key = (r["iso3"], r["admin_level"], r["place_name"].strip().lower())
        key = key[:2] + (WORKBOOK_ALIASES.get(key, key[2]),)
        pcode = lookup.get(key)
        if pcode:
            r["admin_pcode"] = pcode
        elif r["admin_level"]:
            unmatched.add(r["place_name"])
    return sorted(unmatched)


def workbook_path(variant):
    """The file behind one workbook variant, or None if that is not a variant."""
    for filename, _parse, _all_sheets, key in WORKBOOKS:
        if key["variant"] == variant:
            return settings.SOURCE_ROOT / filename
    return None


def file_changed(sync):
    """Has this workbook moved since the row was last loaded?

    THE WATERMARK FOR A FILE IS THE FILE, not a date. "Pull everything out of
    date" skips anything already pulled today, which is right for an API - asking
    twice in a day gets the same answer. It is wrong here: an analyst who saves a
    corrected figure an hour after the last load would be told there is nothing to
    do. The sha1 already recorded in `params` answers the question properly.

    A missing file, and a row never loaded, both count as changed: each is
    something a refresh should look at and report, not silently skip.

    AND SO DOES A FILE THAT WILL NOT OPEN. This runs on every render of the data
    sources page, and it is the only thing on that page that touches /work - a
    OneDrive share, mounted into the container, where a Files-On-Demand
    placeholder that has not hydrated raises OSError out of open(). Letting that
    escape would 500 the whole list and take every other source's Pull now button
    down with it, over a file nobody had asked to load.
    """
    path = workbook_path(sync.variant)
    if path is None:
        return True
    try:
        if not path.is_file():
            return True
        return (sync.params or {}).get("sha1") != _fingerprint(path)["sha1"]
    except OSError:
        return True


def _fingerprint(path):
    """sha1 and mtime - the workbook equivalent of a high-water date."""
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "sha1": digest.hexdigest(),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "bytes": path.stat().st_size,
    }


class Command(BaseCommand):
    help = "Load the two hand-maintained Excel workbooks into movement_patterns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change and write nothing.",
        )
        parser.add_argument(
            "--only", default="",
            help="Load one workbook by its source_sync variant, e.g. "
                 "sudan-idps-workbook. Default: both.",
        )
        parser.add_argument(
            "--job", type=int, default=None,
            help="PullJob id to record progress against (the admin button).",
        )

    def handle(self, *args, **options):
        from api_calls.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        if job:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.save(update_fields=["status", "started_at"])

        try:
            rows_written, summary = self._run(options, job)
        except Exception as exc:
            # One place writes a failure onto the job, so there is one place
            # that has to remember to close it. Outside the transaction, so the
            # rollback of the load cannot take this record with it.
            self._finish(job, "failed", message=str(exc))
            raise

        self._finish(job, "succeeded", rows=rows_written, message="; ".join(summary))
        return None

    # ONE TRANSACTION AROUND BOTH WORKBOOKS, as before. A run that reads two
    # files and commits only the first leaves the table in a state no single
    # press produced, and the freshness row would then disagree with it.
    @transaction.atomic
    def _run(self, options, job=None):
        root = settings.SOURCE_ROOT
        wanted = options["only"] or ""
        books = [w for w in WORKBOOKS if not wanted or w[3]["variant"] == wanted]
        if not books:
            raise CommandError(
                f"--only {wanted}: no such workbook. Known variants: "
                + ", ".join(w[3]["variant"] for w in WORKBOOKS)
            )

        rows_written, summary = 0, []
        self._progress(job, done=0, total=len(books), note="starting")

        for index, (filename, parse, all_sheets, key) in enumerate(books, start=1):
            path = root / filename
            if not path.is_file():
                raise CommandError(
                    f"workbook not found: {path}. It is expected beside the PDFs, in "
                    f"the folder SOURCE_ROOT points at."
                )

            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            sheets = wb.worksheets if all_sheets else wb.worksheets[:1]
            rows = []
            for ws in sheets:
                rows.extend(parse(ws))
            wb.close()

            if not rows:
                # Same rule as the MCP loaders: nothing readable is a failure, not
                # a quiet success that advances the watermark.
                raise CommandError(
                    f"{filename}: no usable rows. Check the column headings - "
                    f"a renamed 'Data Date' or 'Population (DD Mon YYYY)' looks "
                    f"exactly like this."
                )

            unmatched = resolve_pcodes(rows)

            # One workbook can legitimately repeat a country and date across sheets;
            # the later sheet wins, matching s07's "latest value for the same date".
            deduped = {tuple(r[f] for f in UNIQUE_FIELDS): r for r in rows}
            collapsed = len(rows) - len(deduped)
            rows = list(deduped.values())

            self.stdout.write(f"{filename}: {len(rows)} rows")
            if collapsed:
                self.stdout.write(f"  {collapsed} duplicate observations collapsed")
            if unmatched:
                # Named, not counted: a spelling nobody can see is a spelling
                # nobody fixes.
                self.stdout.write(
                    f"  {len(unmatched)} place names matched no polygon: "
                    + ", ".join(unmatched)
                )
            if options["dry_run"]:
                self._progress(job, done=index, note=f"{filename}: dry run")
                summary.append(f"{filename}: {len(rows)} rows (dry run)")
                continue

            sync, _ = SourceSync.objects.get_or_create(**key)
            # Whether the file itself moved since the last load, read BEFORE the
            # new fingerprint overwrites it. "0 new figures" and "somebody has
            # not saved the workbook yet" look identical on the page otherwise,
            # and they call for completely different next steps.
            fingerprint = _fingerprint(path)
            unchanged = (sync.params or {}).get("sha1") == fingerprint["sha1"]

            MovementPattern.objects.bulk_create(
                [MovementPattern(**r) for r in rows],
                update_conflicts=True,
                unique_fields=UNIQUE_FIELDS,
                update_fields=UPDATE_FIELDS,
            )

            sync.tool = "openpyxl"
            sync.params = fingerprint
            sync.last_pulled_at = datetime.now(timezone.utc)
            latest = max(r["date"] for r in rows)
            if sync.high_water_date is None or latest > sync.high_water_date:
                sync.high_water_date = latest
            sync.row_count = MovementPattern.objects.filter(
                source="excel", source_dataset=filename
            ).count()
            sync.notes = "maintained by hand; re-read in full on every load"
            sync.save()
            self.stdout.write(f"  data now held to {sync.high_water_date}")
            if unchanged:
                self.stdout.write("  the file itself is unchanged since the last load")

            rows_written += len(rows)
            note = f"{len(rows)} rows, data to {sync.high_water_date}"
            if unchanged:
                note += " - file unchanged since the last load"
            summary.append(f"{filename}: {note}")
            self._progress(job, done=index, note=f"{filename}: {len(rows)} rows")

        return rows_written, summary

    def _progress(self, job, done=None, total=None, note=""):
        """How far along, on the row rather than scraped out of the log.

        The same reasoning as refresh_external._progress: a banner that parses
        stdout breaks the first time a message is reworded.

        These writes happen inside _run's transaction, so the banner does not see
        them until it commits - unlike a pull, where each call commits as it goes.
        That is tolerable only because reading two small local files takes seconds;
        'running' is set outside the transaction, so the banner still appears.
        """
        if not job:
            return
        fields = []
        if done is not None:
            job.progress_done = done
            fields.append("progress_done")
        if total is not None:
            job.progress_total = total
            fields.append("progress_total")
        if note:
            job.progress_note = note[:200]
            fields.append("progress_note")
        if fields:
            job.save(update_fields=fields)

    def _finish(self, job, status, rows=0, message=""):
        if not job:
            return
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.rows_written = rows
        job.message = str(message)[:4000]
        job.save(update_fields=["status", "finished_at", "rows_written", "message"])
