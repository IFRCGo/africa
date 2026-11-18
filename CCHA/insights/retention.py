"""How long an uploaded document stays on disk, and what happens when it goes.

THE UPLOADED FILE IS A COURIER. What this platform keeps is what was read out
of a document - the DocumentText pages Docling wrote, and the statements a
person published from them. The PDF itself is needed only until that reading is
done, and holding it afterwards is a second copy of somebody's report sitting in
MEDIA_ROOT for no one.

So a file leaves in one of two ways:

  * the reading finished - the document's last pending statement was published
    or rejected, and `release_document` runs from insights.review;
  * the reading never finished - `sweep` releases anything older than
    INSIGHT_UPLOAD_RETENTION_MINUTES, and that batch is started again from a
    fresh import.

`sweep` FOLLOWS ROWS, NEVER THE FOLDER, and nothing here deletes a file because
the database does not mention it. An earlier version did, from the wizard's own
page-load sweep, and `manage.py test` emptied this deployment's upload folder:
the test database legitimately has no rows, so every real file looked
unclaimed. "Nothing points at this file" is a claim about one database used to
destroy something somewhere else, and a view cannot know it is holding the
right database. A file left behind by deleting an upload in Admin is therefore
left behind - a person can remove it, and no code here will.

RELEASING IS NOT DELETING THE ROW. The file is unlinked and InsightUpload.file
is blanked; the row stays, with its label, its iso3, its uploaded_at and its
link to the Document. That empty FileField is a state the rest of the app
already reads: convert.source_path does `.exclude(file="")` when it looks for a
document on disk, so a released upload is simply not offered as one.

NOTHING DERIVED IS TOUCHED. Document, DocumentText and Insight rows all stay
exactly where they are - they are the reading, and paying for it twice is the
outcome this module exists to make unnecessary.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from insights.models import ExtractionJob, InsightUpload

DEFAULT_RETENTION_MINUTES = 30


def retention_minutes():
    """The cap, read at call time so a test or a .env change is honoured."""
    return int(getattr(settings, "INSIGHT_UPLOAD_RETENTION_MINUTES", None)
               or DEFAULT_RETENTION_MINUTES)


def release(upload):
    """Unlink one upload's file and blank the field. True if there was one.

    Storage.delete swallows a file that is already gone, which is deliberate:
    a row still claiming a file somebody removed by hand is exactly the row
    that sends convert.source_path looking for it.
    """
    name = upload.file.name
    if not name:
        return False

    upload.file.storage.delete(name)
    upload.file = ""
    upload.save(update_fields=["file"])
    return True


def release_document(document):
    """Release every copy of one document. Returns how many files went.

    A document may have more than one upload row - re-imported after an earlier
    copy was released, it gets a second one - so this is a loop, not a get().
    """
    document_id = getattr(document, "id", document)
    return sum(release(upload) for upload in
               InsightUpload.objects.filter(document_id=document_id).exclude(file=""))


def release_if_reviewed(document_ids, *, statuses=("pending",)):
    """Release the file of every one of these documents with nothing left to review.

    Called from insights.review after a decision. A document whose queue still
    holds a pending statement keeps its file: the reviewer reading that
    statement may still want the batch re-read.
    """
    from insights.models import Insight

    released = 0
    for document_id in {document_id for document_id in document_ids if document_id}:
        if Insight.objects.filter(
                document_id=document_id, status__in=statuses).exists():
            continue
        released += release_document(document_id)
    return released


def _is_being_read(upload):
    """Is Docling reading this document right now?

    Docling opens each file as it reaches it, so unlinking one mid-run does not
    stop the run: it fails every document the run has not got to yet, and each
    of those is badged "Docling failed" and quietly keeps its intake text. The
    cap is not a deadline worth that, so a batch at "converting" is skipped and
    swept on the next pass instead - within a page load of the read finishing.

    A job killed rather than raised stays at "converting" and would hold its
    files indefinitely; the "Reset stuck job to queued" admin action is the way
    out, and it is the same way out that job already needed.
    """
    if not upload.document_id:
        return False
    return ExtractionJob.objects.filter(
        documents=upload.document_id, status="converting").exists()


def sweep(now=None):
    """Release every stored file older than the cap. Returns how many went.

    There is no scheduler in this deployment - the compose file runs db, web
    and pgadmin - so this is called from the wizard's own views and from
    `manage.py prune_uploads`.
    """
    cutoff = (now or timezone.now()) - timedelta(minutes=retention_minutes())
    stale = InsightUpload.objects.exclude(file="").filter(uploaded_at__lt=cutoff)
    return sum(release(upload) for upload in stale if not _is_being_read(upload))


def released_documents(job):
    """The job's documents whose file is gone and whose text was never upgraded.

    STEP 2 CANNOT BE HONEST WITHOUT THIS. convert_documents turns a missing
    file into a per-document failure, so a swept batch read anyway badges every
    document "Docling failed", silently keeps the weaker PyMuPDF intake text,
    and lets extraction run on it. The person needs the one fact none of that
    conveys: the files went, and the way forward is a new import.

    A document that WAS read successfully is not in this list. Its Docling text
    is in the database; the missing file costs it nothing.

    Only a document that had an upload counts. One catalogued from a registered
    folder and since moved is a different problem with a different answer, and
    saying "released" about it would be a lie.
    """
    had_upload = set(InsightUpload.objects.filter(
        document__in=job.documents.all()).values_list("document_id", flat=True))
    still_held = set(InsightUpload.objects.filter(
        document_id__in=had_upload).exclude(file="").values_list("document_id", flat=True))
    read_already = set(job.documents.filter(
        conversion__ok=True).values_list("id", flat=True))
    gone = had_upload - still_held - read_already
    return list(job.documents.filter(id__in=gone))


RELEASED_MESSAGE = (
    "These files were released - start a new import. "
    "An uploaded document is kept for %s minutes; the text already read out of "
    "these ones is still here, and so is anything extracted from it."
)


def released_sentence():
    """The sentence step 2 shows, with this deployment's own cap in it."""
    return RELEASED_MESSAGE % retention_minutes()
