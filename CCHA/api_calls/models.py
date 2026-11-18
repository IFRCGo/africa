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
    """The freshness table, listed under the Data Refresh via API heading.

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
        help_text="pull (one row) / batch (several, serially) / rebuild (the layers)",
    )
    # Null for a rebuild, which belongs to no single row.
    source = models.TextField(null=True, blank=True)
    dataset = models.TextField(null=True, blank=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True)
    variant = models.TextField(default="", blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")

    # The batch this job was claimed by, if any. WHAT THE BANNER FOLDS ON: a
    # batch claims a job per row - it must, or the status column on the data
    # sources page has nothing to read - and drawing all of them turns one press
    # into nine bars. Matching children to their batch by time instead would
    # swallow a Pull now somebody pressed while the batch was running.
    #
    # SET_NULL, not CASCADE: this table is an audit trail, and deleting one
    # batch row from the job list must not take the record of the eight pulls it
    # ran with it. An orphaned child simply goes back to being drawn on its own.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="children", help_text="The batch job that claimed this one",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    rows_written = models.IntegerField(default=0)

    # How far along, for the banner. Kept as columns rather than scraped out of
    # the log, because a banner that parses stdout breaks the first time a
    # message is reworded.
    progress_done = models.IntegerField(default=0)
    progress_total = models.IntegerField(default=0)
    progress_note = models.TextField(default="", blank=True)
    # A batch's plan and how far it got: one entry per row, each
    # {"label", "status", "message"}. Written FULL AND PENDING at launch rather
    # than grown as rows are reached, so the bar cites what is coming as well as
    # what is done - and says so in the seconds before the command has booted.
    #
    # Not derived from the child jobs, because a skipped row never gets one:
    # inferring per-row state from `progress_done` indices is how a skip reason
    # that only ever reached stdout stays unreadable.
    items = models.JSONField(
        default=list, blank=True,
        help_text="For a batch: [{label, status, message}] per row",
    )
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
        # PINNED, because the default off `api_calls` would be `api_calls_pulljob`
        # and this table is read by hand often enough to be worth a name a person
        # would write. It was `mcp_pull_job` until 2026-09-24; migration 0003
        # renamed it, and rewrote the cache paths the rows below hold.
        db_table = "api_pull_job"
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
            # Same reasoning for a batch: `source` is null on one, so the
            # per-source constraint cannot see it. Two batches running at once
            # would race for the same rows and defeat the one-at-a-time rule
            # they exist to keep.
            models.UniqueConstraint(
                fields=["kind"], name="uniq_active_batch",
                condition=Q(kind="batch", status__in=ACTIVE),
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
        from api_calls.locks import STALE_AFTER
        if self.status not in ACTIVE:
            return False
        started = self.started_at or self.requested_at
        return bool(started and timezone.now() - started > STALE_AFTER)

    @property
    def target(self):
        """'ipc/food_security SDN', or what the batch and rebuild jobs cover."""
        if self.kind == "rebuild":
            return "dashboard layers"
        if self.kind == "batch":
            return f"{self.progress_total or 'several'} data sources"
        where = self.iso3 or "global"
        return f"{self.source}/{self.dataset} {where} {self.variant}".strip()

    def __str__(self):
        return f"job {self.id}: {self.target} ({self.status})"
