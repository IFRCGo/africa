"""What Admin must guarantee: nothing publishes itself, and a quote cannot be
quietly rewritten.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from data_track.models import Document, DocumentText
from insights.models import Insight
from insights.verify import quote_sha1

QUOTE = "We have cholera now and nowhere to take the sick."


class AdminReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.doc = Document.objects.create(file_name="x.pdf", rel_path="insights/x.pdf")
        DocumentText.objects.create(document=self.doc, page=1, text=f"They said: {QUOTE}")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), document=self.doc, page=1,
            voice_type="community", channel="document_ai", stated_on="2026-03-14",
            iso3="ETH", method="llm", status="pending",
        )

    def test_the_changelist_loads(self):
        response = self.client.get(reverse("admin:insights_insight_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_publishing_records_who_and_when(self):
        self.client.post(reverse("admin:insights_insight_changelist"), {
            "action": "publish_selected",
            "_selected_action": [str(self.insight.id)],
        }, follow=True)
        self.insight.refresh_from_db()
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertIsNotNone(self.insight.reviewed_at)

    def test_editing_the_quote_recomputes_the_fingerprint(self):
        self.insight.quote = "We have cholera now and nowhere to take the sick!"
        self.insight.save()
        self.assertEqual(self.insight.quote_sha1, quote_sha1(self.insight.quote))

    def test_a_manual_insight_saves_without_a_document(self):
        row = Insight.objects.create(
            quote="A statement relayed by the field team.",
            quote_sha1=quote_sha1("A statement relayed by the field team."),
            voice_type="community", channel="manual", stated_on="2026-04-01",
            iso3="TCD", method="manual", status="published",
        )
        self.assertIsNone(row.document_id)
        self.assertEqual(row.status, "published")
