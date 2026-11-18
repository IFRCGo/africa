"""Release uploaded documents that have outlived the retention cap.

The sweep the wizard runs on every page load, for a terminal or a host cron -
this deployment has no scheduler of its own (compose runs db, web and pgadmin),
so on a machine where nobody opens the wizard for a week this is what keeps
MEDIA_ROOT empty.

    docker compose exec web python manage.py prune_uploads [--dry-run]

IT FOLLOWS ROWS, LIKE EVERYTHING ELSE IN insights.retention. A file in the
folder that no InsightUpload row points at is left exactly where it is - see
the module docstring there for the deletion that rule is written in the blood
of. Removing one is a person's job, not a command's.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from insights import retention
from insights.models import InsightUpload


class Command(BaseCommand):
    help = "Release uploads older than INSIGHT_UPLOAD_RETENTION_MINUTES."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Name what would go, and release nothing.")

    def handle(self, *args, **options):
        minutes = retention.retention_minutes()
        cutoff = timezone.now() - timedelta(minutes=minutes)
        stale = InsightUpload.objects.exclude(file="").filter(uploaded_at__lt=cutoff)

        if options["dry_run"]:
            for upload in stale:
                held = " (being read - would wait)" if retention._is_being_read(upload) else ""
                self.stdout.write(f"would release {upload.file.name}{held}")
            self.stdout.write(f"{stale.count()} file(s) older than {minutes} minutes.")
            return

        released = retention.sweep()
        self.stdout.write(
            f"{released} file(s) released; the cap is {minutes} minutes.")
