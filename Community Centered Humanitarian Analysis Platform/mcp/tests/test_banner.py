"""The banner, the multi-select action, and the pull-everything button.

What these are for: not having to open Pull jobs to learn whether a pull worked.
So the tests are about what a person can SEE on the data sources page.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from external_data.models import SourceSync
from mcp.models import PullJob


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)
        self.a = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                           iso3="TCD", variant="")
        self.b = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                           iso3="SDN", variant="")
        self.file_row = SourceSync.objects.create(source="excel", dataset="idps",
                                                  iso3="SDN", variant="w")


class ActivityEndpointTests(Base):
    def test_a_running_job_is_reported_with_its_progress(self):
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="running", progress_done=3,
                               progress_total=7, progress_note="412 rows so far")
        data = self.client.get("/admin/mcp/datasource/activity/").json()
        self.assertEqual(len(data["running"]), 1)
        job = data["running"][0]
        self.assertEqual((job["done"], job["total"]), (3, 7))
        self.assertIn("412 rows", job["note"])

    def test_a_recent_failure_is_still_reported(self):
        """The whole point of the banner: a pull that failed while you were on
        another tab must still be on the page when you come back."""
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="failed", message="503 from IPC",
                               finished_at=timezone.now() - timedelta(minutes=5))
        data = self.client.get("/admin/mcp/datasource/activity/").json()
        self.assertEqual(len(data["finished"]), 1)
        self.assertIn("503", data["finished"][0]["message"])

    def test_an_old_job_is_not_reported(self):
        """Otherwise the banner becomes a second, worse copy of the job list."""
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now() - timedelta(hours=3))
        data = self.client.get("/admin/mcp/datasource/activity/").json()
        self.assertEqual(data["finished"], [])

    def test_it_is_staff_only(self):
        self.client.logout()
        response = self.client.get("/admin/mcp/datasource/activity/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class BannerMarkupTests(Base):
    def test_the_page_carries_the_banner_container_and_script(self):
        html = self.client.get(reverse("admin:mcp_datasource_changelist")).content.decode()
        self.assertIn('id="mcp-activity"', html)
        self.assertIn("mcp/activity.js", html)

    def test_the_page_says_how_many_sources_are_out_of_date(self):
        html = self.client.get(reverse("admin:mcp_datasource_changelist")).content.decode()
        self.assertIn("2 sources not pulled today", html)

    def test_it_says_so_when_nothing_is_out_of_date(self):
        SourceSync.objects.all().update(last_pulled_at=timezone.now())
        html = self.client.get(reverse("admin:mcp_datasource_changelist")).content.decode()
        self.assertIn("pulled today", html)


class PullSelectedTests(Base):
    def _act(self, rows):
        return self.client.post(
            reverse("admin:mcp_datasource_changelist"),
            {"action": "pull_selected", "_selected_action": [str(r.pk) for r in rows]},
            follow=True)

    def test_selecting_rows_starts_one_batch_for_all_of_them(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self._act([self.a, self.b])
        job = PullJob.objects.get(kind="batch")
        self.assertEqual(job.progress_total, 2)
        argv = popen.call_args.args[0]
        self.assertIn("pull_batch", argv)
        # Order follows the changelist, not the order rows happened to be
        # created - which is what an operator scanning the page would expect.
        rows = argv[argv.index("--rows") + 1].split(",")
        self.assertEqual(set(rows), {str(self.a.pk), str(self.b.pk)})

    def test_a_file_based_row_in_the_selection_is_skipped_not_attempted(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self._act([self.a, self.file_row])
        argv = popen.call_args.args[0]
        self.assertNotIn(str(self.file_row.pk), argv.__str__().split("--rows")[-1])
        self.assertIn("1 skipped", response.content.decode())

    def test_selecting_only_unpullable_rows_starts_nothing(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self._act([self.file_row])
        popen.assert_not_called()
        self.assertIn("None of those can be pulled", response.content.decode())

    def test_a_second_batch_is_refused_while_one_runs(self):
        PullJob.objects.create(kind="batch", status="running")
        with patch("mcp.views.subprocess.Popen") as popen:
            self._act([self.a])
        popen.assert_not_called()


class PullAllTests(Base):
    def test_it_pulls_every_stale_row(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post("/admin/mcp/datasource/pull-all/")
        job = PullJob.objects.get(kind="batch")
        self.assertEqual(job.progress_total, 2)      # the two fewsnet rows
        popen.assert_called_once()

    def test_a_get_shows_what_would_be_pulled_and_starts_nothing(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            html = self.client.get("/admin/mcp/datasource/pull-all/").content.decode()
        popen.assert_not_called()
        self.assertIn("one at a time", html)
        self.assertIn("seasonal_calendar", html)

    def test_pressing_it_when_nothing_is_stale_starts_nothing(self):
        SourceSync.objects.all().update(last_pulled_at=timezone.now())
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post("/admin/mcp/datasource/pull-all/")
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)

    @override_settings(IPC_API_KEY="")
    def test_a_keyless_row_is_never_counted_as_stale(self):
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        with patch("mcp.views.subprocess.Popen"):
            self.client.post("/admin/mcp/datasource/pull-all/")
        self.assertEqual(PullJob.objects.get(kind="batch").progress_total, 2)
