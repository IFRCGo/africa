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
exactly as a UNHCR PDF's does; otherwise it is 'media/<name>'. It is unique
either way, which is what s01 matches on.
"""
import hashlib
from datetime import date
from pathlib import Path

import fitz
from django.conf import settings

from data_track.models import Document, DocumentText
from insights.models import ExtractionJob

SUFFIXES = {".pdf", ".docx"}


def sha1_of(path, chunk=1 << 20):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path):
    """Relative to SOURCE_ROOT when it is under it; 'media/<name>' otherwise."""
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(settings.SOURCE_ROOT).resolve()).as_posix()
    except ValueError:
        return f"media/{path.name}"


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
    rel = relative_path(path)

    existing = Document.objects.filter(rel_path=rel).first()
    if existing is not None:
        return existing

    # Parse a string date rather than handing it straight to the DateField. Django
    # would accept it and the in-memory object would keep the string, so a later
    # `document.report_date.isoformat()` - which the Phase 2 extractor calls -
    # would raise on a freshly created object but not on a reloaded one.
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    pages = _pages_of(path)
    document = Document.objects.create(
        file_name=path.name,
        rel_path=rel,
        source_collection="insights",
        family="insight_source",
        country_focus=iso3,
        report_date=report_date or None,
        date_source="intake",
        pages=len(pages),
        file_size=path.stat().st_size,
        sha1=sha1_of(path),
    )
    DocumentText.objects.bulk_create(
        [DocumentText(document=document, page=number, text=text) for number, text in pages]
    )
    return document


def catalogue_folder(folder):
    """Catalogue everything in a registered folder and open a job for it."""
    root = Path(folder.path)
    if not root.is_dir():
        raise FileNotFoundError(
            f"{folder.path} is not a directory inside this container. Folders must "
            f"live under a mounted path - /work covers the whole SUDAN Ops folder."
        )

    pattern = "**/*" if folder.recursive else "*"
    files = sorted(p for p in root.glob(pattern) if p.suffix.lower() in SUFFIXES)

    job = ExtractionJob.objects.create(folder=folder, producer="external", status="queued")
    for path in files:
        catalogue_file(path, iso3=folder.default_iso3)
    job.documents_total = len(files)
    job.save(update_fields=["documents_total"])
    return job
