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
from api_calls.models import PullJob


class Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)
        # EVERY TEST BELOW COUNTS THE ROWS IT CAN SEE, so this fixture owns the
        # whole table and starts by emptying it.
        #
        # Seed migrations run against the test database too - 0015 adds eight
        # montandon rows, 0018 a dtm row, 0019 a unhcr-odp row - and each has
        # never been pulled, so each is rightly stale and joins every count and
        # every batch here. Naming them one by one meant this fixture had to be
        # edited every time a source was added, and the failure when it was not
        # reads as an off-by-one in the banner rather than a new row in the
        # table. Clearing the lot cannot go stale.
        SourceSync.objects.all().delete()
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
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
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
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
        self.assertEqual(len(data["finished"]), 1)
        self.assertIn("503", data["finished"][0]["message"])

    def test_an_old_job_is_not_reported(self):
        """Otherwise the banner becomes a second, worse copy of the job list."""
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now() - timedelta(hours=3))
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
        self.assertEqual(data["finished"], [])

    def test_a_batchs_row_jobs_are_not_drawn_beside_it(self):
        """ONE BAR PER PRESS. A batch claims a job per row so the status column
        has something to read; drawing all of them turns one press into nine
        bars, each lingering half an hour after it ends."""
        batch = PullJob.objects.create(kind="batch", status="running",
                                       progress_total=2)
        PullJob.objects.create(kind="pull", source="fewsnet", iso3="TCD",
                               status="running", parent=batch)
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
        self.assertEqual([j["kind"] for j in data["running"]], ["batch"])

    def test_a_pull_pressed_by_hand_during_a_batch_is_still_drawn(self):
        """Only the batch's OWN rows are folded in. Somebody else's press is
        theirs, and hiding it would leave them watching nothing."""
        batch = PullJob.objects.create(kind="batch", status="running")
        PullJob.objects.create(kind="pull", source="fewsnet", status="running",
                               parent=batch)
        PullJob.objects.create(kind="pull", source="ipc", status="running")
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
        self.assertEqual(sorted(j["kind"] for j in data["running"]),
                         ["batch", "pull"])

    def test_a_long_batch_is_still_reported(self):
        """Children are requested AFTER the batch, so a newest-first slice of
        twelve drops the one bar the page is there to draw."""
        batch = PullJob.objects.create(kind="batch", status="running",
                                       progress_total=20)
        for n in range(20):
            PullJob.objects.create(kind="pull", source=f"s{n}", status="succeeded",
                                   parent=batch, finished_at=timezone.now())
        data = self.client.get("/admin/api_calls/datasource/activity/").json()
        self.assertEqual([j["kind"] for j in data["running"]], ["batch"])

    def test_a_batch_names_every_source_it_covers(self):
        """The plan, not just a count: the bar cites what is being pulled."""
        batch = PullJob.objects.create(
            kind="batch", status="running", progress_total=2,
            items=[{"label": "fewsnet/seasonal_calendar TCD", "status": "succeeded",
                    "message": "41 rows"},
                   {"label": "fewsnet/seasonal_calendar SDN", "status": "pending",
                    "message": ""}])
        job = self.client.get("/admin/api_calls/datasource/activity/").json()["running"][0]
        self.assertEqual([i["label"] for i in job["items"]],
                         ["fewsnet/seasonal_calendar TCD",
                          "fewsnet/seasonal_calendar SDN"])
        self.assertEqual([i["status"] for i in job["items"]],
                         ["succeeded", "pending"])

    def test_a_finished_job_reports_when_it_finished(self):
        """The result list hides itself a couple of minutes after the batch
        ends, and the browser cannot work out when that is without this."""
        PullJob.objects.create(kind="batch", status="succeeded",
                               finished_at=timezone.now() - timedelta(minutes=1))
        job = self.client.get("/admin/api_calls/datasource/activity/").json()["finished"][0]
        self.assertTrue(job["finished_at"])

    def test_it_is_staff_only(self):
        self.client.logout()
        response = self.client.get("/admin/api_calls/datasource/activity/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class BannerMarkupTests(Base):
    def test_the_page_carries_the_banner_container_and_script(self):
        html = self.client.get(reverse("admin:api_calls_datasource_changelist")).content.decode()
        self.assertIn('id="api-calls-activity"', html)
        self.assertIn("api_calls/activity.js", html)

    def test_the_page_says_how_many_sources_are_out_of_date(self):
        html = self.client.get(reverse("admin:api_calls_datasource_changelist")).content.decode()
        self.assertIn("2 sources not pulled today", html)

    def test_it_says_so_when_nothing_is_out_of_date(self):
        SourceSync.objects.all().update(last_pulled_at=timezone.now())
        html = self.client.get(reverse("admin:api_calls_datasource_changelist")).content.decode()
        self.assertIn("pulled today", html)


class PullSelectedTests(Base):
    def _act(self, rows):
        return self.client.post(
            reverse("admin:api_calls_datasource_changelist"),
            {"action": "pull_selected", "_selected_action": [str(r.pk) for r in rows]},
            follow=True)

    def test_selecting_rows_starts_one_batch_for_all_of_them(self):
        with patch("api_calls.views.subprocess.Popen") as popen:
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
        with patch("api_calls.views.subprocess.Popen") as popen:
            response = self._act([self.a, self.file_row])
        argv = popen.call_args.args[0]
        self.assertNotIn(str(self.file_row.pk), argv.__str__().split("--rows")[-1])
        self.assertIn("1 skipped", response.content.decode())

    def test_selecting_only_unpullable_rows_starts_nothing(self):
        with patch("api_calls.views.subprocess.Popen") as popen:
            response = self._act([self.file_row])
        popen.assert_not_called()
        self.assertIn("None of those can be pulled", response.content.decode())

    def test_a_second_batch_is_refused_while_one_runs(self):
        PullJob.objects.create(kind="batch", status="running")
        with patch("api_calls.views.subprocess.Popen") as popen:
            self._act([self.a])
        popen.assert_not_called()


class PullAllTests(Base):
    def test_it_pulls_every_stale_row(self):
        with patch("api_calls.views.subprocess.Popen") as popen:
            self.client.post("/admin/api_calls/datasource/pull-all/")
        job = PullJob.objects.get(kind="batch")
        self.assertEqual(job.progress_total, 2)      # the two fewsnet rows
        popen.assert_called_once()

    def test_the_batch_names_its_rows_before_the_command_boots(self):
        """Pressing the button must put the plan on the page at once. The
        command takes seconds to start, and a bar that says only "2 data
        sources" for those seconds is a bar that looks stuck."""
        with patch("api_calls.views.subprocess.Popen"):
            self.client.post("/admin/api_calls/datasource/pull-all/")
        job = PullJob.objects.get(kind="batch")
        self.assertEqual({i["status"] for i in job.items}, {"pending"})
        self.assertEqual(sorted(i["label"] for i in job.items),
                         ["fewsnet/seasonal_calendar SDN",
                          "fewsnet/seasonal_calendar TCD"])

    def test_a_get_shows_what_would_be_pulled_and_starts_nothing(self):
        with patch("api_calls.views.subprocess.Popen") as popen:
            html = self.client.get("/admin/api_calls/datasource/pull-all/").content.decode()
        popen.assert_not_called()
        self.assertIn("one at a time", html)
        self.assertIn("seasonal_calendar", html)

    def test_pressing_it_when_nothing_is_stale_starts_nothing(self):
        SourceSync.objects.all().update(last_pulled_at=timezone.now())
        with patch("api_calls.views.subprocess.Popen") as popen:
            self.client.post("/admin/api_calls/datasource/pull-all/")
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)

    @override_settings(IPC_API_KEY="")
    def test_a_keyless_row_is_never_counted_as_stale(self):
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        with patch("api_calls.views.subprocess.Popen"):
            self.client.post("/admin/api_calls/datasource/pull-all/")
        self.assertEqual(PullJob.objects.get(kind="batch").progress_total, 2)
