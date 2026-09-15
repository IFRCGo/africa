"""Pulling several sources from one press, strictly one at a time.

THE RULE THIS FILE EXISTS FOR. "Never pull two IPC countries in parallel" -
recorded incident, the connection closed and the server stayed down for the rest
of the session. A "pull everything" button spanning six IPC countries is exactly
how that happens again, so the batch is serial by construction and tested to be.
"""
from datetime import timedelta
from unittest.mock import call as mock_call, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from external_data.models import SourceSync
from mcp.locks import JobBusy, claim
from mcp.models import PullJob


class SerialTests(TestCase):
    def setUp(self):
        self.rows = [
            SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                      iso3=iso3, variant="")
            for iso3 in ("TCD", "SDN", "ETH")
        ]

    def test_each_row_is_refreshed_once_in_order(self):
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("mcp.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        countries = [c.kwargs["iso3"] for c in ran.call_args_list]
        self.assertEqual(countries, ["TCD", "SDN", "ETH"])

    def test_the_batch_job_reports_progress_as_it_goes(self):
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("mcp.management.commands.pull_batch.call_command"):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        job.refresh_from_db()
        self.assertEqual(job.progress_total, 3)
        self.assertEqual(job.progress_done, 3)
        self.assertEqual(job.status, "succeeded")

    def test_one_failure_does_not_stop_the_rest(self):
        """A 503 from one agency must not cost you the other five sources."""
        job = PullJob.objects.create(kind="batch", status="queued")
        def maybe_fail(*args, **kwargs):
            if kwargs.get("iso3") == "SDN":
                raise Exception("503 Service Unavailable")
        with patch("mcp.management.commands.pull_batch.call_command",
                   side_effect=maybe_fail) as ran:
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        self.assertEqual(len(ran.call_args_list), 3)
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertIn("1 failed", job.message)

    def test_the_batch_always_finishes_its_job_row(self):
        """A batch left active would hold nothing itself, but the constraint
        would refuse every later batch. It must close, whatever happens."""
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("mcp.management.commands.pull_batch.call_command",
                   side_effect=Exception("everything is broken")):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        job.refresh_from_db()
        self.assertIn(job.status, ("succeeded", "failed"))
        self.assertIsNotNone(job.finished_at)
        # And a second batch may now start.
        self.assertIsNotNone(claim("batch"))

    def test_a_row_with_no_fetcher_is_skipped_not_attempted(self):
        excel = SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                          variant="sudan-idps-workbook")
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("mcp.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(job.id), "--rows", str(excel.pk))
        ran.assert_not_called()
        job.refresh_from_db()
        self.assertIn("skipped", job.message)


class StaleSelectionTests(TestCase):
    """"Pull everything out of date" must mean that, or pressing it twice is
    a second full download."""

    def test_rows_pulled_today_are_not_stale(self):
        from mcp.views import stale_rows
        SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                  iso3="TCD", last_pulled_at=timezone.now())
        self.assertEqual(list(stale_rows()), [])

    def test_a_row_never_pulled_is_stale(self):
        from mcp.views import stale_rows
        row = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                        iso3="SDN")
        self.assertIn(row.pk, [r.pk for r in stale_rows()])

    def test_a_row_pulled_yesterday_is_stale(self):
        from mcp.views import stale_rows
        row = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="ETH",
            last_pulled_at=timezone.now() - timedelta(days=1))
        self.assertIn(row.pk, [r.pk for r in stale_rows()])

    def test_file_based_rows_are_never_stale(self):
        """They have no API. Offering to refresh them is offering nothing."""
        from mcp.views import stale_rows
        SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                  variant="sudan-idps-workbook")
        self.assertEqual(list(stale_rows()), [])

    def test_rows_missing_their_key_are_not_stale(self):
        from django.test import override_settings
        from mcp.views import stale_rows
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        with override_settings(IPC_API_KEY=""):
            self.assertEqual(list(stale_rows()), [])
