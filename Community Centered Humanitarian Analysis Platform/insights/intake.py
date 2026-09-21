"""Turn a file on disk into a Document plus its page text.

WHY THIS DOES NOT COLLIDE WITH THE PIPELINE (spec §7.2), all verified:

  s01_catalog  walks only SOURCE_COLLECTIONS and never deletes, so it neither
               sees nor removes these documents.
  s02_extract  selects Document.objects.filter(texts__isnull=True). Because we
               write DocumentText here, these are never selected - so s02 never
               tries to reopen a file at a path it cannot resolve.
  s03_parse    dispatches its positional parsers on `family` alone (811/813/817).
               'insight_source' matches none of them. Its taxonomy tagger does run
               over every document with text, so these get regex-tagged into
               narrative_tags like any other - which is harmless: those tags are
               analyst voice, they live in a table rebuilt on every run, and they
               never touch `insights`.

rel_path is relative to SOURCE_ROOT when the file is under it, so it resolves
exactly as a UNHCR PDF's does. Otherwise it is content-addressed:
'media/<sha1[:12]>-<name>'. A basename alone is NOT unique - "assessment.pdf"
is the most likely filename in the world for an upload - so two different
files sharing a name would otherwise collide and catalogue_file's dedup would
silently hand the second upload the first upload's Document: wrong sha1,
wrong pages, wrong page text, no error raised. Prefixing with the content's
own sha1 fixes that: identical content (the same file uploaded twice) hashes
to the same prefix and so dedups correctly, exactly as intended; different
content, even under an identical name, hashes to a different prefix and can
never collide.
"""
import hashlib
from datetime import date
from pathlib import Path

import fitz
from django.conf import settings
from django.db import transaction

from data_track.models import Document, DocumentText
from insights import document_date
from insights.models import ExtractionJob

SUFFIXES = {".pdf", ".docx"}


def sha1_of(path, chunk=1 << 20):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path, sha1):
    """Relative to SOURCE_ROOT when it is under it; content-addressed otherwise.

    sha1 must already be computed by the caller - it is what makes the
    out-of-tree case collision-proof (see the module docstring).
    """
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(settings.SOURCE_ROOT).resolve()).as_posix()
    except ValueError:
        return f"media/{sha1[:12]}-{path.name}"


def pdf_metadata(path):
    """The PDF's own /CreationDate etc, or {} for a DOCX or an unreadable file.

    Read here rather than in document_date so that module stays testable without
    a file on disk - it arbitrates between dates, it does not open documents.

    Public because convert.py re-runs date inference after a successful
    conversion and needs the same metadata this one reads.
    """
    if path.suffix.lower() != ".pdf":
        return {}
    try:
        with fitz.open(str(path)) as pdf:
            return pdf.metadata or {}
    except Exception:  # noqa: BLE001 - a missing date is not worth failing intake
        return {}


def _pages_of(path):
    """[(page_number, text)] - PyMuPDF for PDF, python-docx for DOCX."""
    if path.suffix.lower() == ".docx":
        from docx import Document as Docx
        # A DOCX has no pages until it is rendered, so the whole body is page 1.
        # Saying so here is cheaper than someone later reading page 1 as "the
        # first page of the printed document".
        body = "\n".join(p.text for p in Docx(str(path)).paragraphs)
        return [(1, body)]

    with fitz.open(str(path)) as pdf:
        return [(n + 1, pdf[n].get_text("text")) for n in range(len(pdf))]


def catalogue_file(path, iso3=None, report_date=None):
    """Create the Document and its page rows. Returns the existing one if known."""
    path = Path(path)
    # sha1 has to exist before rel_path is built, because the out-of-tree case
    # content-addresses on it - and before the dedup lookup, since that lookup
    # is keyed on rel_path.
    digest = sha1_of(path)
    rel = relative_path(path, digest)

    existing = Document.objects.filter(rel_path=rel).first()
    if existing is not None:
        return existing

    # A falsy report_date (None, or "" from an Admin form's optional field)
    # becomes None outright rather than reaching fromisoformat, which raises
    # on "". A non-empty string is parsed rather than handed straight to the
    # DateField: Django would accept it and the in-memory object would keep
    # the string, so a later `document.report_date.isoformat()` - which the
    # Phase 2 extractor calls - would raise on a freshly created object but
    # not on a reloaded one.
    if not report_date:
        report_date = None
    elif isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    pages = _pages_of(path)

    # Nobody supplied a date, so read one out of the document. `date_source`
    # records which source won, using the vocabulary the pipeline already writes
    # there. A guess whose sources disagree is NOT written: report_date stays
    # null and the wizard asks, because a wrong date silently mis-places every
    # insight in the document on the dashboard timeline. See document_date.py.
    date_source = "intake"
    if report_date is None:
        guess = document_date.infer(path, pages, pdf_metadata(path))
        if guess.date is not None and not guess.needs_person:
            report_date, date_source = guess.date, guess.source

    # Atomic because a crash between the Document and its DocumentText rows
    # would strand the document permanently: catalogue_file's own dedup would
    # keep returning that same textless row on every later attempt, and for
    # a media/-rooted upload s02 cannot resolve the path either, so nothing
    # would ever backfill the text.
    with transaction.atomic():
        document = Document.objects.create(
            file_name=path.name,
            rel_path=rel,
            source_collection="insights",
            family="insight_source",
            country_focus=iso3,
            report_date=report_date,
            date_source=date_source,
            pages=len(pages),
            file_size=path.stat().st_size,
            sha1=digest,
        )
        DocumentText.objects.bulk_create(
            [DocumentText(document=document, page=number, text=text) for number, text in pages]
        )
    return document


def catalogue_folder(folder):
    """Catalogue everything in a registered folder and open a job for it."""
    root = Path(folder.path)
    if not root.is_dir():
        from insights import document_roots
        raise FileNotFoundError(
            f"{folder.path} is not a directory inside this container. "
            f"{document_roots.sentence()}"
        )

    pattern = "**/*" if folder.recursive else "*"
    files = sorted(p for p in root.glob(pattern) if p.suffix.lower() in SUFFIXES)

    job = ExtractionJob.objects.create(folder=folder, producer="external", status="queued")
    for path in files:
        document = catalogue_file(path, iso3=folder.default_iso3)
        # A document already catalogued by an earlier job is attached to this
        # one too - the M2M has no ordering opinion about which job "owns" a
        # document, and extract_insights will re-extract it here on purpose.
        job.documents.add(document)
    job.documents_total = len(files)
    job.save(update_fields=["documents_total"])
    return job
