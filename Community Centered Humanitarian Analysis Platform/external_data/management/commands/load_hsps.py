"""`python manage.py load_hsps` - the HSP mapping export into the database.

    docker compose exec web python manage.py load_hsps
    docker compose exec web python manage.py load_hsps --dry-run
    docker compose exec web python manage.py load_hsps --path /boundary-src/chad-maps/<newer>.xlsx

The file is found through the HSP_XLSX setting, which docker-compose already points
at the Chad Maps mount.

Each district label is resolved to a p-code against the boundary library, and the
matched polygon's point-on-surface is copied onto the row - so a map can be drawn
from this one table with no join and no second source, which is the whole point of
putting it here.

Loading a NEWER export does not overwrite the older one: date_reported is part of
the natural key, so both sets sit side by side and "what changed" is a query.
"""
from datetime import datetime

import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boundaries.models import AdminArea
from external_data.loaders.hsp import (export_date, parse_country_rows,
                                       parse_location_rows)
from external_data.models import HumanitarianServicePoint, SourceSync

UNIQUE_FIELDS = ["date_reported", "iso3", "service", "location_name"]
UPDATE_FIELDS = [
    "country", "scope", "admin_pcode", "admin_level", "match_method", "lat", "lon",
    "same_services_everywhere", "hsp_count", "kobo_uuid", "source_file",
]

# South Sudan's submission carries real p-codes in selected_districts; these are
# the three, in the order the location sheet lists them.
SSD_PCODES = {"Renk": "SS0711", "Aweil North": "SS0503", "Fashoda": "SS0702"}


def resolve_places(rows):
    """Fill admin_pcode, level and centroid from the boundary library.

    Tried in order: a known p-code, then an exact name match within the country,
    then the polygon's alternate spellings. Anything still unplaced keeps
    match_method='unmatched' and is reported by name - a district nobody can see is
    a district nobody reconciles.
    """
    isos = {r["iso3"] for r in rows if r["iso3"]}
    by_name, by_pcode = {}, {}
    for area in AdminArea.objects.filter(iso3__in=isos, kind=AdminArea.KIND_ADMIN):
        by_pcode[(area.iso3, area.pcode)] = area
        key = (area.iso3, area.name.strip().lower())
        # Shallower levels win: a district and a state sharing a name should
        # resolve to the district only if nothing coarser claimed it first.
        if key not in by_name or (area.level or 9) < (by_name[key].level or 9):
            by_name[key] = area
        for alt in area.name_alt or []:
            if alt:
                by_name.setdefault((area.iso3, str(alt).strip().lower()), area)

    unmatched = set()
    for r in rows:
        area = None
        method = "unmatched"
        pcode = SSD_PCODES.get(r["location_name"]) if r["iso3"] == "SSD" else None
        if pcode and (r["iso3"], pcode) in by_pcode:
            area, method = by_pcode[(r["iso3"], pcode)], "pcode"
        if area is None:
            area = by_name.get((r["iso3"], r["location_name"].strip().lower()))
            method = "name" if area else "unmatched"
        if area is None:
            unmatched.add(f'{r["iso3"]}:{r["location_name"]}')
            continue
        r["admin_pcode"] = area.pcode
        r["admin_level"] = area.level
        r["match_method"] = method
        r["lat"] = area.center_lat
        r["lon"] = area.center_lon
    return sorted(unmatched)


class Command(BaseCommand):
    help = "Load the Humanitarian Service Point mapping export into the database."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=None, help="Override the HSP_XLSX setting")
        parser.add_argument(
            "--date", default=None,
            help="YYYY-MM-DD to record as date_reported. Defaults to the export "
                 "timestamp in the filename, which is the only date this source has.",
        )
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    @transaction.atomic
    def handle(self, *args, **options):
        path = options["path"] or getattr(settings, "HSP_XLSX", None)
        if not path:
            raise CommandError("HSP_XLSX is not set and --path was not given.")
        from pathlib import Path
        path = Path(path)
        if not path.is_file():
            raise CommandError(f"HSP export not found: {path}")

        if options["date"]:
            reported = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            reported = export_date(path.name)
        if reported is None:
            raise CommandError(
                f"no export timestamp in '{path.name}' and no --date given. This "
                "source carries no submission date, so one of the two must supply it."
            )

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        main_rows = list(wb[wb.sheetnames[0]].iter_rows(values_only=True))
        loc_rows = (list(wb["location"].iter_rows(values_only=True))
                    if "location" in wb.sheetnames else [])
        wb.close()

        rows = parse_country_rows(main_rows, path.name, reported)
        rows += parse_location_rows(loc_rows, main_rows, path.name, reported)
        for r in rows:
            r.pop("_region", None)

        if not rows:
            raise CommandError(
                f"{path.name}: no service/district combinations found. A renamed "
                "'Services offered' or 'Districts where these services are offered' "
                "column heading looks exactly like this."
            )

        unmatched = resolve_places(rows)

        self.stdout.write(f"{path.name}")
        self.stdout.write(f"  date reported: {reported} (export timestamp)")
        self.stdout.write(f"  {len(rows)} service/place rows")
        placed = sum(1 for r in rows if r["admin_pcode"])
        self.stdout.write(f"  {placed} placed on a polygon, {len(rows) - placed} not")
        if unmatched:
            self.stdout.write("  unmatched: " + ", ".join(unmatched))

        if options["dry_run"]:
            return

        HumanitarianServicePoint.objects.bulk_create(
            [HumanitarianServicePoint(**r) for r in rows],
            update_conflicts=True,
            unique_fields=UNIQUE_FIELDS,
            update_fields=UPDATE_FIELDS,
        )

        sync, _ = SourceSync.objects.get_or_create(
            source="kobo", dataset="humanitarian_service_points",
            iso3=None, variant="hsp-mapping",
        )
        sync.tool = "xlsx export"
        sync.params = {"source_file": path.name}
        sync.last_pulled_at = datetime.now().astimezone()
        if sync.high_water_date is None or reported > sync.high_water_date:
            sync.high_water_date = reported
        sync.row_count = HumanitarianServicePoint.objects.count()
        sync.notes = (
            "District-level, not point-level: the export holds no coordinates and "
            "no per-site rows. date_reported is the export timestamp because the "
            "form carries no submission date."
        )
        sync.save()
