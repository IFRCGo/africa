"""The one place that knows what Docling looks like.

Everything else in the insights app asks for [(page_number, markdown)] and a
version string. That boundary is what lets convert.py be tested without model
weights, and what makes a Docling upgrade one file's problem.

WHY THE OCR ENGINE IS NAMED EXPLICITLY. Docling's default is OcrAutoOptions,
which probes the machine and picks an engine at pipeline init - and its own
documentation says language settings then fall back to that engine's internal
defaults, so DOCLING_OCR_LANGS would be silently ignored. On a CPU-only
container the probe lands on RapidOCR, whose supported-language list has no
Arabic at all. For an archive of Sudan and Chad reports that is
disqualifying. EasyOcrOptions takes ISO 639-1 codes, including 'ar' and 'fr'.

WHY ARABIC AND FRENCH CANNOT BOTH BE ON. EasyOCR refuses to load Arabic beside
any other non-English language - Reader.__init__ raises "Arabic is only
compatible with English" - and Docling takes exactly one ocr_options, so one
pass cannot cover both scripts. settings.DOCLING_OCR_LANGS defaults to en,ar
because the loss is asymmetric: French is Latin script, so an English model
still reads it and only mangles the accents, while Arabic under a Latin model
reads as nothing. check_languages() below turns that library error into one
that names the setting and the fix.
"""
from pathlib import Path

from django.conf import settings


class DoclingDisabled(RuntimeError):
    """DOCLING_ENABLED is off. Raised, never returned as an empty result."""


class OcrLanguagesIncompatible(ValueError):
    """DOCLING_OCR_LANGS asks for a combination EasyOCR will not load."""


# EasyOCR's own compatibility groups, and the only ones this project needs to
# know about. English is compatible with everything; Arabic is compatible with
# nothing else except these.
_ARABIC_SCRIPT = {"ar", "fa", "ug", "ur"}


def check_languages(langs=None):
    """Raise before a Reader is built, with a message naming the setting.

    EasyOCR's own error arrives from deep inside Reader.__init__ during a
    detached conversion run, where it reaches a person as one line in a job
    log naming neither DOCLING_OCR_LANGS nor what to set it to.
    """
    langs = list(settings.DOCLING_OCR_LANGS if langs is None else langs)
    arabic = _ARABIC_SCRIPT & set(langs)
    others = set(langs) - _ARABIC_SCRIPT - {"en"}
    if arabic and others:
        raise OcrLanguagesIncompatible(
            f"DOCLING_OCR_LANGS={','.join(langs)} cannot be loaded: EasyOCR reads "
            f"Arabic only alongside English, so {sorted(arabic)} and {sorted(others)} "
            f"cannot share one pass. Set DOCLING_OCR_LANGS=en,ar for Arabic reports "
            f"or DOCLING_OCR_LANGS=en,fr for French ones; the weights for both are "
            f"in the image, so this is a .env change and a restart, not a rebuild."
        )
    return langs


def _build_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    artifacts = str(settings.DOCLING_ARTIFACTS_PATH)
    options = PdfPipelineOptions(artifacts_path=artifacts)
    options.do_ocr = True
    options.do_table_structure = True
    # download_enabled=False so a missing weight fails here, loudly, instead of
    # quietly reaching for the internet inside a detached subprocess nobody is
    # watching.
    options.ocr_options = EasyOcrOptions(
        lang=check_languages(),
        download_enabled=False,
        model_storage_directory=artifacts,
    )
    options.document_timeout = settings.DOCLING_TIMEOUT_SECONDS
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _convert(path):
    """(result, version). Split out so the tests can stand in for it."""
    import docling

    converter = _build_converter()
    result = converter.convert(str(path), page_range=(1, settings.DOCLING_MAX_PAGES))
    return result, getattr(docling, "__version__", "unknown")


def _serialise_page(document, page_number):
    """That page's items, in reading order, as markdown.

    An item spanning a page break is serialised into BOTH pages: docling-core's
    page filter yields an item when any of its provenances matches. That is
    harmless and mildly useful - a quote from a table running across pages 3
    and 4 verifies against whichever page the model cites.
    """
    from docling_core.transforms.serializer.markdown import (
        MarkdownDocSerializer, MarkdownParams)

    return MarkdownDocSerializer(
        doc=document, params=MarkdownParams(pages={page_number})).serialize().text


def _serialise_whole(document):
    return document.export_to_markdown()


def read(path):
    """([(page_number, markdown)], docling_version). Raises on any failure."""
    if not settings.DOCLING_ENABLED:
        raise DoclingDisabled("DOCLING_ENABLED is off")

    result, version = _convert(Path(path))
    document = result.document

    page_numbers = sorted(getattr(document, "pages", {}) or {})
    if not page_numbers:
        # A DOCX, or anything else with no page provenance. Same convention as
        # intake._pages_of: the whole body is page 1, because a DOCX has no
        # pages until it is rendered.
        return [(1, _serialise_whole(document))], version

    return [(number, _serialise_page(document, number)) for number in page_numbers], version
