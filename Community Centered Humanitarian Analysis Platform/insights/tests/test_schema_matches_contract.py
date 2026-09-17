"""The JSON schema is the third half of the contract, and it is load-bearing.

anthropic_api.SCHEMA is passed as the request's json_schema output format with
"additionalProperties": False on both the insight object and the coding object.
A field the contract accepts but the schema omits is not ignored - it is
FORBIDDEN, and the adapter simply never emits it. The failure is silent: the run
looks healthy and returns nothing new.

So the schema is checked against the vocabularies rather than trusted to be kept
in step by hand.
"""
from django.test import SimpleTestCase

from insights.extractors.anthropic_api import SCHEMA
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES, ROLE_VALUES,
)

INSIGHT = SCHEMA["properties"]["insights"]["items"]["properties"]


class SchemaTests(SimpleTestCase):
    def test_the_insight_object_admits_figures_and_movements(self):
        self.assertIn("figures", INSIGHT)
        self.assertIn("movements", INSIGHT)

    def test_a_coding_admits_a_role_and_its_enum_matches_the_model(self):
        coding = INSIGHT["codings"]["items"]["properties"]
        self.assertIn("role", coding)
        self.assertEqual(set(coding["role"]["enum"]), ROLE_VALUES)

    def test_the_figure_unit_enum_matches_the_model(self):
        figure = INSIGHT["figures"]["items"]["properties"]
        self.assertEqual(set(figure["unit"]["enum"]), FIGURE_UNIT_VALUES)

    def test_a_figure_must_carry_its_span(self):
        """figure_as_written is what makes the number checkable. Not optional."""
        figure = INSIGHT["figures"]["items"]
        self.assertIn("figure_as_written", figure["required"])

    def test_the_movement_enums_match_the_model(self):
        movement = INSIGHT["movements"]["items"]["properties"]
        self.assertEqual(set(movement["flow_type"]["enum"]), FLOW_TYPE_VALUES)
        self.assertEqual(
            {value for value in movement["unit"]["enum"] if value is not None},
            MOVEMENT_UNIT_VALUES)

    def test_a_corridor_is_never_measured_as_a_share(self):
        movement = INSIGHT["movements"]["items"]["properties"]
        self.assertNotIn("percent", movement["unit"]["enum"])

    def test_figures_and_movements_stay_optional(self):
        """Task 1's tripwire in schema form: a payload may omit them entirely."""
        required = SCHEMA["properties"]["insights"]["items"]["required"]
        self.assertNotIn("figures", required)
        self.assertNotIn("movements", required)
