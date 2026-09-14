"""Run extraction in-container for one job, then load the result.

    manage.py extract_insights --job 4

Every payload is still written to mcp_cache/insights/ before it is loaded, so an
in-container run leaves exactly the same evidence on disk as an agent on the host
does, and can be re-loaded without re-paying for the model.

Extracts ONLY the documents attached to this job (ExtractionJob.documents,
R13a) - not every document ever catalogued into the insights collection, which
would re-pay the model for the whole archive on every run and let a job for
one folder extract another folder's documents too.
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
        job.save()

        for document in documents:
            pages = list(DocumentText.objects.filter(document=document)
                         .order_by("page").values_list("page", "text"))
            payload = extractor.extract(document, pages)

            # Refusals and malformed chunks never disappear silently (spec
            # §8.2, task-13-rulings.md §2-4): there is no model field for
            # them, so they go to the job's own log text field, and to
            # stdout so a live "docker compose logs" or the Admin action's
            # redirected log file shows them as the run happens.
            if extractor.problems:
                for problem in extractor.problems:
                    self.stdout.write(self.style.WARNING(problem))
                stamp = timezone.now().isoformat(timespec="seconds")
                new_lines = "\n".join(f"[{stamp}] {problem}" for problem in extractor.problems)
                job.log = f"{job.log}\n{new_lines}" if job.log else new_lines
                job.save(update_fields=["log"])

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

        job.status = "loaded"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
