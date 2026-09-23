"""`load_workbooks --only` and `--job`: what the admin's Reload file button needs.

THE JOB BOOKKEEPING IS THE FRAGILE PART, and it is fragile in one specific way.
The load runs inside a transaction; a failure recorded inside that transaction is
rolled back with it, and the job then stays at 'queued'. 'queued' is an ACTIVE
status, so that one row would hold the 'excel' source against every future press -
the trap run_rebuild.py's docstring describes. Both paths are tested below.
"""
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import openpyxl
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from external_data.models import MovementPattern, SourceSync
from mcp.models import ACTIVE, PullJob


def write_idp_workbook(directory, dates=("31 Jul 2026", "31 Aug 2026")):
    """A minimal Sudan IDPs.xlsx: one state, one column per date."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Location name", "Population",
               *[f"Population ({d})" for d in dates]])
    ws.append(["Khartoum", None, *[100 + i for i in range(len(dates))]])
    path = directory / "Sudan IDPs.xlsx"
    wb.save(str(path))
    return path


class WorkbookTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = write_idp_workbook(self.root)


class OnlyTests(WorkbookTestCase):
    """One row's button must reload one workbook."""

    def test_only_loads_the_named_workbook_and_ignores_the_other(self):
        """The neighbours file is absent here.

        Without --only this run would fail on it - which is the whole reason a
        per-row button needs the option.
        """
        with override_settings(SOURCE_ROOT=self.root):
            call_command("load_workbooks", "--only", "sudan-idps-workbook")
        self.assertTrue(MovementPattern.objects.filter(
            source="excel", metric="idps", iso3="SDN").exists())
        self.assertFalse(MovementPattern.objects.filter(metric="refugees").exists())

    def test_an_unknown_variant_is_refused_and_lists_the_real_ones(self):
        with override_settings(SOURCE_ROOT=self.root):
            with self.assertRaises(CommandError) as caught:
                call_command("load_workbooks", "--only", "not-a-workbook")
        self.assertIn("sudan-idps-workbook", str(caught.exception))

    def test_the_newest_dated_column_becomes_the_high_water_date(self):
        """This is what the operator checks after pressing the button."""
        with override_settings(SOURCE_ROOT=self.root):
            call_command("load_workbooks", "--only", "sudan-idps-workbook")
        sync = SourceSync.objects.get(source="excel", variant="sudan-idps-workbook")
        self.assertEqual(sync.high_water_date, date(2026, 8, 31))

    def test_a_dry_run_writes_nothing(self):
        with override_settings(SOURCE_ROOT=self.root):
            call_command("load_workbooks", "--only", "sudan-idps-workbook",
                         "--dry-run")
        self.assertEqual(MovementPattern.objects.count(), 0)


class JobTests(WorkbookTestCase):
    def setUp(self):
        super().setUp()
        self.job = PullJob.objects.create(
            kind="pull", source="excel", dataset="idps", iso3="SDN",
            variant="sudan-idps-workbook", status="queued")

    def test_a_successful_load_closes_its_job_with_the_row_count(self):
        with override_settings(SOURCE_ROOT=self.root):
            call_command("load_workbooks", "--only", "sudan-idps-workbook",
                         "--job", str(self.job.id))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "succeeded")
        self.assertEqual(self.job.rows_written, 2)
        self.assertIn("2026-08-31", self.job.message)
        self.assertIsNotNone(self.job.finished_at)

    def test_a_failed_load_closes_its_job_rather_than_holding_the_source(self):
        """THE ROLLBACK TRAP.

        The failure is written outside the transaction, so the rollback of the
        load cannot take the record of it away and leave this row at 'queued',
        refusing every later press for the excel source.
        """
        with override_settings(SOURCE_ROOT=self.root / "nowhere"):
            with self.assertRaises(CommandError):
                call_command("load_workbooks", "--only", "sudan-idps-workbook",
                             "--job", str(self.job.id))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "failed")
        self.assertNotIn(self.job.status, ACTIVE)
        self.assertIn("not found", self.job.message)

    def test_a_failed_load_leaves_the_freshness_row_alone(self):
        """source_sync records what is HELD, so a load that failed must never
        look like fresh data."""
        with override_settings(SOURCE_ROOT=self.root):
            call_command("load_workbooks", "--only", "sudan-idps-workbook")
        held = SourceSync.objects.get(source="excel", variant="sudan-idps-workbook")
        before = held.high_water_date

        # Re-saved with no dated column at all - the shape a renamed heading
        # leaves behind, and a failure by the loaders' "loud on empty" rule.
        write_idp_workbook(self.root, dates=[])
        with override_settings(SOURCE_ROOT=self.root):
            with self.assertRaises(CommandError):
                call_command("load_workbooks", "--only", "sudan-idps-workbook")
        held.refresh_from_db()
        self.assertEqual(held.high_water_date, before)

    def test_a_second_load_of_an_untouched_file_says_so(self):
        """"No new figures" and "nobody saved the workbook" look identical on the
        page otherwise, and they call for completely different next steps."""
        with override_settings(SOURCE_ROOT=self.root):
            # The first press, through setUp's job. It has to be CLOSED before a
            # second job for the same source can exist at all -
            # uniq_active_job_per_source allows exactly one active per source.
            call_command("load_workbooks", "--only", "sudan-idps-workbook",
                         "--job", str(self.job.id))
            second = PullJob.objects.create(
                kind="pull", source="excel", dataset="idps", iso3="SDN",
                variant="sudan-idps-workbook", status="queued")
            call_command("load_workbooks", "--only", "sudan-idps-workbook",
                         "--job", str(second.id))
        second.refresh_from_db()
        self.assertIn("file unchanged", second.message)


class FileChangedTests(WorkbookTestCase):
    """The staleness rule for a file, which is not a date."""

    def _row(self, **kwargs):
        return SourceSync.objects.create(
            source="excel", dataset="idps", iso3="SDN",
            variant="sudan-idps-workbook", **kwargs)

    def test_a_row_never_loaded_counts_as_changed(self):
        from external_data.management.commands.load_workbooks import file_changed
        with override_settings(SOURCE_ROOT=self.root):
            self.assertTrue(file_changed(self._row()))

    def test_a_missing_file_counts_as_changed_rather_than_up_to_date(self):
        """It is something for a refresh to look at and report, not to skip."""
        from external_data.management.commands.load_workbooks import file_changed
        row = self._row(params={"sha1": "whatever"})
        with override_settings(SOURCE_ROOT=self.root / "nowhere"):
            self.assertTrue(file_changed(row))

    def test_the_same_bytes_are_not_a_change(self):
        from external_data.management.commands.load_workbooks import (
            _fingerprint, file_changed)
        row = self._row(params=_fingerprint(self.path))
        with override_settings(SOURCE_ROOT=self.root):
            self.assertFalse(file_changed(row))

    def test_a_file_that_will_not_open_does_not_take_the_page_down(self):
        """This runs on every render of the data sources list, and it is the only
        thing on that page that touches /work.

        That is a OneDrive share mounted into the container: a Files-On-Demand
        placeholder that has not hydrated raises OSError out of open(). Letting it
        escape would 500 the whole list and disable every other source's button,
        over a file nobody had asked to load.
        """
        from external_data.management.commands.load_workbooks import (
            _fingerprint, file_changed)
        row = self._row(params=_fingerprint(self.path))
        with override_settings(SOURCE_ROOT=self.root), \
                patch("builtins.open", side_effect=OSError("cloud file not available")):
            self.assertTrue(file_changed(row))

    def test_resaving_the_workbook_with_a_new_column_is_a_change(self):
        from external_data.management.commands.load_workbooks import (
            _fingerprint, file_changed)
        row = self._row(params=_fingerprint(self.path))
        write_idp_workbook(self.root,
                           dates=("31 Jul 2026", "31 Aug 2026", "30 Sep 2026"))
        with override_settings(SOURCE_ROOT=self.root):
            self.assertTrue(file_changed(row))
