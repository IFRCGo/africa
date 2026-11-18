"""The second button: the database is updated, the map is not - until you say so."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from api_calls.models import PullJob
from api_calls.views import pulls_since_last_rebuild


class RebuildTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)

    def test_pressing_it_launches_the_rebuild_wrapper(self):
        """run_rebuild, not run_pipeline directly: the pipeline takes no --job,
        so a job launched straight at it never leaves 'queued' - and a queued
        rebuild blocks every pull on every source, forever. The wrapper is what
        closes the job. See api_calls/tests/test_rebuild_job.py."""
        with patch("api_calls.views.subprocess.Popen") as popen:
            self.client.post("/admin/api_calls/datasource/rebuild/")
        argv = popen.call_args.args[0]
        self.assertIn("run_rebuild", argv)
        self.assertIn("--job", argv)

    def test_it_creates_a_rebuild_job(self):
        with patch("api_calls.views.subprocess.Popen"):
            self.client.post("/admin/api_calls/datasource/rebuild/")
        self.assertEqual(PullJob.objects.get().kind, "rebuild")

    def test_it_is_refused_while_a_pull_runs(self):
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="running")
        with patch("api_calls.views.subprocess.Popen") as popen:
            self.client.post("/admin/api_calls/datasource/rebuild/")
        popen.assert_not_called()

    def test_a_get_starts_nothing(self):
        with patch("api_calls.views.subprocess.Popen") as popen:
            response = self.client.get("/admin/api_calls/datasource/rebuild/")
        popen.assert_not_called()
        self.assertEqual(response.status_code, 200)


class CounterTests(TestCase):
    def test_it_counts_successful_pulls_since_the_last_rebuild(self):
        PullJob.objects.create(kind="rebuild", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="hdx", status="succeeded",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 2)

    def test_failed_pulls_do_not_count(self):
        """A failed pull changed nothing, so it is not a reason to rebuild."""
        PullJob.objects.create(kind="rebuild", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="ipc", status="failed",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 0)

    def test_with_no_rebuild_ever_every_successful_pull_counts(self):
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 1)

    def test_the_changelist_reports_the_count(self):
        user = get_user_model().objects.create_superuser("u", "u@e.org", "pw")
        self.client.force_login(user)
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        response = self.client.get(reverse("admin:api_calls_datasource_changelist"))
        self.assertContains(response, "1 pull")

    def test_the_changelist_says_so_when_there_is_nothing_to_rebuild_for(self):
        user = get_user_model().objects.create_superuser("v", "v@e.org", "pw")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:api_calls_datasource_changelist"))
        self.assertContains(response, "No pulls since the last rebuild")
