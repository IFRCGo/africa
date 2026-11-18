"""Turning a Docling result into numbered pages.

Docling itself is not exercised here - it is slow, it needs weights, and what
can actually go wrong in our code is the page splitting. The converter is
faked; the manual checks at the end of the plan cover the real thing.
"""
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from insights import docling_reader


class FakePage:
    pass


class FakeDocument:
    def __init__(self, pages):
        self.pages = {n: FakePage() for n in range(1, pages + 1)}


class FakeResult:
    def __init__(self, pages):
        self.document = FakeDocument(pages)


class ReadTests(TestCase):
    def test_pages_are_numbered_from_one(self):
        with mock.patch.object(docling_reader, "_convert",
                               return_value=(FakeResult(3), "2.129.0")), \
             mock.patch.object(docling_reader, "_serialise_page",
                               side_effect=lambda doc, n: f"body {n}"):
            pages, version = docling_reader.read(Path("/tmp/r.pdf"))
        self.assertEqual(pages, [(1, "body 1"), (2, "body 2"), (3, "body 3")])
        self.assertEqual(version, "2.129.0")

    def test_a_docx_is_one_page(self):
        # A DOCX has no page provenance, so the whole body is page 1 - the same
        # convention intake._pages_of has always used, for the same reason.
        with mock.patch.object(docling_reader, "_convert",
                               return_value=(FakeResult(0), "2.129.0")), \
             mock.patch.object(docling_reader, "_serialise_whole",
                               return_value="the whole body"):
            pages, _ = docling_reader.read(Path("/tmp/r.docx"))
        self.assertEqual(pages, [(1, "the whole body")])

    @override_settings(DOCLING_ENABLED=False)
    def test_disabled_raises_rather_than_returning_nothing(self):
        # Returning [] would delete every DocumentText row and replace it with
        # nothing. A refusal has to be loud.
        with self.assertRaises(docling_reader.DoclingDisabled):
            docling_reader.read(Path("/tmp/r.pdf"))

    @override_settings(DOCLING_OCR_LANGS=["en", "fr", "ar"])
    def test_an_incompatible_language_set_is_refused_with_a_usable_message(self):
        # EasyOCR raises "Arabic is only compatible with English" from deep
        # inside Reader.__init__, by which point the message names neither the
        # setting that caused it nor the fix. Catch it at the edge instead.
        with self.assertRaises(docling_reader.OcrLanguagesIncompatible) as caught:
            docling_reader.check_languages()
        self.assertIn("DOCLING_OCR_LANGS", str(caught.exception))
