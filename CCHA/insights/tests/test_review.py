"""Publishing is a decision, and it is recorded as one."""
from django.contrib.auth.models import User
from django.test import TestCase

from insights import review
from insights.models import Insight
from insights.verify import quote_sha1

QUOTE = "The borehole has been dry since the rains failed."


class ReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="manual", stated_on="2026-05-01", iso3="TCD", status="pending",
        )

    def test_publishing_records_who_and_when(self):
        changed = review.publish(Insight.objects.filter(id=self.insight.id), self.user)
        self.insight.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertIsNotNone(self.insight.reviewed_at)

    def test_rejecting_records_who_and_when(self):
        changed = review.reject(Insight.objects.filter(id=self.insight.id), self.user)
        self.insight.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(self.insight.status, "rejected")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)

    def test_only_the_selected_rows_move(self):
        other = Insight.objects.create(
            quote="A second statement.", quote_sha1=quote_sha1("A second statement."),
            voice_type="community", channel="manual", stated_on="2026-05-02",
            iso3="TCD", status="pending",
        )
        review.publish(Insight.objects.filter(id=self.insight.id), self.user)
        other.refresh_from_db()
        self.assertEqual(other.status, "pending")
