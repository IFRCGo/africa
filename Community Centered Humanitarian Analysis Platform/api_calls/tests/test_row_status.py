"""After a pull succeeds, the row must SAY so.

The gap this closes: pull_batch called refresh_external without --job, so a
batch left no per-row record at all and every row it had just refreshed still
showed a dash. The freshness date moved and nothing on the page said why.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from external_data.models import SourceSync
from mcp.models import PullJob


class BatchRecordsEachRowTests(TestCase):
    def setUp(self):
        self.rows = [
            SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                      iso3=iso3, variant="")
            for iso3 in ("TCD", "SDN")
        ]

    def _run(self):
        batch = PullJob.objects.create(kind="batch", status="queued")
        with patch("mcp.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(batch.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        return batch, ran

    def test_every_row_in_a_batch_gets_its_own_job(self):
        self._run()
        for row in self.rows:
            self.assertTrue(
                PullJob.objects.filter(kind="pull", source=row.source,
                                       dataset=row.dataset, iso3=row.iso3).exists(),
                f"no job recorded for {row.iso3}")

    def test_the_row_job_is_passed_to_refresh_external(self):
        """Without --job the command has nothing to write its outcome onto."""
        _, ran = self._run()
        for c in ran.call_args_list:
            self.assertIn("--job", c.args)

    def test_a_row_job_is_closed_before_the_next_row_starts(self):
        """One active job per source is a database constraint. Eight FEWS NET
        countries in one batch would breach it if the jobs overlapped."""
        self._run()
        self.assertEqual(
            PullJob.objects.filter(kind="pull", status__in=("queued", "running")).count(), 0)

    def test_a_row_whose_source_is_already_busy_is_skipped_not_crashed(self):
        """A single Pull running for fewsnet while a batch reaches a fewsnet row
        must not take the whole batch down with an IntegrityError."""
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="ETH",
                               status="running")
        batch, ran = self._run()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "succeeded")
        self.assertIn("skipped", batch.message)


class StatusColumnTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)
        self.row = SourceSync.objects.create(source="fewsnet",
                                             dataset="seasonal_calendar",
                                             iso3="TCD", variant="")

    def _html(self):
        return self.client.get(reverse("admin:mcp_datasource_changelist")).content.decode()

    def test_a_successful_pull_shows_as_succeeded_with_its_row_count(self):
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD", variant="",
                               status="succeeded", rows_written=6,
                               finished_at=timezone.now())
        html = self._html()
        self.assertIn("succeeded", html)
        self.assertIn("6 rows", html)

    def test_an_up_to_date_pull_says_so_rather_than_zero_rows(self):
        """'0 rows' reads like a failure. 'up to date' is what happened."""
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD", variant="",
                               status="succeeded", rows_written=0,
                               message="already up to date - nothing new published",
                               finished_at=timezone.now())
        html = self._html()
        self.assertIn("up to date", html)
        self.assertNotIn("0 rows", html)

    def test_a_failure_still_shows_its_reason(self):
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD", variant="",
                               status="failed", message="503 from fdw.fews.net",
                               finished_at=timezone.now())
        self.assertIn("503 from fdw.fews.net", self._html())

    def test_a_row_never_pulled_shows_a_dash(self):
        self.assertIn("&mdash;", self._html())

    def test_a_batch_that_pulled_the_row_is_what_the_column_reports(self):
        """The end-to-end shape of the bug: a batch ran, so the row shows it."""
        SourceSync.objects.filter(pk=self.row.pk).update(last_pulled_at=timezone.now())
        PullJob.objects.create(kind="batch", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD", variant="",
                               status="succeeded", rows_written=6,
                               finished_at=timezone.now() - timedelta(seconds=5))
        html = self._html()
        self.assertIn("succeeded", html)
        self.assertIn("6 rows", html)
