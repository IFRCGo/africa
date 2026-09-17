"""The codebook reaches the tag rows, and then the dashboard files."""
from datetime import date

from django.test import TestCase

from data_track.models import NarrativeTag


class TagStampingTests(TestCase):
    """Every hazard tag carries its codebook category, stamped at parse time.

    Derived rather than curated: s03_parse deletes and rebuilds narrative_tags
    on every run, so a category written into the table by hand would not
    survive the next pass. The codebook file is the place to change one.
    """

    def test_a_hazard_tag_carries_its_codebook_category(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "flooding"),
                         {"hazard_category": "hydrological", "hazard_sub": "flooding"})

    def test_a_conflict_tag_lands_in_the_project_category(self):
        """The codebook excludes armed conflict from man-made hazards, but six
        of the ten tags are conflict tags and they are most of the reporting."""
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "armed_conflict"),
                         {"hazard_category": "conflict_violence",
                          "hazard_sub": "armed_conflict"})

    def test_a_need_has_no_hazard_category(self):
        """Null, not empty string - an empty string reads as a blank category."""
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("need", "water_wash"),
                         {"hazard_category": None, "hazard_sub": None})

    def test_the_columns_survive_a_round_trip_through_the_table(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        NarrativeTag.objects.create(
            dimension="hazard", tag="flooding", country="Sudan",
            report_date=date(2026, 8, 1), **hazard_columns("hazard", "flooding"))
        row = NarrativeTag.objects.get(tag="flooding")
        self.assertEqual(row.hazard_category, "hydrological")
        self.assertEqual(row.hazard_sub, "flooding")
