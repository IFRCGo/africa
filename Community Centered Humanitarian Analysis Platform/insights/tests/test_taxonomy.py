"""The vocabulary gate: a model may not grow the taxonomy by itself."""
from django.test import SimpleTestCase

from insights.taxonomy import normalise_coding, valid_dimensions


class VocabularyTests(SimpleTestCase):
    def test_a_known_tag_passes_through_untouched(self):
        self.assertEqual(
            normalise_coding("hazard", "flooding"),
            {"dimension": "hazard", "tag": "flooding", "tag_raw": None},
        )

    def test_an_unknown_tag_degrades_and_keeps_what_was_proposed(self):
        self.assertEqual(
            normalise_coding("hazard", "locusts"),
            {"dimension": "hazard", "tag": "other", "tag_raw": "locusts"},
        )

    def test_a_tag_from_the_wrong_dimension_degrades(self):
        """'flooding' is a hazard, not a need. The dimension is kept, the tag is not."""
        self.assertEqual(
            normalise_coding("need", "flooding"),
            {"dimension": "need", "tag": "other", "tag_raw": "flooding"},
        )

    def test_an_unknown_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            normalise_coding("vibes", "flooding")

    def test_the_comment_key_is_not_a_dimension(self):
        self.assertNotIn("_comment", valid_dimensions())

    def test_the_five_real_dimensions_are_present(self):
        self.assertEqual(
            valid_dimensions(),
            {"hazard", "vulnerability", "coping", "need", "movement_pattern"},
        )

    def test_tags_are_matched_case_and_space_insensitively(self):
        self.assertEqual(normalise_coding("need", "Water WASH")["tag"], "water_wash")
