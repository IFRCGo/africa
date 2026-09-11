"""Load one payload file, or every payload in mcp_cache/insights/.

    manage.py load_insights                       # everything not yet loaded
    manage.py load_insights path/to/one.json      # just this one
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from data_track.models import Document
from insights.contract import ContractError
from insights.loader import load
from insights.models import ExtractionJob


def payload_dir():
    return Path(settings.MCP_CACHE_DIR) / "insights"


class Command(BaseCommand):
    help = "Load community-insight payloads written by an extraction agent."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="One payload file. Default: all of them.")
        parser.add_argument("--job", type=int, help="Attribute the load to this ExtractionJob.")

    def handle(self, *args, **options):
        if options["path"]:
            files = [Path(options["path"])]
        else:
            files = sorted(payload_dir().glob("*.json"))
        if not files:
            raise CommandError(f"no payloads found in {payload_dir()}")

        job = ExtractionJob.objects.filter(id=options["job"]).first() if options["job"] else None

        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rel = (payload.get("source") or {}).get("rel_path")
            document = Document.objects.filter(rel_path=rel).first() if rel else None
            if rel and document is None:
                self.stderr.write(f"{path.name}: no document with rel_path {rel!r}; skipped")
                continue
            try:
                report = load(payload, document, job=job)
            except ContractError as exc:
                self.stderr.write(f"{path.name}: {exc}")
                continue
            self.stdout.write(
                f"{path.name}: {report.written} written, "
                f"{report.rejected_unverifiable} unverifiable, "
                f"{report.skipped_reviewed} already reviewed"
            )

        if job is not None:
            job.status = "loaded"
            job.save(update_fields=["status"])
