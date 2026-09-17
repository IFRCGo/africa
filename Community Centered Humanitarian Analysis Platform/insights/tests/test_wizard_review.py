"""The review step shows one job's results and publishes what is chosen."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob, Insight, InsightCoding
from insights.verify import quote_sha1

QUOTE = "We walk four hours for water and the queue is longer every week."
OTHER = "The clinic closed when the staff left in March."


class ReviewStepTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.job = ExtractionJob.objects.create(status="loaded", label="2 files")
        self.doc = Document.objects.create(file_name="dtm.pdf", rel_path="insights/dtm.pdf")
        self.job.documents.add(self.doc)
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), document=self.doc, page=3,
            voice_type="community", channel="document_ai", stated_on="2026-04-02",
            iso3="TCD", status="pending", job=self.job, confidence="high")
        InsightCoding.objects.create(insight=self.insight, dimension="need", tag="water")
        self.other = Insight.objects.create(
            quote=OTHER, quote_sha1=quote_sha1(OTHER), document=self.doc, page=5,
            voice_type="community", channel="document_ai", stated_on="2026-04-02",
            iso3="TCD", status="pending", job=self.job)

    def url(self):
        return reverse("admin:insights_wizard_job", args=[self.job.id])

    def test_the_review_step_shows_the_quote_and_its_themes(self):
        body = self.client.get(self.url()).content.decode()
        self.assertIn(QUOTE, body)
        self.assertIn("need:water", body)
        self.assertIn("dtm.pdf", body)

    def test_it_shows_only_this_jobs_insights(self):
        stray = ExtractionJob.objects.create(status="loaded")
        Insight.objects.create(
            quote="Another batch entirely.", quote_sha1=quote_sha1("Another batch entirely."),
            voice_type="community", channel="document_ai", stated_on="2026-04-03",
            iso3="SDN", status="pending", job=stray)
        body = self.client.get(self.url()).content.decode()
        self.assertNotIn("Another batch entirely.", body)

    def test_publishing_the_selected_rows_only(self):
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "publish", "selected": [str(self.insight.id)]}, follow=True)
        self.insight.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertEqual(self.other.status, "pending")

    def test_rejecting_records_the_reviewer(self):
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "reject", "selected": [str(self.other.id)]}, follow=True)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, "rejected")
        self.assertEqual(self.other.reviewed_by_id, self.user.id)

    def test_a_decision_cannot_reach_another_jobs_insights(self):
        stray_job = ExtractionJob.objects.create(status="loaded")
        stray = Insight.objects.create(
            quote="Not this batch.", quote_sha1=quote_sha1("Not this batch."),
            voice_type="community", channel="document_ai", stated_on="2026-04-03",
            iso3="SDN", status="pending", job=stray_job)
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "publish", "selected": [str(stray.id)]}, follow=True)
        stray.refresh_from_db()
        self.assertEqual(stray.status, "pending")


class ReviewRowShowsChildrenTests(TestCase):
    def test_a_figure_and_a_corridor_are_rendered_under_the_quote(self):
        from django.template.loader import render_to_string

        from insights.models import Insight, InsightFigure, InsightMovement

        insight = Insight.objects.create(
            quote="0.7 million Sudanese refugees have been registered in Egypt.",
            iso3="EGY", stated_on="2026-03-01")
        InsightFigure.objects.create(
            insight=insight, figure_as_written="0.7 million", value=700000.0,
            unit="people", measures="Sudanese refugees registered in Egypt")
        InsightMovement.objects.create(
            insight=insight, origin_name_as_written="Sudan", origin_iso3="SDN",
            dest_name_as_written="Egypt", dest_iso3="EGY", flow_type="cross_border")

        html = render_to_string("insights/_review_row.html", {"insight": insight})
        self.assertIn("0.7 million", html)
        self.assertIn("Sudan", html)
        self.assertIn("cross_border", html)
