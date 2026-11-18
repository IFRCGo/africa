"""The section shows two front doors, and the machinery stays reachable."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights.models import ExtractionJob


class WizardIndexTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_the_index_offers_part_1_and_part_2(self):
        response = self.client.get(reverse("admin:app_list", args=["insights"]))
        body = response.content.decode()
        self.assertIn("Part 1 — Documents → insights", body)
        self.assertIn("Part 2 — Insights", body)

    def test_the_machinery_is_off_the_index(self):
        body = self.client.get(reverse("admin:app_list", args=["insights"])).content.decode()
        self.assertNotIn("Extraction jobs", body)
        self.assertNotIn("Insight folders", body)
        self.assertNotIn("Insight uploads", body)

    def test_the_machinery_is_still_reachable_by_url(self):
        # Hidden from the index is not the same as gone: "Reset stuck job to
        # queued" is the only way out of a job whose process was killed.
        for url_name in ("admin:insights_extractionjob_changelist",
                         "admin:insights_insightfolder_changelist",
                         "admin:insights_insightupload_changelist"):
            self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_the_wizard_lists_recent_batches(self):
        ExtractionJob.objects.create(status="loaded", label="4 files")
        response = self.client.get(
            reverse("admin:insights_documentstoinsights_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("4 files", response.content.decode())
