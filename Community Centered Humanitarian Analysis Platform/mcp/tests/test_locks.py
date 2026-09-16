"""Claiming a job, and the rule that stops the recorded IPC crash repeating.

The lock is tested through its effects rather than with threads. What must hold
is: while a source has work in flight, nothing else may claim that source; a
rebuild excludes everything; and the database refuses a duplicate even if some
future caller forgets to go through claim().
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from mcp.locks import JobBusy, STALE_AFTER, claim
from mcp.models import PullJob


class ClaimTests(TestCase):
    def test_a_claim_returns_a_queued_job(self):
        job = claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.source, "fewsnet")
        self.assertIsNotNone(job.requested_at)

    def test_a_second_claim_on_a_busy_source_is_refused(self):
        """Two tabs, two countries, two clicks - the way IPC went down before."""
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        with self.assertRaises(JobBusy):
            claim("pull", source="ipc", dataset="food_security", iso3="TCD")

    def test_a_different_source_is_allowed_at_the_same_time(self):
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        job = claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        self.assertEqual(job.status, "queued")

    def test_a_finished_job_does_not_hold_the_source(self):
        first = claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        first.status = "succeeded"
        first.save(update_fields=["status"])
        self.assertIsNotNone(claim("pull", source="ipc", dataset="food_security", iso3="TCD"))

    def test_a_rebuild_is_refused_while_any_pull_runs(self):
        """A rebuild reads the tables a pull is writing."""
        claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        with self.assertRaises(JobBusy):
            claim("rebuild")

    def test_a_pull_is_refused_while_a_rebuild_runs(self):
        claim("rebuild")
        with self.assertRaises(JobBusy):
            claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")

    def test_a_second_rebuild_is_refused(self):
        claim("rebuild")
        with self.assertRaises(JobBusy):
            claim("rebuild")

    def test_the_refusal_names_the_job_holding_the_source(self):
        held = claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        with self.assertRaises(JobBusy) as caught:
            claim("pull", source="ipc", dataset="food_security", iso3="TCD")
        self.assertIn(str(held.id), str(caught.exception))


class ConstraintTests(TestCase):
    def test_the_database_itself_refuses_two_active_jobs_for_one_source(self):
        """claim() is the front door; the constraint is the lock on it. A future
        caller that inserts directly must not be able to break the rule."""
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="running")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                   iso3="TCD", status="queued")


class StaleTests(TestCase):
    def test_a_long_running_job_is_reported_stale(self):
        job = PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                     iso3="SDN", status="running")
        PullJob.objects.filter(pk=job.pk).update(
            started_at=timezone.now() - STALE_AFTER - timedelta(minutes=1))
        self.assertTrue(PullJob.objects.get(pk=job.pk).is_stale)

    def test_a_fresh_job_is_not_stale(self):
        job = PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                     iso3="SDN", status="running",
                                     started_at=timezone.now())
        self.assertFalse(job.is_stale)
