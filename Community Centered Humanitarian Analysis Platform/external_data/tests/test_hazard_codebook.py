"""The hazard vocabulary is complete, consistent and keyed on the HIP code.

The test that matters most is test_every_taxonomy_hazard_tag_is_mapped: it fails
the day somebody adds a hazard tag to taxonomy.json and forgets this file, which
would otherwise show up as a tag silently missing from the dashboard dropdown.
"""
import json

from django.conf import settings
from django.test import TestCase

from external_data import hazards


class CodebookShapeTests(TestCase):
    def test_every_category_declares_whether_it_is_the_codebooks(self):
        for cat in hazards.categories():
            self.assertIn("in_codebook", cat, cat["key"])
            self.assertIsInstance(cat["in_codebook"], bool)

    def test_the_seven_codebook_categories_are_present_and_defined(self):
        expected = {"climatological", "biological", "geophysical", "meteorological",
                    "hydrological", "technological", "non_technological"}
        real = {c["key"] for c in hazards.categories() if c["in_codebook"]}
        self.assertEqual(real, expected)
        for cat in hazards.categories():
            if cat["in_codebook"]:
                self.assertTrue(cat["definition"].strip(), cat["key"])

    def test_the_two_project_categories_are_flagged_as_not_the_codebooks(self):
        for key in ("conflict_violence", "food_insecurity"):
            cat = next(c for c in hazards.categories() if c["key"] == key)
            self.assertFalse(cat["in_codebook"])
            self.assertIn("NOT an IFRC codebook category", cat["definition"])


class MappingTests(TestCase):
    def test_every_taxonomy_hazard_tag_is_mapped(self):
        """Add a hazard tag to taxonomy.json and forget this file, and the tag
        vanishes from the dashboard dropdown. This is where you find out."""
        taxonomy = json.loads(
            (settings.BASE_DIR / "data_pipeline" / "taxonomy.json").read_text("utf-8"))
        for tag in taxonomy["hazard"]:
            category, sub = hazards.for_tag(tag)
            self.assertIsNotNone(category, f"{tag} has no codebook category")
            self.assertIsNotNone(sub, f"{tag} has no sub-hazard")

    def test_every_observed_hip_code_is_mapped(self):
        observed = ["EN0205", "MH0600", "MH0103", "MH0301",
                    "MH0501", "MH0401", "GH0300", "GH0101"]
        for code in observed:
            category, sub = hazards.for_hip(code)
            self.assertNotEqual(category, "uncategorised", code)

    def test_wildfire_follows_the_codebook_not_the_undrr_slug(self):
        """nat-cli-wil-wil is climatological to UNDRR. The codebook names
        Wildfires under non-technological and man-made, and it wins."""
        self.assertEqual(hazards.for_hip("EN0205"), ("non_technological", "wildfires"))

    def test_extreme_heat_follows_the_codebook_not_the_undrr_slug(self):
        """nat-met-ext-hea is meteorological to UNDRR; the codebook files heat
        waves as climatological."""
        self.assertEqual(hazards.for_hip("MH0501"), ("climatological", "extreme_heat"))

    def test_the_two_storm_codes_sharing_a_slug_stay_distinct(self):
        """MH0103 and MH0301 both carry nat-met-sto-sto. Keying on the slug
        would merge thunderstorms with windstorms."""
        self.assertEqual(hazards.for_hip("MH0103"), ("meteorological", "thunderstorm"))
        self.assertEqual(hazards.for_hip("MH0301"), ("meteorological", "violent_wind"))

    def test_an_unknown_code_is_uncategorised_never_guessed(self):
        self.assertEqual(hazards.for_hip("ZZ9999"), ("uncategorised", "uncategorised"))

    def test_every_mapping_points_at_a_category_that_exists(self):
        keys = {c["key"] for c in hazards.categories()}
        subs = {s["key"] for c in hazards.categories() for s in c["sub_hazards"]}
        book = hazards.codebook()
        for table in ("hip_codes", "tags"):
            for name, entry in book[table].items():
                self.assertIn(entry["category"], keys, f"{table}/{name}")
                self.assertIn(entry["sub"], subs, f"{table}/{name}")


class HipExtractionTests(TestCase):
    def test_the_hip_code_is_picked_out_of_montandons_mixed_list(self):
        """Montandon sends three flavours in one list: HIP, GLIDE, UNDRR slug."""
        self.assertEqual(
            hazards.hip_from_codes(["EN0205", "WF", "nat-cli-wil-wil"]), "EN0205")
        self.assertEqual(
            hazards.hip_from_codes(["nat-hyd-flo-flo", "FL", "MH0600"]), "MH0600")

    def test_no_hip_code_present_returns_none(self):
        self.assertIsNone(hazards.hip_from_codes(["FL", "nat-hyd-flo-flo"]))
        self.assertIsNone(hazards.hip_from_codes([]))


class DetectionTests(TestCase):
    def test_a_green_gdacs_fire_with_no_impact_is_a_detection(self):
        self.assertTrue(hazards.is_detection("gdacs", "Green", 0))
        self.assertTrue(hazards.is_detection("gdacs", "Green", None))

    def test_a_green_gdacs_fire_that_affected_someone_is_an_event(self):
        self.assertFalse(hazards.is_detection("gdacs", "Green", 4200))

    def test_an_alerting_gdacs_event_is_an_event(self):
        self.assertFalse(hazards.is_detection("gdacs", "Orange", 0))

    def test_sources_with_no_rule_publish_events_only(self):
        """Only GDACS produces the problem, so only GDACS has a rule."""
        self.assertFalse(hazards.is_detection("pdc", "WATCH", 0))
        self.assertFalse(hazards.is_detection("idmc-idu", None, 0))
