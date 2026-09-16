"""The section, the button, and the rows that must not offer one."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from external_data.models import SourceSync
from mcp.models import PullJob


class AdminTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "tester", "t@example.org", "pw")
        self.client.force_login(self.user)
        self.api_row = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")
        self.file_row = SourceSync.objects.create(
            source="excel", dataset="idps", iso3="SDN", variant="sudan-idps-workbook")


class ListTests(AdminTestCase):
    def test_the_section_is_reachable(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_the_source_is_shown_by_its_display_name(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "FEWS NET")

    @override_settings(IPC_API_KEY="", HDX_API_TOKEN="")
    def test_a_row_whose_key_is_missing_says_which_one(self):
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "IPC_API_KEY")

    def test_a_file_based_row_offers_no_button(self):
        """A button that cannot work is worse than no button."""
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertNotContains(response, f"pull/{self.file_row.pk}/")

    def test_an_api_row_offers_one(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, f"pull/{self.api_row.pk}/")

    def test_a_file_based_row_names_the_command_that_loads_it(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "load_workbooks")


class PullTests(AdminTestCase):
    def _url(self, row):
        return f"/admin/mcp/datasource/pull/{row.pk}/"

    def test_pressing_the_button_creates_a_queued_job_and_launches_it(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self.client.post(self._url(self.api_row))
        self.assertEqual(response.status_code, 302)
        job = PullJob.objects.get()
        self.assertEqual(job.source, "fewsnet")
        self.assertEqual(job.requested_by, self.user)
        popen.assert_called_once()

    def test_the_command_is_launched_detached(self):
        """start_new_session, or a child that outlives its worker reparents to
        gunicorn's arbiter, which misreads its exit code and halts the server."""
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.api_row))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("refresh_external", popen.call_args.args[0])

    def test_the_country_and_variant_reach_the_command(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.api_row))
        argv = popen.call_args.args[0]
        self.assertIn("--iso3", argv)
        self.assertIn("TCD", argv)

    def test_a_get_does_not_start_anything(self):
        """A pull is a change. It must not be triggerable by following a link."""
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self.client.get(self._url(self.api_row))
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_an_anonymous_visitor_is_refused(self):
        self.client.logout()
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self.client.post(self._url(self.api_row))
        popen.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_a_busy_source_is_refused_without_launching(self):
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD",
                               status="running")
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.api_row))
        popen.assert_not_called()

    def test_a_file_based_row_is_refused(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.file_row))
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)

    @override_settings(IPC_API_KEY="")
    def test_a_keyless_source_is_refused_without_launching(self):
        row = SourceSync.objects.create(source="ipc", dataset="food_security",
                                        iso3="SDN")
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(row))
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)


class JobPageTests(AdminTestCase):
    def test_a_job_page_shows_its_status(self):
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="failed", message="503 from fdw.fews.net")
        response = self.client.get(f"/admin/mcp/datasource/job/{job.id}/")
        self.assertContains(response, "503 from fdw.fews.net")

    def test_the_status_endpoint_reports_the_job(self):
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="running")
        response = self.client.get(f"/admin/mcp/datasource/job/{job.id}/status/")
        self.assertEqual(response.json()["status"], "running")
