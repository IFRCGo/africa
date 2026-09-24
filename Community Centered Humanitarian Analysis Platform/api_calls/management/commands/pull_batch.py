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

from external_data.fetchers.base import redact
from external_data.models import SourceSync
from api_calls.locks import JobBusy, claim
from api_calls.models import ACTIVE
from api_calls.views import pullable, refresh_argv, row_label


class Command(BaseCommand):
    help = "Refresh several data sources, strictly one at a time."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, default=None,
                            help="PullJob id (kind='batch') to record against")
        parser.add_argument("--rows", default="",
                            help="Comma-separated source_sync ids, in order")

    def handle(self, *args, **options):
        from api_calls.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        ids = [int(i) for i in options["rows"].split(",") if i.strip()]
        rows = sorted(SourceSync.objects.filter(pk__in=ids), key=lambda r: ids.index(r.pk))

        if job:
            job.status = "running"
            job.started_at = datetime.now(dt_timezone.utc)
            job.progress_total = len(rows)
            job.save(update_fields=["status", "started_at", "progress_total"])

        batch_user = job.requested_by if job else None
        pulled = failed = skipped = 0
        try:
            for index, row in enumerate(rows, start=1):
                label = row_label(row)
                self._progress(job, index - 1, f"{label} ...")
                self._item(job, index - 1, "running")

                why = self._unpullable(row)
                if why:
                    skipped += 1
                    self.stdout.write(f"skip {label}: {why}")
                    self._progress(job, index, f"skipped {label}")
                    # The reason, which until now reached stdout and nowhere a
                    # person looks.
                    self._item(job, index - 1, "skipped", why)
                    continue

                self.stdout.write(f"--- {label}")

                # EVERY ROW GETS ITS OWN JOB, and that is not bookkeeping for
                # its own sake: the status column on the data sources page reads
                # the latest job for a row. Without one, a batch would refresh
                # eight countries, move every freshness date, and leave all
                # eight rows still showing a dash - the pull having visibly
                # done nothing.
                #
                # Claimed one at a time, and closed before the next row starts:
                # uniq_active_job_per_source allows exactly one active job per
                # source, and a batch of eight FEWS NET countries would breach
                # it the moment two overlapped.
                try:
                    row_job = claim("pull", source=row.source, dataset=row.dataset,
                                    iso3=row.iso3, variant=row.variant,
                                    user=batch_user, parent=job)
                except JobBusy as exc:
                    # Somebody pressed Pull on this source while the batch was
                    # running. Their job is doing the work; skipping is right,
                    # and taking the whole batch down with an IntegrityError is
                    # not.
                    skipped += 1
                    self.stdout.write(f"    skipped: {exc}")
                    self._progress(job, index, f"skipped {label}")
                    self._item(job, index - 1, "skipped", str(exc))
                    continue

                try:
                    # In-process, so the command's own guarantees apply - for an
                    # API row, refresh_external's fetch, save, load, watermark
                    # last, redact on the way out; for a workbook row,
                    # load_workbooks' one transaction and its file fingerprint.
                    #
                    # WHICH command comes from api_calls.views.refresh_argv, the same
                    # answer the button on the list uses. Hard-coding
                    # refresh_external here is how an excel row admitted by
                    # stale_rows() would fail inside every batch while its own
                    # button worked.
                    argv = refresh_argv(row, row_job.id)
                    call_command(*argv)
                    pulled += 1
                    self._item(job, index - 1, "succeeded")
                except Exception as exc:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"    failed: {redact(exc)}"))
                    # Redacted on the way out, like every other message this
                    # command writes: `items` is served to a browser.
                    self._item(job, index - 1, "failed", str(redact(exc)))
                finally:
                    # refresh_external closes the job itself on both paths, but
                    # a crash before it got that far would leave the row job
                    # active and hold the source against every later press.
                    row_job.refresh_from_db()
                    if row_job.status in ACTIVE:
                        row_job.status = "failed"
                        row_job.finished_at = datetime.now(dt_timezone.utc)
                        row_job.message = row_job.message or "ended without reporting"
                        row_job.save(update_fields=["status", "finished_at", "message"])
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
        """Why this row cannot be refreshed, or None if it can.

        api_calls.views.pullable, not a copy of it. The admin filters a selection with
        that function before launching; a second rule here that disagreed would
        skip rows the operator had just been told would be pulled.
        """
        return pullable(row)

    def _item(self, job, index, status, message=""):
        """Mark one row of the plan: pending -> running -> what became of it.

        A batch launched before this column existed, or one whose plan is short
        of a row, is simply left alone - the tally at the end still tells the
        truth, and a missing entry is not worth an exception inside a loop whose
        whole design is that one row's trouble costs no other row. Hence the
        re-read: `items` is asked for rather than assumed.
        """
        if not job:
            return
        job.refresh_from_db(fields=["items"])
        items = job.items or []
        if not 0 <= index < len(items):
            return
        items[index] = dict(items[index], status=status, message=message[:200])
        job.items = items
        job.save(update_fields=["items"])

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
