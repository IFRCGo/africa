"""`python manage.py pull_batch --job N --rows 3,7,12` - several sources, in turn.

ONE AT A TIME, AND THAT IS THE ENTIRE DESIGN. "Never pull two IPC countries in
parallel" is a recorded incident: the connection closed and the IPC server stayed
down for the rest of the session. A "pull everything" button spanning six IPC
countries is exactly how that happens again, so this command is a plain for-loop
and must stay one. Do not gather it, thread it, or hand it to a task queue.

Each row is refreshed by calling `refresh_external` in-process, which means every
guarantee that command keeps - fetch, save, load, watermark last, redact on the
way out - applies here unchanged. This file adds no data handling of its own.

ONE FAILURE DOES NOT STOP THE REST. A 503 from one agency must not cost the
operator the other five sources, so each row is tried, its outcome recorded, and
the batch reports the tally at the end.
"""
from datetime import datetime, timezone as dt_timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys, redact
from external_data.models import SourceSync


class Command(BaseCommand):
    help = "Refresh several data sources, strictly one at a time."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, default=None,
                            help="PullJob id (kind='batch') to record against")
        parser.add_argument("--rows", default="",
                            help="Comma-separated source_sync ids, in order")

    def handle(self, *args, **options):
        from mcp.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        ids = [int(i) for i in options["rows"].split(",") if i.strip()]
        rows = sorted(SourceSync.objects.filter(pk__in=ids), key=lambda r: ids.index(r.pk))

        if job:
            job.status = "running"
            job.started_at = datetime.now(dt_timezone.utc)
            job.progress_total = len(rows)
            job.save(update_fields=["status", "started_at", "progress_total"])

        pulled = failed = skipped = 0
        try:
            for index, row in enumerate(rows, start=1):
                label = f"{row.source}/{row.dataset} {row.iso3 or 'global'}"
                self._progress(job, index - 1, f"{label} ...")

                why = self._unpullable(row)
                if why:
                    skipped += 1
                    self.stdout.write(f"skip {label}: {why}")
                    self._progress(job, index, f"skipped {label}")
                    continue

                self.stdout.write(f"--- {label}")
                try:
                    # In-process, so refresh_external's own guarantees apply.
                    # Its per-source job row is not claimed here: the batch is
                    # already serial, and claiming would refuse a source the
                    # operator deliberately queued behind another.
                    call_command("refresh_external", row.source, row.dataset,
                                 iso3=row.iso3, variant=row.variant)
                    pulled += 1
                except Exception as exc:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"    failed: {redact(exc)}"))
                self._progress(job, index, f"{pulled} pulled, {failed} failed")
        finally:
            # ALWAYS closes. A batch left active holds no source itself, but the
            # uniq_active_batch constraint would refuse every later batch.
            parts = [f"{pulled} pulled"]
            if failed:
                parts.append(f"{failed} failed")
            if skipped:
                parts.append(f"{skipped} skipped")
            self._finish(job, ", ".join(parts))
            self.stdout.write(", ".join(parts))

    def _unpullable(self, row):
        """Why this row cannot be pulled, or None if it can."""
        fetcher_cls = fetcher_for(row.source, row.dataset, row.variant)
        if fetcher_cls is None:
            return "file-based, no API"
        absent = missing_keys(fetcher_cls)
        if absent:
            return f"{absent[0]} is not set"
        return None

    def _progress(self, job, done, note):
        if not job:
            return
        job.progress_done = done
        job.progress_note = note[:200]
        job.save(update_fields=["progress_done", "progress_note"])

    def _finish(self, job, message):
        if not job:
            return
        job.status = "succeeded"
        job.finished_at = datetime.now(dt_timezone.utc)
        job.message = message[:4000]
        job.save(update_fields=["status", "finished_at", "message"])
