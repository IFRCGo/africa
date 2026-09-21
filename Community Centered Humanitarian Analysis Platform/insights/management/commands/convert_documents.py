"""Read a job's documents with Docling, in-container, and replace their text.

    manage.py convert_documents --job 4
    manage.py convert_documents --job 4 --reload-from-cache

Mirrors extract_insights.py deliberately: the same per-document loop, the same
log discipline, the same CommandError on a run-level failure so a direct
`docker compose exec web python manage.py convert_documents` exits non-zero
rather than a quiet 0.

A PER-DOCUMENT FAILURE IS NOT A RUN FAILURE. convert_document never raises for
a bad document - it returns a Conversion with ok=False and leaves the intake
text in place. An unreadable PDF in a folder of two hundred must not take the
other 199 down. What reaches the except branch below is a real run failure -
the database went away, the disk filled - and that leaves the job at
"convert_failed" rather than wedged at "converting", which nothing but the
admin's reset action could recover.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from insights import convert
from insights.models import ExtractionJob


class Command(BaseCommand):
    help = "Convert a job's documents to per-page markdown with Docling."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, required=True)
        parser.add_argument(
            "--reload-from-cache", action="store_true", dest="reload_from_cache",
            help="Load mcp_cache/insights/converted/<sha1>.json instead of calling Docling.")

    def _log(self, job, message):
        self.stdout.write(message)
        stamp = timezone.now().isoformat(timespec="seconds")
        line = f"[{stamp}] {message}"
        job.log = f"{job.log}\n{line}" if job.log else line
        job.save(update_fields=["log"])

    def _path_of(self, document):
        """Where this document's file actually is.

        A document catalogued from a registered folder resolves under
        SOURCE_ROOT, exactly as the pipeline's do. An upload is
        "media/<sha1>-<name>", which lives under BASE_DIR.
        """
        candidate = Path(settings.SOURCE_ROOT) / document.rel_path
        if candidate.exists():
            return candidate
        return Path(settings.BASE_DIR) / document.rel_path

    def handle(self, *args, **options):
        job = ExtractionJob.objects.filter(id=options["job"]).first()
        if job is None:
            raise CommandError(f"no ExtractionJob with id {options['job']}")

        documents = list(job.documents.order_by("id"))
        job.status = "converting"
        job.started_at = timezone.now()
        job.documents_total = len(documents)
        # Re-running the same job on purpose must not inherit the previous
        # run's count - documents_done is incremented below, never set.
        job.documents_done = 0
        job.save()

        try:
            for document in documents:
                row = convert.convert_document(
                    document, self._path_of(document), job=job,
                    reload_only=options["reload_from_cache"])

                detail = f" - {row.message}" if row.message else ""
                self._log(job, f"{document.file_name}: {row.engine}, "
                               f"{row.pages} page(s){detail}")

                job.documents_done += 1
                job.save(update_fields=["documents_done"])
        except Exception as exc:
            # Only the exception's type and message are ever recorded - never
            # its repr, and never a request object an SDK exception may carry.
            message = f"{type(exc).__name__}: {exc}"
            self.stderr.write(message)
            job.log = f"{job.log}\n{message}" if job.log else message
            job.status = "convert_failed"
            job.finished_at = timezone.now()
            job.save(update_fields=["log", "status", "finished_at"])
            raise CommandError(message) from exc
        else:
            # NOT "queued". The operator has not looked at the converted text
            # yet, and step 2's whole purpose is that they can. The Continue
            # button on that page is what moves this on.
            job.status = "converted"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at"])
