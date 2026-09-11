"""What Admin must guarantee: nothing publishes itself, and a quote cannot be
quietly rewritten.
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from data_track.models import Document, DocumentText
from insights.models import ExtractionJob, Insight
from insights.verify import quote_sha1

FIXTURES = Path(__file__).parent / "fixtures"
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


class LoadPayloadsActionTests(TestCase):
    """A payload file is written by an external agent that can be interrupted
    mid-write. A truncated or unreadable file must be reported and skipped,
    exactly like a rejected-but-well-formed one - never a 500 that takes the
    whole action, and every other file in the batch, down with it.
    """

    FLOOD_QUOTE = (
        "When it rains we get flash floods, and with the fighting around us the "
        "hospitals are gone — we have cholera now and nowhere to take the sick."
    )

    def setUp(self):
        self.user = User.objects.create_superuser("loader", "l@example.org", "pw")
        self.client.force_login(self.user)
        self.doc = Document.objects.create(
            file_name="x.pdf", rel_path="insights/x.pdf", report_date="2026-03-14")
        DocumentText.objects.create(
            document=self.doc, page=7, text=f"Participants said: {self.FLOOD_QUOTE}")
        self.job = ExtractionJob.objects.create(producer="external", status="queued")

    def _run_action(self, cache_dir):
        with override_settings(MCP_CACHE_DIR=str(cache_dir)):
            return self.client.post(reverse("admin:insights_extractionjob_changelist"), {
                "action": "load_payloads_for_job",
                "_selected_action": [str(self.job.id)],
            }, follow=True)

    def test_a_malformed_payload_does_not_crash_the_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            insights_dir = Path(tmp) / "insights"
            insights_dir.mkdir()
            (insights_dir / "truncated.json").write_text('{"insights": [', encoding="utf-8")

            response = self._run_action(tmp)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be read as JSON")
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "loaded")

    def test_a_good_payload_still_loads_beside_a_bad_one(self):
        good_payload = json.loads((FIXTURES / "payload_ok.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            insights_dir = Path(tmp) / "insights"
            insights_dir.mkdir()
            # Sorts before the good file, so this also proves a bad file earlier in
            # the batch does not stop a good one later in the batch from loading.
            (insights_dir / "a_truncated.json").write_text('{"insights": [', encoding="utf-8")
            (insights_dir / "b_good.json").write_text(
                json.dumps(good_payload), encoding="utf-8")

            response = self._run_action(tmp)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Insight.objects.count(), 1)
