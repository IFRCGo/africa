"""The gate that makes an unknown model safe to use.

This is the only guard in the design that does not depend on which provider
produced the payload, which is exactly why it is the one that matters. A model
that invents produces FEWER insights, not wrong ones.
"""
from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.verify import normalise, quote_is_verbatim, quote_sha1

PAGE_TEXT = (
    "Participants explained:  “When it rains we get flash floods,\n"
    "and with the fighting around us the hospitals are gone — we have\n"
    "cholera now and nowhere to take the sick.”\n"
)


class NormaliseTests(TestCase):
    def test_runs_of_whitespace_collapse(self):
        self.assertEqual(normalise("a   b\n\nc"), "a b c")

    def test_unicode_dashes_fold_to_hyphen(self):
        self.assertEqual(normalise("a — b"), normalise("a - b"))

    def test_curly_quotes_fold_to_straight(self):
        self.assertEqual(normalise("“hi”"), normalise('"hi"'))

    def test_case_is_ignored(self):
        self.assertEqual(normalise("Flood"), normalise("flood"))


class Sha1Tests(TestCase):
    def test_the_same_quote_formatted_differently_hashes_the_same(self):
        self.assertEqual(quote_sha1("a  b"), quote_sha1("a b"))

    def test_a_different_quote_hashes_differently(self):
        self.assertNotEqual(quote_sha1("a b"), quote_sha1("a c"))


class VerbatimTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(file_name="x.pdf", rel_path="insights/x.pdf")
        DocumentText.objects.create(document=self.doc, page=7, text=PAGE_TEXT)

    def test_a_real_quote_is_found_across_line_breaks(self):
        quote = ("When it rains we get flash floods, and with the fighting around us "
                 "the hospitals are gone — we have cholera now and nowhere to take the sick.")
        self.assertTrue(quote_is_verbatim(self.doc.id, 7, quote))

    def test_an_invented_quote_is_not_found(self):
        self.assertFalse(quote_is_verbatim(
            self.doc.id, 7, "We were promised boreholes and nothing came."))

    def test_a_real_quote_on_the_wrong_page_is_not_found(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 3, "we have cholera now"))

    def test_a_missing_page_is_not_found_rather_than_an_error(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 99, "anything"))

    def test_an_empty_quote_is_never_verbatim(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 7, "   "))
