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
        # Add a second page with a short statement for testing the word-count floor.
        DocumentText.objects.create(document=self.doc, page=8, text="We have no water.")

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

    def test_a_two_word_fragment_is_rejected_even_if_it_appears(self):
        # "flash floods" genuinely appears on page 7, but has only 2 words.
        self.assertFalse(quote_is_verbatim(self.doc.id, 7, "flash floods"))

    def test_a_single_word_is_rejected_even_if_it_appears(self):
        # "hospitals" genuinely appears on page 7, but is a single word.
        self.assertFalse(quote_is_verbatim(self.doc.id, 7, "hospitals"))

    def test_a_short_four_word_statement_passes_the_minimum(self):
        # "We have no water." has 4 words and 17 characters (after normalisation),
        # so it passes both thresholds.
        self.assertTrue(quote_is_verbatim(self.doc.id, 8, "We have no water."))


class MarkdownFoldingTests(TestCase):
    """A quote of the words matches a stored line that carries the markup.

    Docling's text is markdown. The model is asked for a verbatim quote and
    returns the sentence, not the asterisks around part of it - so the fold
    has to happen on both the needle and the haystack.
    """

    def setUp(self):
        self.document = Document.objects.create(
            file_name="r.pdf", rel_path="media/abc-r.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40)

    def page(self, text, page=1):
        DocumentText.objects.create(document=self.document, page=page, text=text)

    def test_quote_without_emphasis_matches_a_bolded_line(self):
        self.page("Families reported that **water points** were destroyed.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Families reported that water points were destroyed."))

    def test_quote_matches_across_a_table_pipe(self):
        self.page("| Kulbus | 12,400 displaced since June |")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Kulbus 12,400 displaced since June"))

    def test_quote_matches_a_heading(self):
        self.page("## Protection concerns in Zalingei\n\nThe clinic closed.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Protection concerns in Zalingei"))

    def test_quote_matches_a_list_item(self):
        self.page("- No water has reached the site since March.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "No water has reached the site since March."))

    def test_a_changed_word_still_fails(self):
        # The whole reason this gate exists. Folding markup must not fold meaning.
        self.page("Families reported that **water points** were destroyed.")
        self.assertFalse(quote_is_verbatim(
            self.document.id, 1, "Families reported that water points were rebuilt."))

    def test_hyphenated_place_names_survive_the_fold(self):
        # The trap: a position-independent "-" strip would eat this, and
        # normalise() has already folded en-dashes to the same character.
        self.page("Displacement from **Al-Fasher** rose between 12-14 June.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Displacement from Al-Fasher rose between 12-14 June."))

    def test_markup_alone_cannot_pass_the_length_guard(self):
        # The 3-word/12-character floor must measure the FOLDED needle, or
        # "** ** **" buys its way past a check meant to stop trivial matches.
        self.page("| ** | ** | ** | text here to match against |")
        self.assertFalse(quote_is_verbatim(self.document.id, 1, "** ** ** **"))


class NaturalKeyStabilityTests(TestCase):
    """quote_sha1 must be byte-identical to what it was before the fold existed.

    It is half of the (document, page, quote_sha1) unique constraint. If it
    moves, a re-extraction inserts duplicates beside published rows instead of
    matching them, and no error is raised anywhere. These values were captured
    from the running container before verify.py was touched.
    """

    FIXED = {
        "Families reported that water points were destroyed.":
            "1f122c94fe9b69d4c8f1ab319eb63ff06a1bf596",
        "**bold** text": "d944e44f723e17b01e6d2dfd7ae99da8d947e7dc",
        "Al-Fasher, 12-14 June 2026": "de6ca970cc3803669ed69c4d0cbbd45a5b0079df",
        "the clinic closed in March": "1ffc27beb6e0c2c4d802c3d586bbbd5a9e2fe4e6",
    }

    def test_hashes_are_unchanged(self):
        for text, expected in self.FIXED.items():
            self.assertEqual(quote_sha1(text), expected, f"quote_sha1 moved for {text!r}")
