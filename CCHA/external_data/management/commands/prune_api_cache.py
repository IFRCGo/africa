"""Delete cached payloads whose rows are already in the database.

    manage.py prune_api_cache              # report only, deletes nothing
    manage.py prune_api_cache --delete     # actually remove them

WHY THIS IS SAFE FOR SOME FOLDERS AND NOT OTHERS. api_cache/ holds three
different kinds of thing, and only one of them is disposable:

  a staging copy   the raw payload a pull landed in before the loader put it
                   in Postgres. Once source_sync says the load happened and
                   the table has rows, this file is a duplicate: pressing Pull
                   now fetches it again. THESE are what this command removes.

  a referenced     job logs under api/ are named by PullJob.log_path, and the
  artefact         markdown under insights/ by Conversion.markdown_path, both
                   as ABSOLUTE paths. Deleting these does not free a duplicate,
                   it breaks a page. NEVER TOUCHED.

  an input         the loose .geojson at the top level were read INTO the
                   boundary library from shapefiles elsewhere; admin_areas does
                   not point back at them, but neither are they a pull's
                   output, and no Pull now button rebuilds them. Reported as
                   "not a pull" and left alone unless --include-orphans.

A folder whose source has NO rows in the database is also left alone, loudly:
that is either a pull that failed or a payload nothing has loaded yet, and
either way it is the one copy in existence.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from external_data.models import SourceSync

# cache folder -> the source_sync rows that prove its contents were loaded.
# A folder absent here is never deleted, whatever it holds.
PULL_FOLDERS = {
    "dtm_snapshots": {"source": "dtm"},
    "unhcr_situations": {"source": "unhcr-odp"},
    "hdx_idps": {"source": "hdx", "dataset": "idps"},
    "hdx_refugees": {"source": "unhcr", "dataset": "refugees"},
    "ipc": {"source__in": ["ipc", "ch"]},
    "fewsnet_phases": {"source": "fewsnet", "dataset": "food_security"},
    "fewsnet_seasons": {"source": "fewsnet", "dataset": "seasonal_calendar"},
    "seasonal": {"source": "acaps"},
    "montandon": {"source": "montandon"},
}

# Named so the report can say why, rather than leaving them unexplained.
REFERENCED = {
    "api": "job logs - PullJob.log_path names these files absolutely",
    "insights": "Docling markdown - Conversion.markdown_path names these",
}


def folder_size(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1:.1f} {unit}"
        n /= 1024


class Command(BaseCommand):
    help = "Remove cached payloads whose data is already loaded. Reports by default."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true",
                            help="actually remove the files (default: report only)")
        parser.add_argument("--include-orphans", action="store_true",
                            help="also remove top-level files that no pull produced")

    def handle(self, *args, **options):
        root = Path(settings.API_CACHE_DIR)
        if not root.exists():
            self.stdout.write(f"{root} does not exist; nothing to do.")
            return

        freed = 0
        keep_bytes = 0

        self.stdout.write(self.style.MIGRATE_HEADING("Loaded - safe to remove"))
        for name, query in sorted(PULL_FOLDERS.items()):
            folder = root / name
            if not folder.exists():
                continue
            size = folder_size(folder)
            rows = sum(s.row_count for s in SourceSync.objects.filter(**query))
            files = sum(1 for f in folder.rglob("*") if f.is_file())
            if rows <= 0:
                keep_bytes += size
                self.stdout.write(
                    f"  KEEP  {name:20} {human(size):>9}  {files:>3} files  "
                    f"- nothing loaded from it; this is the only copy")
                continue
            self.stdout.write(
                f"  {'DROP' if options['delete'] else 'would drop'}  "
                f"{name:20} {human(size):>9}  {files:>3} files  "
                f"- {rows:,} rows in the database")
            freed += size
            if options["delete"]:
                for f in sorted(folder.rglob("*"), reverse=True):
                    f.unlink() if f.is_file() else f.rmdir()
                folder.rmdir()

        self.stdout.write(self.style.MIGRATE_HEADING("Referenced elsewhere - never removed"))
        for name, why in sorted(REFERENCED.items()):
            folder = root / name
            if folder.exists():
                keep_bytes += folder_size(folder)
                self.stdout.write(f"  KEEP  {name:20} "
                                  f"{human(folder_size(folder)):>9}  - {why}")

        loose = [f for f in root.iterdir() if f.is_file()]
        if loose:
            size = sum(f.stat().st_size for f in loose)
            self.stdout.write(self.style.MIGRATE_HEADING(
                "Not a pull's output - inputs and superseded files"))
            self.stdout.write(
                f"  {'DROP' if options['include_orphans'] and options['delete'] else 'KEEP'}"
                f"  {'(top level)':20} {human(size):>9}  {len(loose):>3} files")
            for f in sorted(loose, key=lambda p: -p.stat().st_size)[:6]:
                self.stdout.write(f"          {f.name:52} {human(f.stat().st_size):>9}")
            if options["include_orphans"]:
                freed += size
                if options["delete"]:
                    for f in loose:
                        f.unlink()
            else:
                keep_bytes += size
                self.stdout.write("          (pass --include-orphans to remove these too)")

        self.stdout.write("")
        verb = "freed" if options["delete"] else "would free"
        self.stdout.write(self.style.SUCCESS(
            f"  {verb} {human(freed)}; keeping {human(keep_bytes)}"))
        if not options["delete"]:
            self.stdout.write("  Nothing was deleted. Re-run with --delete to do it.")
