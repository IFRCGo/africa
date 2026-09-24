"""Pulling several sources from one press, strictly one at a time.

THE RULE THIS FILE EXISTS FOR. "Never pull two IPC countries in parallel" -
recorded incident, the connection closed and the server stayed down for the rest
of the session. A "pull everything" button spanning six IPC countries is exactly
how that happens again, so the batch is serial by construction and tested to be.
"""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import call as mock_call, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from external_data.models import SourceSync
from api_calls.locks import JobBusy, claim
from api_calls.models import PullJob


class SerialTests(TestCase):
    def setUp(self):
        self.rows = [
            SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                      iso3=iso3, variant="")
            for iso3 in ("TCD", "SDN", "ETH")
        ]

    def test_each_row_is_refreshed_once_in_order(self):
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("api_calls.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        # Positional argv, because ONE function now decides which command
        # refreshes a row - refresh_argv - and it has to return something both
        # call_command here and subprocess.Popen in the view can take.
        countries = [c.args[c.args.index("--iso3") + 1] for c in ran.call_args_list]
        self.assertEqual(countries, ["TCD", "SDN", "ETH"])

    def test_the_batch_job_reports_progress_as_it_goes(self):
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("api_calls.management.commands.pull_batch.call_command"):
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
            if "SDN" in args:
                raise Exception("503 Service Unavailable")
        with patch("api_calls.management.commands.pull_batch.call_command",
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
        with patch("api_calls.management.commands.pull_batch.call_command",
                   side_effect=Exception("everything is broken")):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        job.refresh_from_db()
        self.assertIn(job.status, ("succeeded", "failed"))
        self.assertIsNotNone(job.finished_at)
        # And a second batch may now start.
        self.assertIsNotNone(claim("batch"))

    def test_two_workbook_rows_are_told_apart_on_the_banner(self):
        """They share nothing an operator can see but their variant. Listing
        both as "excel/refugees global" is a plan that reads as one row twice."""
        from api_calls.views import row_label
        a = SourceSync.objects.create(source="excel", dataset="refugees",
                                      variant="neighbours-workbook")
        b = SourceSync.objects.create(source="excel", dataset="refugees",
                                      variant="older-workbook")
        self.assertNotEqual(row_label(a), row_label(b))
        self.assertIn("neighbours-workbook", row_label(a))

    def test_every_row_job_names_the_batch_that_claimed_it(self):
        """What lets the banner fold nine bars into one. Without it the page
        can only guess, and guessing by time swallows a press of somebody
        else's Pull now button."""
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("api_calls.management.commands.pull_batch.call_command"):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        children = PullJob.objects.filter(kind="pull")
        self.assertEqual(children.count(), 3)
        self.assertEqual(set(children.values_list("parent_id", flat=True)), {job.id})

    def test_each_row_is_marked_done_as_the_batch_reaches_it(self):
        job = PullJob.objects.create(kind="batch", status="queued")
        job.items = [{"label": f"fewsnet/seasonal_calendar {r.iso3}",
                      "status": "pending", "message": ""} for r in self.rows]
        job.save(update_fields=["items"])
        with patch("api_calls.management.commands.pull_batch.call_command"):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        job.refresh_from_db()
        self.assertEqual([i["status"] for i in job.items],
                         ["succeeded"] * 3)

    def test_a_failed_row_is_marked_failed_and_says_why(self):
        """The tally at the end says "1 failed"; this says WHICH, without
        anyone opening a log."""
        job = PullJob.objects.create(kind="batch", status="queued")
        job.items = [{"label": f"fewsnet/seasonal_calendar {r.iso3}",
                      "status": "pending", "message": ""} for r in self.rows]
        job.save(update_fields=["items"])
        def maybe_fail(*args, **kwargs):
            if "SDN" in args:
                raise Exception("503 Service Unavailable")
        with patch("api_calls.management.commands.pull_batch.call_command",
                   side_effect=maybe_fail):
            call_command("pull_batch", "--job", str(job.id),
                         "--rows", ",".join(str(r.pk) for r in self.rows))
        job.refresh_from_db()
        failed = [i for i in job.items if i["status"] == "failed"]
        self.assertEqual([i["label"] for i in failed],
                         ["fewsnet/seasonal_calendar SDN"])
        self.assertIn("503", failed[0]["message"])

    def test_a_skipped_row_says_why_it_was_skipped(self):
        """Today that reason reaches stdout and nowhere a person looks."""
        kobo = SourceSync.objects.create(source="kobo", dataset="service_points",
                                         iso3="TCD", variant="")
        job = PullJob.objects.create(kind="batch", status="queued")
        job.items = [{"label": "kobo/service_points TCD", "status": "pending",
                      "message": ""}]
        job.save(update_fields=["items"])
        with patch("api_calls.management.commands.pull_batch.call_command"):
            call_command("pull_batch", "--job", str(job.id), "--rows", str(kobo.pk))
        job.refresh_from_db()
        self.assertEqual(job.items[0]["status"], "skipped")
        self.assertIn("no API", job.items[0]["message"])

    def test_a_row_with_neither_an_api_nor_a_command_is_skipped(self):
        kobo = SourceSync.objects.create(source="kobo", dataset="service_points",
                                         iso3="TCD", variant="")
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("api_calls.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(job.id), "--rows", str(kobo.pk))
        ran.assert_not_called()
        job.refresh_from_db()
        self.assertIn("skipped", job.message)

    def test_a_workbook_row_in_a_batch_runs_load_workbooks(self):
        """The batch and the button must choose the same command.

        Hard-coding refresh_external here is how an excel row admitted by
        stale_rows() fails inside every batch while its own button works.
        """
        excel = SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                          variant="sudan-idps-workbook")
        job = PullJob.objects.create(kind="batch", status="queued")
        with patch("api_calls.management.commands.pull_batch.call_command") as ran:
            call_command("pull_batch", "--job", str(job.id), "--rows", str(excel.pk))
        argv = ran.call_args.args
        self.assertEqual(argv[0], "load_workbooks")
        self.assertEqual(argv[argv.index("--only") + 1], "sudan-idps-workbook")


class ArgvReallyParsesTests(TestCase):
    """The argv refresh_argv builds, put through the REAL parser.

    Every other test here patches call_command, so the switch from keyword
    arguments to positional option strings is otherwise proven only against a
    mock - which would accept anything. These two ask argparse itself.
    """

    def _parsed(self, row):
        from django.core.management import load_command_class
        from api_calls.views import refresh_argv
        argv = refresh_argv(row, 42)
        app = {"refresh_external": "external_data",
               "load_workbooks": "external_data"}[argv[0]]
        parser = load_command_class(app, argv[0]).create_parser("manage.py", argv[0])
        return parser.parse_args(argv[1:])

    def test_an_api_rows_argv_carries_its_country_and_job(self):
        row = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                        iso3="TCD", variant="")
        opts = self._parsed(row)
        self.assertEqual((opts.source, opts.dataset, opts.iso3, opts.job),
                         ("fewsnet", "seasonal_calendar", "TCD", 42))

    def test_a_workbook_rows_argv_carries_its_variant_and_job(self):
        row = SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                        variant="sudan-idps-workbook")
        opts = self._parsed(row)
        self.assertEqual((opts.only, opts.job), ("sudan-idps-workbook", 42))


class StaleSelectionTests(TestCase):
    """"Pull everything out of date" must mean that, or pressing it twice is
    a second full download."""

    def test_rows_pulled_today_are_not_stale(self):
        from api_calls.views import stale_rows
        row = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                        iso3="TCD", last_pulled_at=timezone.now())
        # The row under test, not the whole list: migration 0015 seeds eight
        # montandon rows which have never been pulled and so are rightly stale.
        self.assertNotIn(row.pk, [r.pk for r in stale_rows()])

    def test_a_row_never_pulled_is_stale(self):
        from api_calls.views import stale_rows
        row = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                        iso3="SDN")
        self.assertIn(row.pk, [r.pk for r in stale_rows()])

    def test_a_row_pulled_yesterday_is_stale(self):
        from api_calls.views import stale_rows
        row = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="ETH",
            last_pulled_at=timezone.now() - timedelta(days=1))
        self.assertIn(row.pk, [r.pk for r in stale_rows()])

    def test_rows_with_no_api_and_no_command_are_never_stale(self):
        """Nothing refreshes them. Offering to is offering nothing."""
        from api_calls.views import stale_rows
        row = SourceSync.objects.create(source="kobo", dataset="service_points",
                                        iso3="TCD", variant="")
        self.assertNotIn(row.pk, [r.pk for r in stale_rows()])

    def _workbook_row(self, tmp, **kwargs):
        """A Sudan IDPs row and a stand-in file for it under a temporary root.

        file_changed only hashes the bytes, so the file need not be a real
        workbook - which keeps this test about the staleness rule.
        """
        (tmp / "Sudan IDPs.xlsx").write_bytes(b"august figures")
        return SourceSync.objects.create(
            source="excel", dataset="idps", iso3="SDN",
            variant="sudan-idps-workbook", **kwargs)

    def test_a_workbook_saved_after_the_last_load_is_stale(self):
        """THE WATERMARK FOR A FILE IS THE FILE.

        The date rule would skip exactly the edit the operator pressed the button
        for: an analyst who adds the August column an hour after the morning load
        would be told there is nothing to do.
        """
        from api_calls.views import stale_rows
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            row = self._workbook_row(
                tmp, last_pulled_at=timezone.now(), params={"sha1": "july"})
            with override_settings(SOURCE_ROOT=tmp):
                self.assertIn(row.pk, [r.pk for r in stale_rows()])

    def test_a_workbook_nobody_has_touched_is_not_stale(self):
        """Pressing twice must cost nothing the second time."""
        from external_data.management.commands.load_workbooks import _fingerprint
        from api_calls.views import stale_rows
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            row = self._workbook_row(tmp)
            with override_settings(SOURCE_ROOT=tmp):
                row.params = _fingerprint(tmp / "Sudan IDPs.xlsx")
                row.save(update_fields=["params"])
                self.assertNotIn(row.pk, [r.pk for r in stale_rows()])

    def test_rows_missing_their_key_are_not_stale(self):
        from django.test import override_settings
        from api_calls.views import stale_rows
        row = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        with override_settings(IPC_API_KEY=""):
            self.assertNotIn(row.pk, [r.pk for r in stale_rows()])
