"""The uploaded file is a courier, not an archive.

THE PLATFORM DOES NOT KEEP THE DOCUMENT. It keeps what was read out of it -
DocumentText, and the statements a person published from that text. The PDF
itself earns its place on disk only until the reading is done, and these tests
are what says so: released the moment the last pending statement is decided,
and swept after the retention cap whether anybody reviewed it or not.

WHAT IS NOT DELETED, and is asserted here so a later change has to argue with a
test rather than with a comment: the Document row, its DocumentText pages, and
every Insight written against them. Losing those would mean the reading had to
be paid for again, which is the opposite of the point.
"""
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

import fitz
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from data_track.models import Document
from insights import retention, review
from insights.models import ExtractionJob, Insight, InsightUpload
from insights.verify import quote_sha1


def a_pdf(text="The market has been closed for three weeks."):
    """A real one-page PDF, because catalogue_file actually opens it."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


class RetentionTestCase(TestCase):
    """MEDIA_ROOT is a temporary folder for the whole test, not a block of it.

    FileField.path resolves against whatever MEDIA_ROOT is when it is READ, so
    an assertion outside the override would ask about the real media folder.
    Enabling it in setUp puts every line of every test inside it.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)

    def an_upload(self, name="report.pdf", minutes_ago=0, document=None):
        """One stored file, optionally backdated past the cap.

        uploaded_at is auto_now_add, so the age has to be written with an
        UPDATE rather than passed to create().
        """
        upload = InsightUpload.objects.create(
            file=SimpleUploadedFile(name, a_pdf(), content_type="application/pdf"),
            label=name, document=document)
        if minutes_ago:
            InsightUpload.objects.filter(id=upload.id).update(
                uploaded_at=timezone.now() - timedelta(minutes=minutes_ago))
            upload.refresh_from_db()
        return upload

    def a_document(self, sha1="a" * 40):
        return Document.objects.create(
            file_name="report.pdf", rel_path=f"media/{sha1[:12]}-report.pdf",
            source_collection="insights", sha1=sha1, pages=1)

    def a_pending_insight(self, document, job=None, quote="The borehole is dry."):
        return Insight.objects.create(
            quote=quote, quote_sha1=quote_sha1(quote), voice_type="community",
            channel="document_ai", stated_on="2026-05-01", iso3="TCD",
            status="pending", document=document, job=job)


class SweepTests(RetentionTestCase):
    def test_a_file_past_the_cap_is_deleted_and_the_row_blanked(self):
        upload = self.an_upload(minutes_ago=31)
        stored = Path(upload.file.path)

        released = retention.sweep()

        self.assertEqual(released, 1)
        self.assertFalse(stored.exists())
        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_a_file_inside_the_cap_is_untouched(self):
        upload = self.an_upload(minutes_ago=29)
        stored = Path(upload.file.path)

        self.assertEqual(retention.sweep(), 0)

        self.assertTrue(stored.exists())
        upload.refresh_from_db()
        self.assertNotEqual(upload.file.name, "")

    @override_settings(INSIGHT_UPLOAD_RETENTION_MINUTES=5)
    def test_the_cap_is_configurable(self):
        upload = self.an_upload(minutes_ago=6)

        self.assertEqual(retention.sweep(), 1)

        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_a_file_being_read_right_now_survives_this_sweep(self):
        # Docling opens each document as it reaches it, so unlinking one
        # mid-run does not stop the run - it fails every document the run has
        # not got to yet, badged "Docling failed" with the intake text left in
        # place. The batch is left alone until the reading is over.
        document = self.a_document()
        upload = self.an_upload(minutes_ago=45, document=document)
        job = ExtractionJob.objects.create(status="converting")
        job.documents.add(document)

        self.assertEqual(retention.sweep(), 0)

        upload.refresh_from_db()
        self.assertNotEqual(upload.file.name, "")

    def test_the_file_goes_on_the_next_sweep_once_the_reading_is_over(self):
        document = self.a_document()
        upload = self.an_upload(minutes_ago=45, document=document)
        job = ExtractionJob.objects.create(status="converting")
        job.documents.add(document)
        retention.sweep()

        job.status = "converted"
        job.save(update_fields=["status"])

        self.assertEqual(retention.sweep(), 1)
        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_a_missing_file_is_released_rather_than_raising(self):
        # Someone emptied the folder by hand. The row must still come clean,
        # because a row claiming a file that is not there sends convert.py
        # looking for it.
        upload = self.an_upload(minutes_ago=31)
        Path(upload.file.path).unlink()

        self.assertEqual(retention.sweep(), 1)
        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_what_was_read_out_of_the_document_is_kept(self):
        document = self.a_document()
        self.an_upload(minutes_ago=31, document=document)
        insight = self.a_pending_insight(document)

        retention.sweep()

        self.assertTrue(Document.objects.filter(id=document.id).exists())
        insight.refresh_from_db()
        self.assertEqual(insight.status, "pending")


class ReleaseOnDecisionTests(RetentionTestCase):
    def test_publishing_the_last_pending_statement_releases_the_file(self):
        document = self.a_document()
        upload = self.an_upload(document=document)
        insight = self.a_pending_insight(document)

        review.publish(Insight.objects.filter(id=insight.id), self.user)

        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_a_statement_still_pending_keeps_the_file(self):
        document = self.a_document()
        upload = self.an_upload(document=document)
        first = self.a_pending_insight(document, quote="The borehole is dry.")
        self.a_pending_insight(document, quote="The road north is closed.")

        review.publish(Insight.objects.filter(id=first.id), self.user)

        upload.refresh_from_db()
        self.assertNotEqual(upload.file.name, "")

    def test_rejecting_the_last_pending_statement_releases_the_file(self):
        document = self.a_document()
        upload = self.an_upload(document=document)
        insight = self.a_pending_insight(document)

        review.reject(Insight.objects.filter(id=insight.id), self.user)

        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_another_document_in_the_batch_keeps_its_own_file(self):
        reviewed = self.a_document(sha1="a" * 40)
        untouched = self.a_document(sha1="b" * 40)
        untouched.rel_path = "media/bbbbbbbbbbbb-other.pdf"
        untouched.save(update_fields=["rel_path"])
        upload = self.an_upload(name="other.pdf", document=untouched)
        insight = self.a_pending_insight(reviewed)
        self.a_pending_insight(untouched, quote="The road north is closed.")

        review.publish(Insight.objects.filter(id=insight.id), self.user)

        upload.refresh_from_db()
        self.assertNotEqual(upload.file.name, "")

    def test_a_typed_statement_with_no_document_publishes_normally(self):
        quote = "We walked for four days."
        insight = Insight.objects.create(
            quote=quote, quote_sha1=quote_sha1(quote), voice_type="community",
            channel="manual", stated_on="2026-05-01", iso3="TCD", status="pending")

        moved = review.publish(Insight.objects.filter(id=insight.id), self.user)

        self.assertEqual(moved, 1)


class ReimportTests(RetentionTestCase):
    """Sending the same file again after its copy went.

    De-duplication is on Document.sha1 and it writes nothing, which is right
    while the first copy is still on disk and wrong once it is not: step 2 would
    have no file to read and would badge the document "Docling failed" while
    quietly keeping whatever text it already had.
    """

    def open_batch(self, label="1 file"):
        return self.client.post(
            reverse("admin:insights_wizard_batch"), {"label": label}).json()["job_id"]

    def send(self, job_id, name, payload):
        return self.client.post(
            reverse("admin:insights_wizard_batch_file", args=[job_id]),
            {"file": SimpleUploadedFile(name, payload, content_type="application/pdf"),
             "relative_path": ""}).json()

    def test_re_importing_a_released_document_stores_the_file_again(self):
        payload = a_pdf()
        first = self.open_batch()
        self.send(first, "report.pdf", payload)
        retention.release_document(Document.objects.get(source_collection="insights"))

        second = self.open_batch()
        body = self.send(second, "report.pdf", payload)

        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(Document.objects.filter(source_collection="insights").count(), 1)
        live = InsightUpload.objects.exclude(file="").get()
        self.assertTrue(Path(live.file.path).exists())
        self.assertEqual(live.document_id, body["document_id"])

    def test_re_importing_moves_the_pending_statements_to_the_new_batch(self):
        payload = a_pdf()
        first = self.open_batch()
        self.send(first, "report.pdf", payload)
        document = Document.objects.get(source_collection="insights")
        insight = self.a_pending_insight(document, job=ExtractionJob.objects.get(id=first))
        retention.release_document(document)

        second = self.open_batch()
        self.send(second, "report.pdf", payload)

        insight.refresh_from_db()
        self.assertEqual(insight.job_id, second)

    def test_a_published_statement_stays_with_the_batch_that_published_it(self):
        payload = a_pdf()
        first = self.open_batch()
        self.send(first, "report.pdf", payload)
        document = Document.objects.get(source_collection="insights")
        insight = self.a_pending_insight(document, job=ExtractionJob.objects.get(id=first))
        review.publish(Insight.objects.filter(id=insight.id), self.user)

        second = self.open_batch()
        self.send(second, "report.pdf", payload)

        insight.refresh_from_db()
        self.assertEqual(insight.job_id, first)

    def test_a_duplicate_whose_file_is_still_here_is_not_stored_twice(self):
        payload = a_pdf()
        job = self.open_batch()
        self.send(job, "report.pdf", payload)

        body = self.send(job, "report-copy.pdf", payload)

        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(InsightUpload.objects.exclude(file="").count(), 1)


class SweepWiringTests(RetentionTestCase):
    """The sweep has no scheduler behind it, so it rides on the wizard."""

    def test_opening_the_wizard_sweeps_a_stale_upload(self):
        upload = self.an_upload(minutes_ago=31)

        self.client.get(reverse("admin:insights_wizard_start"))

        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_prune_uploads_releases_a_stale_upload(self):
        upload = self.an_upload(minutes_ago=31)

        call_command("prune_uploads", stdout=StringIO())

        upload.refresh_from_db()
        self.assertEqual(upload.file.name, "")

    def test_prune_uploads_dry_run_leaves_the_file_alone(self):
        upload = self.an_upload(minutes_ago=31)

        call_command("prune_uploads", "--dry-run", stdout=StringIO())

        upload.refresh_from_db()
        self.assertNotEqual(upload.file.name, "")


class UnclaimedFileTests(RetentionTestCase):
    """A file in the folder that no row points at is nobody's to delete.

    THIS IS A REGRESSION TEST, not a preference. The first version of this
    module deleted unclaimed files from the sweep the wizard runs on every page
    load, and `manage.py test` emptied the deployment's real upload folder: the
    test database has no InsightUpload rows, so every real file qualified. The
    rule that replaced it is that nothing deletes a file because the database
    does not mention it - a view cannot know it is holding the right database,
    and neither can a cron.
    """

    def a_loose_file(self, name="stray.pdf", minutes_ago=0):
        import os

        folder = Path(self.media.name) / "insights"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(a_pdf())
        if minutes_ago:
            old = (timezone.now() - timedelta(minutes=minutes_ago)).timestamp()
            os.utime(path, (old, old))
        return path

    def test_the_sweep_never_touches_an_unclaimed_file(self):
        stray = self.a_loose_file(minutes_ago=31)

        self.assertEqual(retention.sweep(), 0)

        self.assertTrue(stray.exists())

    def test_prune_uploads_never_touches_one_either(self):
        stray = self.a_loose_file(minutes_ago=31)

        call_command("prune_uploads", stdout=StringIO())

        self.assertTrue(stray.exists())

    def test_an_empty_database_deletes_nothing_at_all(self):
        # The shape of the accident: no rows, real files, a sweep running.
        first = self.a_loose_file("one.pdf", minutes_ago=90)
        second = self.a_loose_file("two.pdf", minutes_ago=90)
        self.assertEqual(InsightUpload.objects.count(), 0)

        retention.sweep()
        call_command("prune_uploads", stdout=StringIO())

        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
