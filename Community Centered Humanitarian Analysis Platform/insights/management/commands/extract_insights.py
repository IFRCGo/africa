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
be re-tried rather than trusting a false "loaded" with nothing written.

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
                        self.stderr.write(f"{document.file_name}: {exc}")
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
        else:
            job.status = "loaded"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at"])
