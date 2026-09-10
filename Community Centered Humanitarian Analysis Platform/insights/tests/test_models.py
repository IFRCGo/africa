"""The constraints, proved rather than assumed.

The duplicate-manual-entry test is the one that matters: a hand-typed insight has
a null document and a null page, and under PostgreSQL's default rule two NULLs
never collide - so without nulls_distinct=False every duplicate would be accepted
silently. This is the same trap admin_areas and source_sync already document.
"""
import tempfile

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from insights.models import ExtractionJob, Insight, InsightCoding, InsightFolder


def make_insight(**kwargs):
    defaults = dict(
        quote="We have cholera now and nowhere to take the sick.",
        quote_sha1="a" * 40,
        voice_type="community",
        channel="manual",
        stated_on="2026-03-14",
        iso3="ETH",
        method="manual",
        status="pending",
    )
    defaults.update(kwargs)
    return Insight.objects.create(**defaults)


class InsightConstraintTests(TestCase):
    def test_two_identical_manual_insights_collide(self):
        """Null document and null page: quote_sha1 alone must distinguish them."""
        make_insight()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_insight()

    def test_the_same_quote_on_two_pages_is_two_rows(self):
        make_insight(quote_sha1="b" * 40, page=1)
        make_insight(quote_sha1="b" * 40, page=2)
        self.assertEqual(Insight.objects.count(), 2)

    def test_status_defaults_to_pending(self):
        self.assertEqual(make_insight().status, "pending")

    def test_people_affected_and_severity_are_optional(self):
        row = make_insight()
        self.assertIsNone(row.people_affected)
        self.assertIsNone(row.severity)


class InsightCodingTests(TestCase):
    def test_a_coding_cannot_repeat_within_one_insight(self):
        insight = make_insight()
        InsightCoding.objects.create(insight=insight, dimension="hazard", tag="flooding")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsightCoding.objects.create(
                    insight=insight, dimension="hazard", tag="flooding")

    def test_one_insight_carries_many_codings(self):
        insight = make_insight()
        for dim, tag in [("hazard", "flooding"), ("hazard", "disease_outbreak"),
                         ("need", "health"), ("need", "water_wash")]:
            InsightCoding.objects.create(insight=insight, dimension=dim, tag=tag)
        self.assertEqual(insight.codings.count(), 4)


class ExtractionJobTests(TestCase):
    def test_counters_start_at_zero(self):
        job = ExtractionJob.objects.create(producer="external")
        self.assertEqual(job.insights_proposed, 0)
        self.assertEqual(job.insights_rejected_unverifiable, 0)
        self.assertEqual(job.insights_skipped_reviewed, 0)
        self.assertEqual(job.status, "queued")


class InsightFolderTests(TestCase):
    def test_an_unreachable_path_is_a_validation_error_not_a_saved_row(self):
        """Spec §7: Admin validates on save and says so, rather than failing in a job."""
        folder = InsightFolder(label="gone", path="/nowhere/at/all")
        with self.assertRaises(ValidationError) as caught:
            folder.full_clean()
        self.assertIn("path", caught.exception.error_dict)

    def test_a_real_directory_validates(self):
        folder = InsightFolder(label="tmp", path=tempfile.gettempdir())
        folder.full_clean()   # must not raise
