"""Claiming a job, which is the only way one may be created.

WHY NOT `select_for_update()`. It locks rows that EXIST. When no ipc job is
active there is no row to lock, so two simultaneous requests both find nothing
and both insert - which is precisely the case the lock is for. A PostgreSQL
advisory lock is held on a name rather than a row, so it serialises the empty
case too, and the transaction releases it however it ends.

ONE GLOBAL CLAIM LOCK, not one per source. Claiming is a query and an insert -
microseconds - while the job it creates may run for minutes. Serialising the
claims costs nothing and removes the race between "may a rebuild start?" and
"may a pull start?", which per-source locks could not see.
"""
from datetime import timedelta

from django.db import connection, transaction

from api_calls.models import ACTIVE, PullJob

# Any stable pair. Namespace 8123 is this application's; 1 is "the claim lock".
CLAIM_LOCK = (8123, 1)

# Longer than any real pull. Sudan's IDP series, the biggest, is 57 pages.
STALE_AFTER = timedelta(minutes=30)


class JobBusy(Exception):
    """Something is already running that this job would collide with."""


def claim(kind, *, source=None, dataset=None, iso3=None, variant="", user=None):
    """Create a queued job, or raise JobBusy naming what is in the way."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", list(CLAIM_LOCK))

        active = PullJob.objects.filter(status__in=ACTIVE)

        if kind == "rebuild":
            # A rebuild reads every table a pull writes, so it waits for all of
            # them rather than for one source.
            blocker = active.first()
            if blocker:
                raise JobBusy(
                    f"job {blocker.id} ({blocker.target}) is {blocker.status}. "
                    "A rebuild waits for every pull to finish."
                )
        else:
            blocker = (active.filter(source=source).first()
                       or active.filter(kind="rebuild").first())
            if blocker:
                raise JobBusy(
                    f"job {blocker.id} ({blocker.target}) is {blocker.status}. "
                    f"Wait for it, or reset it if it is stuck."
                )

        return PullJob.objects.create(
            kind=kind, source=source, dataset=dataset, iso3=iso3,
            variant=variant or "", requested_by=user, status="queued",
        )
