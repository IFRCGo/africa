"""`python manage.py load_external <dataset> <file.json>` - cache into database.

The assistant pulls through MCP on the host and drops the raw response into
data_pipeline/api_cache/. This command is the other half: it reads one of those
files and upserts it into the subject tables, writing the watermark as it goes.

    load_external seasonal_calendar api_cache/seasonal/TCD.json --iso3 TCD
    load_external food_security     api_cache/ipc/TCD-89623970.geojson --iso3 TCD --dry-run

The cache file is staging, not truth. Keeping it on disk means any load can be
replayed without going back to a single MCP server.
"""
import json
import re
from datetime import date
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
            "--period", default=None,
            help="YYYY-MM the analysis describes. IPC payloads do not carry it; "
                 "without this it is read from the filename (ipc_area_YYYY-MM...).",
        )
        parser.add_argument("--title", default="", help="Analysis title, for the record")
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change and write nothing.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")

        if path.suffix.lower() == ".csv":
            # ACAPS publishes this calendar as a CSV export as well as through the
            # MCP, and the records are identical - so the same loader reads both
            # and an analyst can hand over a download without a conversion step.
            from external_data.loaders.acaps_seasonal import read_csv
            payload = read_csv(path)
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise CommandError(f"{path} is not valid JSON: {exc}") from exc

        loader = LOADERS[options["dataset"]]()
        context = {
            "period_date": _period_date(options["period"], path),
            "analysis_title": options["title"],
        }
        try:
            result = load(loader, payload, options["iso3"],
                          dry_run=options["dry_run"], context=context)
        except EmptyPayload as exc:
            raise CommandError(str(exc)) from exc

        verb = "would write" if options["dry_run"] else "wrote"
        self.stdout.write(f"{verb} {result.written} rows to {loader.model._meta.db_table}")
        if result.high_water_date:
            self.stdout.write(f"  data now held to {result.high_water_date}")


def _period_date(explicit, path):
    """The first day of the period, from --period or from the filename.

    Returns None rather than guessing today's date: a wrong period silently files
    an analysis under the wrong month, which is worse than a load that stops.
    """
    text = explicit or path.name
    m = re.search(r"(\d{4})-(\d{2})", text)
    return date(int(m[1]), int(m[2]), 1) if m else None
