"""The two child tables, and the constraint that had to widen to admit a role."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from insights.models import (
    Insight, InsightCoding, InsightFigure, InsightMovement,
)


def an_insight(**kwargs):
    fields = dict(quote="Nearly 58 percent face moderate to severe food insecurity.",
                  iso3="EGY", stated_on="2026-03-01")
    fields.update(kwargs)
    return Insight.objects.create(**fields)


class CodingRoleTests(TestCase):
    def test_a_coding_defaults_to_subject(self):
        """Every row written before this column existed means 'subject'."""
        coding = InsightCoding.objects.create(
            insight=an_insight(), dimension="hazard", tag="flooding")
        self.assertEqual(coding.role, "subject")

    def test_the_same_tag_may_appear_in_two_roles(self):
        """'return_movement' as the thing happening, and as what drives a need."""
        insight = an_insight()
        InsightCoding.objects.create(
            insight=insight, dimension="movement_pattern", tag="return_movement",
            role="subject")
        InsightCoding.objects.create(
            insight=insight, dimension="movement_pattern", tag="return_movement",
            role="driver")
        self.assertEqual(insight.codings.count(), 2)

    def test_a_true_duplicate_is_still_rejected(self):
        insight = an_insight()
        InsightCoding.objects.create(
            insight=insight, dimension="hazard", tag="flooding", role="driver")
        with self.assertRaises(IntegrityError), transaction.atomic():
            InsightCoding.objects.create(
                insight=insight, dimension="hazard", tag="flooding", role="driver")


class FigureTests(TestCase):
    def test_a_share_is_stored_as_a_share(self):
        """people_affected is a BigIntegerField and cannot hold 58 percent."""
        figure = InsightFigure.objects.create(
            insight=an_insight(),
            figure_as_written="Nearly 58 percent",
            value=58.0,
            unit="percent",
            measures="face moderate to severe food insecurity",
        )
        self.assertEqual(figure.value, 58.0)
        self.assertIsNone(figure.applies_to)

    def test_one_quote_carries_several_figures_with_their_subgroups(self):
        """EVAR p.22 states three in one passage; flattening would keep one."""
        insight = an_insight()
        for written, value, applies_to in (
            ("44 percent", 44.0, None),
            ("36 percent", 36.0, "non-Arabic speaking households"),
            ("26 percent", 26.0, "other regions"),
        ):
            InsightFigure.objects.create(
                insight=insight, figure_as_written=written, value=value,
                unit="percent", measures="report having access to informal credit",
                applies_to=applies_to)
        self.assertEqual(insight.figures.count(), 3)


class MovementTests(TestCase):
    def test_a_corridor_holds_two_independently_resolved_ends(self):
        movement = InsightMovement.objects.create(
            insight=an_insight(),
            origin_name_as_written="Sudan", origin_iso3="SDN",
            dest_name_as_written="Egypt", dest_iso3="EGY",
            flow_type="cross_border",
            value_as_written="0.7 million", value=700000, unit="people",
        )
        self.assertEqual(movement.origin_iso3, "SDN")
        self.assertEqual(movement.dest_iso3, "EGY")
        self.assertEqual(movement.origin_match_method, "unmatched")
        self.assertEqual(movement.dest_match_method, "unmatched")

    def test_a_corridor_with_no_number_is_still_a_corridor(self):
        movement = InsightMovement.objects.create(
            insight=an_insight(),
            origin_name_as_written="Sudan", origin_iso3="SDN",
            flow_type="cross_border")
        self.assertIsNone(movement.value)
        self.assertIsNone(movement.value_as_written)
        self.assertIsNone(movement.unit)
