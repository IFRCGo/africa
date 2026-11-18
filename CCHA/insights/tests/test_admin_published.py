"""Where a published statement is read, and where it is no longer listed.

Part 2 is a work queue: once a statement is published the decision is made and
leaving it there buries the rows that still need one. Part 3 is the archive of
everything published - view-only, because a published quote has been verified
against the page text and an edit there would invalidate that check with
nothing left to say so.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights.models import Insight, PublishedInsight
from insights.verify import quote_sha1

PENDING = "The water point has been dry for three weeks."
PUBLISHED = "We walk two hours to the next borehole and queue half a day."


def _insight(quote, status):
    return Insight.objects.create(
        quote=quote, quote_sha1=quote_sha1(quote), voice_type="community",
        channel="manual", stated_on="2026-05-01", iso3="SDN", method="manual",
        status=status,
    )


class PartTwoIsAQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.pending = _insight(PENDING, "pending")
        self.published = _insight(PUBLISHED, "published")
        self.rejected = _insight("A line the model invented.", "rejected")

    def test_the_changelist_leaves_out_published_rows(self):
        response = self.client.get(reverse("admin:insights_insight_changelist"))
        self.assertContains(response, PENDING[:40])
        self.assertNotContains(response, PUBLISHED[:40])

    def test_a_rejected_row_stays_because_it_still_wants_a_reason(self):
        response = self.client.get(reverse("admin:insights_insight_changelist"))
        self.assertContains(response, "A line the model invented.")

    def test_a_published_row_cannot_be_opened_through_part_two(self):
        response = self.client.get(
            reverse("admin:insights_insight_change", args=[self.published.id]))
        self.assertEqual(response.status_code, 302)   # admin redirects, "does not exist"


class PartThreeIsAnArchiveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reader", "a@example.org", "pw")
        self.client.force_login(self.user)
        self.pending = _insight(PENDING, "pending")
        self.published = _insight(PUBLISHED, "published")

    def test_it_lists_published_rows_only(self):
        response = self.client.get(
            reverse("admin:insights_publishedinsight_changelist"))
        self.assertContains(response, PUBLISHED[:40])
        self.assertNotContains(response, PENDING[:40])

    def test_nothing_on_it_adds_a_row(self):
        response = self.client.get(
            reverse("admin:insights_publishedinsight_changelist"))
        # The sidebar carries "addlink" for other models, so look for this
        # model's own add URL rather than the CSS class.
        self.assertNotContains(response, "/admin/insights/publishedinsight/add/")
        self.assertEqual(
            self.client.get(
                reverse("admin:insights_publishedinsight_add")).status_code, 403)

    def test_a_row_opens_read_only(self):
        response = self.client.get(
            reverse("admin:insights_publishedinsight_change", args=[self.published.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, PUBLISHED)
        self.assertNotContains(response, 'name="_save"')

    def test_posting_an_edit_changes_nothing(self):
        self.client.post(
            reverse("admin:insights_publishedinsight_change", args=[self.published.id]),
            {"quote": "Something else entirely.", "stated_on": "2026-05-01"})
        self.published.refresh_from_db()
        self.assertEqual(self.published.quote, PUBLISHED)

    def test_un_publishing_sends_it_back_to_the_queue(self):
        self.client.post(reverse("admin:insights_publishedinsight_changelist"), {
            "action": "unpublish_selected",
            "_selected_action": [str(self.published.id)],
        }, follow=True)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, "pending")
        # No longer a standing decision, so it is no longer anybody's.
        self.assertIsNone(self.published.reviewed_by_id)
        self.assertIsNone(self.published.reviewed_at)
        # And Part 2 has it back.
        response = self.client.get(reverse("admin:insights_insight_changelist"))
        self.assertContains(response, PUBLISHED[:40])

    def test_the_proxy_reads_the_same_table(self):
        self.assertEqual(PublishedInsight.objects.count(), Insight.objects.count())
