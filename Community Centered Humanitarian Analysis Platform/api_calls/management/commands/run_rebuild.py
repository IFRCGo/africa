"""`python manage.py run_rebuild --job N` - rebuild the dashboard layers, and say so.

WHY THIS EXISTS RATHER THAN LAUNCHING run_pipeline DIRECTLY. `run_pipeline` knows
nothing about PullJob and takes no --job, so a rebuild launched straight at it
never leaves 'queued'. 'queued' is an ACTIVE status, so that one row then blocks
EVERY pull, for every source, forever - one press of the button bricks the whole
feature until somebody edits the row in a shell.

This wrapper is the piece that closes the job, exactly as refresh_external does
for a pull: mark running, do the work, mark succeeded or failed. The rule it
keeps is that no job is ever left in an active status by a path that finished.
"""
from datetime import datetime, timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand

# The same two steps the updater page's own rebuild runs.
STEPS = "s06,s07"


class Command(BaseCommand):
    help = "Rebuild the dashboard's external layers, recording a PullJob."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, default=None,
                            help="PullJob id to record progress against")

    def handle(self, *args, **options):
        from api_calls.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        if job:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.save(update_fields=["status", "started_at"])

        try:
            call_command("run_pipeline", "--only", STEPS)
        except Exception as exc:
            self._finish(job, "failed", str(exc))
            raise

        self._finish(job, "succeeded", f"rebuilt {STEPS}")
        self.stdout.write(f"rebuilt {STEPS}")

    def _finish(self, job, status, message):
        if not job:
            return
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.message = message[:4000]
        job.save(update_fields=["status", "finished_at", "message"])
