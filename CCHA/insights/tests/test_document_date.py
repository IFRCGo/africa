"""Dating a document from the document, and knowing when not to.

The rule these tests pin comes from real evidence, not taste. Probing the seven
documents already uploaded through the wizard showed:

  - the FILENAME was right on both documents that had a parseable one
    (EVAR_2025_FINAL_March_2026 -> 2026-03-15, ignoring the bare 2025);
  - PDF CREATION METADATA was present on all seven and agreed with the filename
    to within two weeks wherever both fired;
  - the TEXT was wrong on ROSEA_El-Nino_Eastern-Africa_20260813 by seven weeks,
    reading 2026-10-01 out of "October-December" - the El Nino forecast season.

That last one is why text ranks last and why disagreement is not resolved
silently: a humanitarian report is full of forward-looking dates, and a date
read out of its prose can be confidently, invisibly wrong. A wrong report_date
silently mis-places every insight in the document on the dashboard timeline.
"""
import datetime

from django.test import SimpleTestCase

from insights.document_date import AGREEMENT_DAYS, DateGuess, decide


class DecideTests(SimpleTestCase):
    def test_nothing_found_needs_a_person(self):
        guess = decide({})
        self.assertIsNone(guess.date)
        self.assertIsNone(guess.source)
        self.assertTrue(guess.needs_person)

    def test_a_lone_source_is_taken(self):
        """Doc 936 (DFS.pdf): only the PDF metadata fired."""
        guess = decide({"pdf_metadata": datetime.date(2026, 9, 15)})
        self.assertEqual(guess.date, datetime.date(2026, 9, 15))
        self.assertEqual(guess.source, "pdf_metadata")
        self.assertFalse(guess.needs_person)

    def test_the_filename_outranks_the_others_when_they_agree(self):
        """Doc 935 (EVAR): filename 2026-03-15, metadata 2026-03-26. 11 days."""
        guess = decide({
            "filename": datetime.date(2026, 3, 15),
            "pdf_metadata": datetime.date(2026, 3, 26),
        })
        self.assertEqual(guess.date, datetime.date(2026, 3, 15))
        self.assertEqual(guess.source, "filename")
        self.assertFalse(guess.needs_person)

    def test_metadata_outranks_text_when_the_filename_is_silent(self):
        """Doc 934 (DTM): text 2026-08-18, metadata 2026-08-20."""
        guess = decide({
            "text": datetime.date(2026, 8, 18),
            "pdf_metadata": datetime.date(2026, 8, 20),
        })
        self.assertEqual(guess.source, "pdf_metadata")
        self.assertFalse(guess.needs_person)

    def test_a_disagreeing_source_sends_it_to_a_person(self):
        """Doc 939 (ROSEA), the case this whole module exists for.

        The filename and the metadata agree on mid-August. The text says
        1 October, seven weeks out, because it matched the "October-December"
        forecast season. The proposal is still offered, but a person decides.
        """
        guess = decide({
            "filename": datetime.date(2026, 8, 13),
            "pdf_metadata": datetime.date(2026, 8, 20),
            "text": datetime.date(2026, 10, 1),
        })
        self.assertTrue(guess.needs_person)
        # The proposal survives so the wizard can show it rather than a blank.
        self.assertEqual(guess.date, datetime.date(2026, 8, 13))
        self.assertEqual(guess.disagreement, "text")

    def test_agreement_is_inclusive_at_the_boundary(self):
        base = datetime.date(2026, 3, 1)
        guess = decide({
            "filename": base,
            "text": base + datetime.timedelta(days=AGREEMENT_DAYS),
        })
        self.assertFalse(guess.needs_person)

    def test_one_day_past_the_boundary_asks(self):
        base = datetime.date(2026, 3, 1)
        guess = decide({
            "filename": base,
            "text": base + datetime.timedelta(days=AGREEMENT_DAYS + 1),
        })
        self.assertTrue(guess.needs_person)

    def test_a_disagreement_earlier_than_the_winner_also_counts(self):
        """The gap is absolute - a source seven weeks BEFORE is as suspect."""
        guess = decide({
            "filename": datetime.date(2026, 8, 13),
            "text": datetime.date(2026, 5, 1),
        })
        self.assertTrue(guess.needs_person)


class PdfMetadataTests(SimpleTestCase):
    def test_a_pdf_date_string_is_parsed(self):
        from insights.document_date import parse_pdf_date

        self.assertEqual(parse_pdf_date("D:20260326151033+02'00'"),
                         datetime.date(2026, 3, 26))

    def test_a_bare_pdf_date_without_the_prefix_is_parsed(self):
        from insights.document_date import parse_pdf_date

        self.assertEqual(parse_pdf_date("20251128220003"), datetime.date(2025, 11, 28))

    def test_rubbish_is_none_not_an_exception(self):
        from insights.document_date import parse_pdf_date

        for value in ("", None, "not a date", "D:", "D:0000"):
            self.assertIsNone(parse_pdf_date(value))

    def test_an_absurd_year_is_rejected(self):
        """A PDF whose clock was wrong is worse than no metadata at all."""
        from insights.document_date import parse_pdf_date

        self.assertIsNone(parse_pdf_date("D:19700101000000"))


class GuessShapeTests(SimpleTestCase):
    def test_candidates_are_reported_for_the_wizard_to_show(self):
        guess = decide({
            "filename": datetime.date(2026, 8, 13),
            "text": datetime.date(2026, 10, 1),
        })
        self.assertIsInstance(guess, DateGuess)
        self.assertEqual(sorted(guess.candidates), ["filename", "text"])
