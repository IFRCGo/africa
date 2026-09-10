"""`python manage.py load_workbooks` - the two Excel workbooks into the database.

    docker compose exec web python manage.py load_workbooks
    docker compose exec web python manage.py load_workbooks --dry-run

These two files are maintained by hand beside the PDFs, so they have no MCP call
behind them and no date to ask a server for. Their watermark is the file itself:
`params` records each workbook's sha1 and modification time, which is how a later
run can tell "unchanged since last load" from "never loaded".

Both are read in full every time. They are small, and a full re-read is the only
way to notice that somebody corrected a figure in an old sheet.
"""
import hashlib
from datetime import datetime, timezone

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from external_data.loaders.excel import parse_idp_states_sheet, parse_neighbours_sheet
from external_data.models import MovementPattern, SourceSync

UNIQUE_FIELDS = [
    "source", "metric", "iso3", "admin_pcode", "place_name", "date",
    "population_group",
]
UPDATE_FIELDS = [
    "admin_level", "value", "unit", "source_dataset",
    "reference_period_start", "reference_period_end", "lat", "lon",
]

# (filename, which parser, read every sheet?, source_sync identity)
WORKBOOKS = [
    ("neighbouring countries Pop movement data.xlsx", parse_neighbours_sheet, True,
     {"source": "excel", "dataset": "refugees", "iso3": None,
      "variant": "neighbours-workbook"}),
    ("Sudan IDPs.xlsx", parse_idp_states_sheet, False,
     {"source": "excel", "dataset": "idps", "iso3": "SDN",
      "variant": "sudan-idps-workbook"}),
]


# Workbook spellings the boundary library writes differently. Kept deliberately
# short: an alias here is a fact about one file, and every entry added without
# checking the library first is a place quietly filed under the wrong polygon.
WORKBOOK_ALIASES = {
    ("SDN", 1, "nile"): "river nile",
}


def resolve_pcodes(rows):
    """Fill admin_pcode from the boundary library, by name, within one country.

    The workbook names states and nothing else - "North Darfur", not "SD03". The
    library already holds those nineteen polygons with their p-codes and their
    alternate spellings, which is exactly what it was built for, so the join costs
    one query rather than another hand-maintained lookup table.

    A name that does not match is left with a null p-code and reported. It is not
    an error: the row is still a real observation, it simply cannot be drawn on a
    polygon until somebody reconciles the spelling.
    """
    from boundaries.models import AdminArea

    wanted = {(r["iso3"], r["admin_level"]) for r in rows if r.get("place_name")}
    lookup = {}
    for iso3, level in wanted:
        for area in AdminArea.objects.filter(iso3=iso3, level=level):
            lookup[(iso3, level, area.name.strip().lower())] = area.pcode
            for alt in area.name_alt or []:
                if alt:
                    lookup.setdefault((iso3, level, str(alt).strip().lower()), area.pcode)

    unmatched = set()
    for r in rows:
        if r.get("admin_pcode") or not r.get("place_name"):
            continue
        key = (r["iso3"], r["admin_level"], r["place_name"].strip().lower())
        key = key[:2] + (WORKBOOK_ALIASES.get(key, key[2]),)
        pcode = lookup.get(key)
        if pcode:
            r["admin_pcode"] = pcode
        elif r["admin_level"]:
            unmatched.add(r["place_name"])
    return sorted(unmatched)


def _fingerprint(path):
    """sha1 and mtime - the workbook equivalent of a high-water date."""
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "sha1": digest.hexdigest(),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "bytes": path.stat().st_size,
    }


class Command(BaseCommand):
    help = "Load the two hand-maintained Excel workbooks into movement_patterns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change and write nothing.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        root = settings.SOURCE_ROOT
        for filename, parse, all_sheets, key in WORKBOOKS:
            path = root / filename
            if not path.is_file():
                raise CommandError(
                    f"workbook not found: {path}. It is expected beside the PDFs, in "
                    f"the folder SOURCE_ROOT points at."
                )

            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            sheets = wb.worksheets if all_sheets else wb.worksheets[:1]
            rows = []
            for ws in sheets:
                rows.extend(parse(ws))
            wb.close()

            if not rows:
                # Same rule as the MCP loaders: nothing readable is a failure, not
                # a quiet success that advances the watermark.
                raise CommandError(
                    f"{filename}: no usable rows. Check the column headings - "
                    f"a renamed 'Data Date' or 'Population (DD Mon YYYY)' looks "
                    f"exactly like this."
                )

            unmatched = resolve_pcodes(rows)

            # One workbook can legitimately repeat a country and date across sheets;
            # the later sheet wins, matching s07's "latest value for the same date".
            deduped = {tuple(r[f] for f in UNIQUE_FIELDS): r for r in rows}
            collapsed = len(rows) - len(deduped)
            rows = list(deduped.values())

            self.stdout.write(f"{filename}: {len(rows)} rows")
            if collapsed:
                self.stdout.write(f"  {collapsed} duplicate observations collapsed")
            if unmatched:
                # Named, not counted: a spelling nobody can see is a spelling
                # nobody fixes.
                self.stdout.write(
                    f"  {len(unmatched)} place names matched no polygon: "
                    + ", ".join(unmatched)
                )
            if options["dry_run"]:
                continue

            MovementPattern.objects.bulk_create(
                [MovementPattern(**r) for r in rows],
                update_conflicts=True,
                unique_fields=UNIQUE_FIELDS,
                update_fields=UPDATE_FIELDS,
            )

            sync, _ = SourceSync.objects.get_or_create(**key)
            sync.tool = "openpyxl"
            sync.params = _fingerprint(path)
            sync.last_pulled_at = datetime.now(timezone.utc)
            latest = max(r["date"] for r in rows)
            if sync.high_water_date is None or latest > sync.high_water_date:
                sync.high_water_date = latest
            sync.row_count = MovementPattern.objects.filter(
                source="excel", source_dataset=filename
            ).count()
            sync.notes = "maintained by hand; re-read in full on every load"
            sync.save()
            self.stdout.write(f"  data now held to {sync.high_water_date}")
