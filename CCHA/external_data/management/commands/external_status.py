"""`python manage.py external_status` - what external data is held, and how fresh.

This is the FIRST command of any refresh. It answers the only question that matters
before making an MCP call: what does the database already have?

    docker compose exec web python manage.py external_status
    docker compose exec web python manage.py external_status --json

Two dates are shown per row and they mean different things. "pulled" is when we last
asked. "data to" is the newest data we actually hold. A source that publishes
annually will show a recent pull and an old data date, and that is correct rather
than a fault - which is why `notes` is printed beside them.
"""
import json

from django.core.management.base import BaseCommand

from external_data.models import SourceSync


def status_rows():
    """Every watermark as a plain dict.

    Shared with /api/sync/ in external_data.views, so the command and the API can
    never drift into disagreeing about what is held.
    """
    return [
        {
            "source": r.source,
            "dataset": r.dataset,
            "iso3": r.iso3,
            "variant": r.variant,
            "last_pulled_at": r.last_pulled_at.isoformat() if r.last_pulled_at else None,
            "high_water_date": r.high_water_date.isoformat() if r.high_water_date else None,
            "row_count": r.row_count,
            "known_id_count": len(r.known_ids or []),
            "notes": r.notes or "",
        }
        for r in SourceSync.objects.all()
    ]


class Command(BaseCommand):
    help = "Show what external data is held and how fresh it is."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", dest="as_json",
            help="Emit machine-readable JSON instead of a table.",
        )

    def handle(self, *args, **options):
        rows = status_rows()
        if options["as_json"]:
            self.stdout.write(json.dumps(rows, indent=2))
            return

        if not rows:
            self.stdout.write("No external data has been loaded yet.")
            return

        header = (
            f"{'source':<9} {'dataset':<17} {'iso3':<5} {'variant':<18} "
            f"{'pulled':<12} {'data to':<12} {'rows':>7}"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for r in rows:
            pulled = (r["last_pulled_at"] or "never")[:10]
            data_to = r["high_water_date"] or "-"
            self.stdout.write(
                f"{r['source']:<9} {r['dataset']:<17} {(r['iso3'] or '-'):<5} "
                f"{r['variant']:<18} {pulled:<12} {data_to:<12} {r['row_count']:>7}"
            )
            if r["notes"]:
                self.stdout.write(f"          note: {r['notes']}")
