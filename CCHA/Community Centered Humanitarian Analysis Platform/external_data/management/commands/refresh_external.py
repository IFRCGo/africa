"""`python manage.py refresh_external <source> <dataset> --iso3 XXX`

Fetch, save, then load - the rule CLAUDE.md states for the agent, kept by the
application. The command is the feature and the admin button is a caller, which
is how this gets tested and how it would be scheduled if that is ever wanted.

    docker compose exec web python manage.py refresh_external fewsnet \\
        seasonal_calendar --iso3 TCD

ONE CALL AT A TIME. The fetcher's plan() is a generator and it is consumed with a
plain for-loop. Do not gather, map or thread it: two IPC countries in parallel
closed the connection and took that server down for a whole session.
"""
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from external_data.fetchers import fetcher_for
# The module, not the names: `from ... import http_get_json` binds a second
# reference here, and patching the original in tests would then leave this one
# pointing at the real function - which is how a test suite starts quietly
# calling live humanitarian APIs. One door, reached through the module.
from external_data.fetchers import base
from external_data.fetchers.base import missing_keys, redact, save_payload
from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load
from external_data.models import SourceSync


class Command(BaseCommand):
    help = "Fetch one external source into the database, and record the attempt."

    def add_arguments(self, parser):
        parser.add_argument("source", help="e.g. fewsnet")
        parser.add_argument("dataset", help="e.g. seasonal_calendar")
        parser.add_argument("--iso3", default=None)
        parser.add_argument("--variant", default="")
        parser.add_argument("--job", type=int, default=None,
                            help="PullJob id to record progress against")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **options):
        from api_calls.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        if job:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.save(update_fields=["status", "started_at"])

        try:
            written = self._run(options, job)
        except Exception as exc:
            # Every failure route ends here, so there is exactly one place that
            # writes a failure onto the job - and exactly one place that has to
            # remember to redact.
            self._finish(job, "failed", message=redact(exc))
            raise CommandError(redact(exc)) from None

        message = ("already up to date - nothing new published"
                   if getattr(self, "_uptodate", False) else f"wrote {written} rows")
        self._finish(job, "succeeded", rows=written, message=message)
        self.stdout.write(message)
        return None

    def _run(self, options, job=None):
        source, dataset = options["source"], options["dataset"]
        variant = options["variant"] or ""

        sync = SourceSync.objects.filter(
            source=source, dataset=dataset, iso3=options["iso3"], variant=variant,
        ).first()
        if sync is None:
            raise CommandError(
                f"no source_sync row for {source}/{dataset} "
                f"{options['iso3'] or 'global'} '{variant}'"
            )

        fetcher_cls = fetcher_for(source, dataset, variant)
        if fetcher_cls is None:
            raise CommandError(
                f"no fetcher for {source}/{dataset} '{variant}'. This source is "
                "file-based - load it with its own command."
            )

        absent = missing_keys(fetcher_cls)
        if absent:
            raise CommandError(
                f"{', '.join(absent)} is not set. Add it to .env and restart the "
                "web container; nothing was called."
            )

        fetcher = fetcher_cls()
        written = 0
        failures = []
        uptodate = []

        # Materialised so the job can say "3 of 7" instead of spinning. For IPC
        # this performs the analyses listing and nothing else - the area fetches
        # still happen one at a time, in the loop below, which is the rule that
        # matters.
        calls = list(fetcher.plan(sync))
        self._progress(job, done=0, total=len(calls), note="starting")

        # A PLAN THAT YIELDS NOTHING IS A THIRD OUTCOME, and it belongs here
        # rather than at the bottom. An id-keyed source - DTM's snapshots -
        # asks the catalogue what exists, finds every id already in known_ids,
        # and has nothing to fetch. That is a successful, complete refresh.
        #
        # It still has to be RECORDED as an attempt. last_pulled_at is written
        # by the loader, inside load(), and the loader never runs when there is
        # nothing to load - so without this the row reads "never pulled" for
        # ever and views.stale_rows() puts it back in every batch. SourceSync's
        # own docstring states that last_pulled_at moves on every attempt; this
        # is what keeps that true for a source with nothing to do.
        if not calls:
            if not options["dry_run"]:
                SourceSync.objects.filter(pk=sync.pk).update(
                    last_pulled_at=datetime.now(timezone.utc),
                    params=fetcher.params_record())
            self._uptodate = True
            return 0

        for index, call in enumerate(calls, start=1):
            self.stdout.write(f"GET {call.url}")
            # One door. GET or POST, paged or not, is the Call's business -
            # the runner's business is that they happen ONE AT A TIME.
            payload = base.fetch(call)
            path = save_payload(call.cache_path, payload)
            self.stdout.write(f"  saved {path}")

            loader = LOADERS[call.loader_dataset]()
            try:
                # ONE CALL IS ONE TRANSACTION, not one job. Rolling six good IPC
                # analyses back because the seventh was an empty projection
                # update would throw away 8-15 MB of successful work per failure
                # and let one bad analysis poison a whole country.
                result = load(loader, payload, sync.iso3,
                              dry_run=options["dry_run"], context=call.context)
            except EmptyPayload as exc:
                if call.narrowed:
                    # NOTHING NEW IS NOT A FAULT. "Loud on empty" exists so an
                    # API error serialised as [] can never be recorded as a
                    # successful, up-to-date pull - but once the question was
                    # "anything since June?", an empty answer is the ordinary
                    # way of saying no. Only an UNNARROWED empty is still a
                    # failure, which is exactly where the guarantee was aimed.
                    uptodate.append(call)
                    self.stdout.write("  nothing new")
                    self._progress(job, done=index, note="up to date")
                    continue
                failures.append((call, exc))
                self.stdout.write(self.style.WARNING(f"  empty: {exc}"))
                self._note_empty(fetcher, sync, call)
                self._progress(job, done=index, note="empty")
                continue

            written += result.written
            self.stdout.write(f"  loaded {result.written} rows")
            self._progress(job, done=index, note=f"{written} rows so far")

        if failures and not written:
            raise EmptyPayload(
                f"{len(failures)} call(s) produced no rows and none succeeded: "
                f"{failures[0][1]}"
            )
        if failures:
            raise EmptyPayload(
                f"{written} rows loaded, but {len(failures)} call(s) were empty: "
                f"{failures[0][1]}"
            )

        if not options["dry_run"]:
            SourceSync.objects.filter(pk=sync.pk).update(params=fetcher.params_record())

        self._uptodate = bool(uptodate) and not written
        return written

    def _note_empty(self, fetcher, sync, call):
        """Let a fetcher record that one of its Calls came back empty.

        IPC uses this to add an analysis id to skipped_ids, so a projection
        update that publishes no geometry is not re-fetched on every press. Other
        fetchers do not implement it and nothing happens.
        """
        hook = getattr(fetcher, "note_empty", None)
        if hook:
            hook(sync, call)

    def _progress(self, job, done=None, total=None, note=""):
        """Record how far along this job is, so the banner can say something true.

        Written on the row rather than parsed out of the log: a banner that
        scrapes stdout breaks the first time a message is reworded.
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
