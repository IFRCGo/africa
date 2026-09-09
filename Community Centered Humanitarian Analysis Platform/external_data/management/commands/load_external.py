"""`python manage.py load_external <dataset> <file.json>` - cache into database.

The assistant pulls through MCP on the host and drops the raw response into
data_pipeline/mcp_cache/. This command is the other half: it reads one of those
files and upserts it into the subject tables, writing the watermark as it goes.

    load_external seasonal_calendar mcp_cache/seasonal/TCD.json --iso3 TCD
    load_external food_security     mcp_cache/ipc/TCD-89623970.geojson --iso3 TCD --dry-run

The cache file is staging, not truth. Keeping it on disk means any load can be
replayed without going back to a single MCP server.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load


class Command(BaseCommand):
    help = "Load one recorded MCP payload into the external data tables."

    def add_arguments(self, parser):
        parser.add_argument("dataset", choices=sorted(LOADERS), help="Which loader to use")
        parser.add_argument("path", help="Path to the recorded JSON payload")
        parser.add_argument("--iso3", default=None, help="Country the payload is for")
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change and write nothing.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}") from exc

        loader = LOADERS[options["dataset"]]()
        try:
            result = load(loader, payload, options["iso3"], dry_run=options["dry_run"])
        except EmptyPayload as exc:
            raise CommandError(str(exc)) from exc

        verb = "would write" if options["dry_run"] else "wrote"
        self.stdout.write(f"{verb} {result.written} rows to {loader.model._meta.db_table}")
        if result.high_water_date:
            self.stdout.write(f"  data now held to {result.high_water_date}")
