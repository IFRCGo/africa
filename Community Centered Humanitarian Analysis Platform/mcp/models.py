"""The attempt record, and the list the admin section draws.

THE DIVISION THIS TABLE EXISTS FOR. `source_sync` records what is HELD: it is
advanced only by a successful load, inside that load's transaction. `PullJob`
records what was ATTEMPTED, including everything that failed and why. Keeping
them apart is what lets the freshness table still be trusted once a button
exists - a pull that fails must never look like fresh data.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from external_data.models import SourceSync

# The statuses that mean "this job holds its source".
ACTIVE = ("queued", "running")

STATUS_CHOICES = [
    ("queued", "queued"), ("running", "running"),
    ("succeeded", "succeeded"), ("failed", "failed"),
]


class DataSource(SourceSync):
    """The freshness table, listed under the MCP heading.

    A PROXY, NOT A COPY. Django's admin groups the sidebar by app, so a separate
    heading needs a model in this app - but the facts belong to `source_sync` and
    duplicating them into a second table is how two tables start disagreeing
    about which is right. This model has no table of its own.
    """

    class Meta:
        proxy = True
        verbose_name = "data source"
        verbose_name_plural = "data sources"


class PullJob(models.Model):
    """One press of a button, and everything that came of it."""

    kind = models.CharField(
        max_length=16, default="pull",
        help_text="pull (one source_sync row) / rebuild (the dashboard layers)",
    )
    # Null for a rebuild, which belongs to no single row.
    source = models.TextField(null=True, blank=True)
    dataset = models.TextField(null=True, blank=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True)
    variant = models.TextField(default="", blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    rows_written = models.IntegerField(default=0)
    payload_path = models.TextField(
        null=True, blank=True, help_text="Where the raw response was saved"
    )
    message = models.TextField(
        default="", blank=True, help_text="The error, or a one-line summary. Redacted."
    )
    # The full output goes to a FILE, not a column - the same choice
    # insights/admin.py makes for extraction jobs, and for the same reasons: the
    # job page can tail it while the command is still writing, and a 50,000-line
    # IPC run does not become a 50,000-line database row.
    log_path = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "mcp_pull_job"
        ordering = ["-requested_at"]
        constraints = [
            # The database's own guarantee, behind claim(). One active job per
            # source, whatever route the insert came in by.
            models.UniqueConstraint(
                fields=["source"], name="uniq_active_job_per_source",
                condition=Q(status__in=ACTIVE),
            ),
            # `source` is null on a rebuild and Postgres treats nulls as
            # distinct, so the constraint above cannot cover rebuilds. This one
            # does: at most one active rebuild, ever.
            models.UniqueConstraint(
                fields=["kind"], name="uniq_active_rebuild",
                condition=Q(kind="rebuild", status__in=ACTIVE),
            ),
        ]
        indexes = [
            models.Index(fields=["source", "status"], name="idx_pull_job_source_status"),
        ]

    @property
    def is_stale(self):
        """Running far longer than any real pull takes - probably a dead process.

        A container restart leaves a job at 'running' with nothing behind it. The
        row is then holding its source against every future press, so the list
        shows this and offers a reset - the same affordance, and the same reason,
        as reset_stuck_job in insights/admin.py.
        """
        from mcp.locks import STALE_AFTER
        if self.status not in ACTIVE:
            return False
        started = self.started_at or self.requested_at
        return bool(started and timezone.now() - started > STALE_AFTER)

    @property
    def target(self):
        """'ipc/food_security SDN', or 'dashboard layers' for a rebuild."""
        if self.kind == "rebuild":
            return "dashboard layers"
        where = self.iso3 or "global"
        return f"{self.source}/{self.dataset} {where} {self.variant}".strip()

    def __str__(self):
        return f"job {self.id}: {self.target} ({self.status})"
