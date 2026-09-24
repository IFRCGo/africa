"""Read a document properly, then put that text where the model will find it.

THE RULE THIS KEEPS. The text the model reads and the text
verify.quote_is_verbatim checks a returned quote against are the same
DocumentText rows. So Docling's output does not go somewhere new - it REPLACES
those rows. Any design where the model gets markdown while DocumentText keeps
PyMuPDF text would send insights_rejected_unverifiable to essentially 100%
with nothing anywhere saying why.

WHY INTAKE STILL RUNS PyMuPDF. Not a hedge - a hazard fix.
data_pipeline/steps/s02_extract_text.py selects
Document.objects.filter(texts__isnull=True), so a document left textless
between intake and conversion would be picked up by any pipeline run and fail
there on a media/ path it cannot resolve. Those rows are a placeholder, and
they are also what the fallback below falls back TO.
"""
import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from data_track.models import DocumentText
from insights import docling_reader, document_date
from insights.intake import pdf_metadata
from insights.models import Conversion, Insight, InsightUpload


def source_path(document):
    """Where this document's file actually is on disk.

    THE UPLOAD IS ASKED FIRST, AND IT IS ASKED BY ITS OWN FileField. An
    upload's rel_path is "media/<sha1[:12]>-<name>", which only resolves under
    BASE_DIR while MEDIA_ROOT sits at its default - and MEDIA_ROOT is a
    documented .env setting, so that is an assumption, not a fact.
    InsightUpload.file.path is Django's own answer to the same question and
    stays right wherever MEDIA_ROOT points.

    Getting this wrong is quiet rather than loud: convert_document turns a
    FileNotFoundError into a per-document failure, so every upload would be
    badged "Docling failed" and silently keep its PyMuPDF text.
    """
    upload = (InsightUpload.objects.filter(document=document)
              .exclude(file="").order_by("-id").first())
    if upload is not None:
        candidate = Path(upload.file.path)
        if candidate.exists():
            return candidate

    # Catalogued from a registered folder: resolves under SOURCE_ROOT exactly
    # as every pipeline document does.
    candidate = Path(settings.SOURCE_ROOT) / document.rel_path
    if candidate.exists():
        return candidate

    return Path(settings.BASE_DIR) / document.rel_path


def cache_paths(document):
    """(json, markdown). Content-addressed, so the same file re-read is the same pair."""
    root = Path(settings.API_CACHE_DIR) / "insights" / "converted"
    return root / f"{document.sha1}.json", root / f"{document.sha1}.md"


def _record(document, job, engine, ok, pages, message="", version="", markdown_path=""):
    """Write (or overwrite) this document's one Conversion row."""
    row, _ = Conversion.objects.update_or_create(
        document=document,
        defaults={
            "job": job, "engine": engine, "ok": ok, "pages": pages,
            "message": message or "", "docling_version": version or None,
            "markdown_path": markdown_path or None,
        },
    )
    return row


def _save_artifacts(document, pages, version):
    """Write the converted text to disk BEFORE it is loaded.

    The rule CLAUDE.md states for external data - fetch, save, then load - for
    the same reason: a re-load must not have to pay for OCR twice. The .json is
    the re-loadable one; the .md is for a person to open.
    """
    json_path, md_path = cache_paths(document)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({
        "engine": "docling",
        "docling_version": version,
        "converted_at": timezone.now().isoformat(timespec="seconds"),
        "rel_path": document.rel_path,
        "sha1": document.sha1,
        "pages": [{"page": number, "markdown": text} for number, text in pages],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(
        "\n\n".join(f"<!-- page {number} -->\n{text}" for number, text in pages),
        encoding="utf-8")
    return md_path


def _load_artifacts(document):
    """[(page, markdown)] and the version from the cache, or None if absent."""
    json_path, _ = cache_paths(document)
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pages = [(int(item["page"]), item["markdown"]) for item in payload.get("pages", [])]
    return (pages, payload.get("docling_version", "")) if pages else None


def _replace_text(document, pages, path):
    """Swap this document's page rows for the converted ones, atomically.

    Atomic because a crash between the delete and the create leaves the
    document textless - which is exactly the s02 hazard the module docstring
    exists to avoid, and it would be permanent: for a media/-rooted upload s02
    cannot resolve the path either, so nothing would ever backfill it.
    """
    date_fields = []
    # Nobody has a date for this document. There is text now that there was not
    # before - a scanned report that gave PyMuPDF an empty string can finally
    # say when it was written. A guess whose sources DISAGREE is still not
    # written: a wrong date silently mis-places every insight in the document
    # on the dashboard timeline, which is document_date's whole reason to
    # exist and conversion must not quietly undo it.
    if document.report_date is None:
        guess = document_date.infer(path, pages, pdf_metadata(Path(path)))
        if guess.date is not None and not guess.needs_person:
            document.report_date, document.date_source = guess.date, guess.source
            date_fields = ["report_date", "date_source"]

    with transaction.atomic():
        DocumentText.objects.filter(document=document).delete()
        DocumentText.objects.bulk_create(
            [DocumentText(document=document, page=number, text=text)
             for number, text in pages], batch_size=200)
        document.pages = len(pages)
        document.save(update_fields=["pages"] + date_fields)


def convert_document(document, path, job=None, reload_only=False):
    """Read one document with Docling and replace its text. Returns a Conversion.

    NEVER RAISES FOR A BAD DOCUMENT. An unreadable file is an expected input in
    a folder of two hundred, not an exceptional one - the same judgement
    verify.quote_is_verbatim makes when it returns False for a missing page. A
    failure is a Conversion row with ok=False, and the batch carries on.
    """
    path = Path(path)

    # The one refusal. Replacing page text under an existing insight would
    # invalidate the quote it was verified against, with nothing afterwards
    # able to tell. Per document, not per job: a Document can belong to several.
    if Insight.objects.filter(document=document).exclude(status="rejected").exists():
        return _record(
            document, job, engine="skipped", ok=False, pages=document.pages,
            message=("Not re-read: insights still depend on this document's text. "
                     "Reject them first if it must be read again."))

    try:
        if reload_only:
            cached = _load_artifacts(document)
            if cached is None:
                raise FileNotFoundError(f"no cached conversion for {document.sha1}")
            pages, version = cached
            markdown_path = str(cache_paths(document)[1])
        else:
            pages, version = docling_reader.read(path)
            if not pages:
                raise ValueError("Docling returned no pages")
            markdown_path = str(_save_artifacts(document, pages, version))

        _replace_text(document, pages, path)
    except docling_reader.DoclingDisabled as exc:
        return _record(document, job, engine="pymupdf", ok=False, pages=document.pages,
                       message=f"Docling is disabled ({exc}); intake text left in place.")
    except Exception as exc:  # noqa: BLE001 - reported per document, see the docstring
        # Type and message only, never the repr.
        return _record(document, job, engine="pymupdf", ok=False, pages=document.pages,
                       message=f"{type(exc).__name__}: {exc}")

    return _record(document, job, engine="docling", ok=True, pages=len(pages),
                   version=version, markdown_path=markdown_path)
