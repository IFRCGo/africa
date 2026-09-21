"""Run extraction in-container for one job, then load the result.

    manage.py extract_insights --job 4

Every payload is still written to mcp_cache/insights/ before it is loaded, so an
in-container run leaves exactly the same evidence on disk as an agent on the host
does, and can be re-loaded without re-paying for the model.

Extracts ONLY the documents attached to this job (ExtractionJob.documents,
R13a) - not every document ever catalogued into the insights collection, which
would re-pay the model for the whole archive on every run and let a job for
one folder extract another folder's documents too.

A TRANSPORT/SDK FAILURE ENDS THE JOB, IT DOES NOT WEDGE IT (fix-round,
2026-09-14). Each adapter lets a connection failure, rate limit, auth
failure or 5xx propagate out of its own extract() rather than swallow it as
a chunk problem - see the "TRANSPORT VS RESPONSE-SHAPE ERRORS" note in
anthropic_api.py and openai_compatible.py. That exception is caught here,
once, around the whole per-document loop: whatever chunk problems the dying
document had already recorded are flushed to the job log before the
exception is allowed to end the run, the job is marked "failed" rather than
left at "running", and a human can tell at a glance that this run needs to
be re-tried rather than trusting a false "loaded" with nothing written. The
job's state is then re-raised as a CommandError, so CLAUDE.md's own
`docker compose exec web python manage.py <command>` invoked directly also
sees a non-zero exit rather than a quiet 0 - CommandError specifically,
because Django's run_from_argv prints only str(exc) for one and no
traceback, keeping "type and message only, never a raw traceback or the
underlying request object" true for a human reading the terminal too, not
just for what lands in job.log.

A job that instead has its PROCESS killed outright - `docker compose restart
web` kills a detached child (R13b's start_new_session=True) with no
exception anywhere in this codebase to catch it - cannot be recovered by any
of the above, because nothing here ever runs to catch it. That is what
ExtractionJobAdmin's "Reset stuck job to queued" action is for.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from data_track.models import DocumentText
from insights.contract import ContractError
from insights.extractors import get_extractor
from insights.loader import load
from insights.models import ExtractionJob


class Command(BaseCommand):
    help = "Extract community insights from a job's documents using the configured model."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, required=True)

    def _flush_problems(self, job, extractor):
        """Write every problem recorded on `extractor` since the last flush to
        the job's log and to stdout, then clear them.

        Called after every extract() call that returns normally, AND from
        the except branch below before a transport failure is allowed to end
        the run - otherwise the refusals and parse failures already recorded
        for the chunks that succeeded before the one that killed the call
        would vanish with it. That is exactly the silent loss
        task-13-rulings.md §2 exists to rule out; a document dying partway
        through must not cost the record of what happened to the part that
        didn't.
        """
        if not extractor.problems:
            return
        for problem in extractor.problems:
            self.stdout.write(self.style.WARNING(problem))
        stamp = timezone.now().isoformat(timespec="seconds")
        new_lines = "\n".join(f"[{stamp}] {problem}" for problem in extractor.problems)
        job.log = f"{job.log}\n{new_lines}" if job.log else new_lines
        job.save(update_fields=["log"])
        extractor.problems = []

    def handle(self, *args, **options):
        job = ExtractionJob.objects.filter(id=options["job"]).first()
        if job is None:
            raise CommandError(f"no ExtractionJob with id {options['job']}")

        extractor = get_extractor()
        out_dir = Path(settings.MCP_CACHE_DIR) / "insights"
        out_dir.mkdir(parents=True, exist_ok=True)

        documents = list(job.documents.order_by("id"))
        # Payloads this run could not load. A run that rejected everything must
        # not end up looking like a run that found nothing to say.
        rejected = []
        job.status = "running"
        job.producer = extractor.name
        job.model_used = extractor.model
        job.started_at = timezone.now()
        job.documents_total = len(documents)
        # Re-running the SAME job on purpose (§5) must not inherit the
        # previous run's counts - every one of these is incremented, never
        # set, by the code below (documents_done here) and by loader.load()
        # (the other three - shared with load_payloads_for_job, where
        # accumulating across several payload FILES in one action is
        # correct, so the reset belongs here, not in the loader). Without
        # this a second run of a 1-insight job would show documents_done=2
        # and insights_proposed=2 on the only progress columns a reviewer
        # has (ExtractionJobAdmin.list_display) - and
        # insights_rejected_unverifiable is documented on the model itself
        # as "a direct per-run measurement", which a number carried over
        # from a previous run directly contradicts.
        job.documents_done = 0
        job.insights_proposed = 0
        job.insights_rejected_unverifiable = 0
        job.insights_skipped_reviewed = 0
        # The three drop counters are per-run for the same reason, and a stale
        # one is worse than an untidy one: these are the evidence for how well
        # a given model reads the vocabulary. A re-run of the South Darfur job
        # that dropped nothing still reported codings_rejected=2 from the run
        # before it.
        job.codings_rejected = 0
        job.figures_rejected = 0
        job.movements_rejected = 0
        job.save()

        try:
            for document in documents:
                pages = list(DocumentText.objects.filter(document=document)
                             .order_by("page").values_list("page", "text"))

                try:
                    payload = extractor.extract(document, pages)
                except Exception:
                    self._flush_problems(job, extractor)
                    raise

                self._flush_problems(job, extractor)

                if payload["insights"]:
                    path = out_dir / f"{Path(document.rel_path).stem}.json"
                    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
                    try:
                        report = load(payload, document, job=job,
                                      model_used=extractor.model)
                        self.stdout.write(
                            f"{document.file_name}: {report.written} pending, "
                            f"{report.rejected_unverifiable} unverifiable")
                    except ContractError as exc:
                        # NOT stderr only. A payload the contract refuses is a
                        # whole document's worth of extraction thrown away, and
                        # the wizard reads job.log - never this process's
                        # stderr, which goes to a detached log file nobody
                        # opens. On MSF's "Voices from South Darfur"
                        # (2026-09-21) that silence meant 30 insights were
                        # discarded while the job still reported "loaded" with
                        # nothing in it: on the wizard, step 4 with an empty
                        # review queue and no stated reason.
                        #
                        # Recorded through _flush_problems rather than written
                        # here as well: that helper is the one place a problem
                        # reaches both the terminal and job.log, and writing it
                        # twice printed every rejection twice.
                        message = f"{document.file_name}: payload rejected - {exc}"
                        rejected.append(message)
                        extractor.problems.append(message)
                        self._flush_problems(job, extractor)
                else:
                    self.stdout.write(f"{document.file_name}: nothing to extract")

                job.documents_done += 1
                job.save(update_fields=["documents_done"])
        except Exception as exc:
            # A transport/SDK failure (see the module docstring) reaching
            # here has already exhausted whatever retries the adapter itself
            # has - it is not transient, and must not leave the job sitting
            # at "running" forever: ExtractionJobAdmin.run_extraction_now
            # refuses to launch a second extraction of an already-"running"
            # job, so a wedged job is a job nobody can re-try without hand-
            # editing the database.
            #
            # Only the exception's type and message are ever recorded - never
            # its repr, and never the request/response object some SDK
            # exceptions carry, which can carry the Authorization header,
            # which carries LLM_API_KEY (task-13-rulings.md §7).
            message = f"{type(exc).__name__}: {exc}"
            self.stderr.write(message)
            job.log = f"{job.log}\n{message}" if job.log else message
            job.status = "failed"
            job.finished_at = timezone.now()
            job.save(update_fields=["log", "status", "finished_at"])
            # The job's own state is already written above - that is what
            # ExtractionJobAdmin reads. This raise is for the OTHER caller
            # CLAUDE.md documents: `docker compose exec web python manage.py
            # extract_insights --job N` run directly. CommandError specifically
            # (not a bare `raise`) is what keeps this from undercutting the
            # "type and message only" rule just above it: Django's
            # run_from_argv catches CommandError and writes only str(exc) to
            # stderr with no traceback, then exits non-zero - so the caller
            # gets an honest failing exit code without the raw exception (and
            # whatever it dragged in, e.g. an SDK error's underlying request)
            # ever reaching the terminal.
            raise CommandError(message) from exc
        else:
            # "loaded" is what wizard.job_step sends to step 4, the review
            # queue; "failed" goes to step 3, whose page shows the tail of this
            # log and says the reason is at the end of it. So a run that
            # rejected one document's payload and loaded another's stays
            # "loaded" - failing it would hide the insights that DID load -
            # while a run that loaded nothing at all is failed, which is the
            # honest answer and the one that puts the reason in front of a
            # person.
            loaded_nothing = bool(rejected) and job.insights_proposed == 0
            job.status = "failed" if loaded_nothing else "loaded"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at"])
            if loaded_nothing:
                # Same reason the transport-failure branch above raises: a job
                # that ends "failed" must also exit non-zero for CLAUDE.md's
                # documented `manage.py extract_insights --job N`.
                raise CommandError(
                    f"job {job.id}: every payload was rejected and nothing was "
                    f"loaded. The reasons are in the job log: "
                    + "; ".join(rejected))
