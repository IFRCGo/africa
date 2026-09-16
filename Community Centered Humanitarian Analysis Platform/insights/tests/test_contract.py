"""What a payload must contain, and what happens when it does not."""
import json
from pathlib import Path

from django.test import SimpleTestCase

from insights.contract import ContractError, parse

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ParseTests(SimpleTestCase):
    def test_a_good_payload_yields_one_row(self):
        rows = parse(load("payload_ok.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["iso3"], "ETH")
        self.assertEqual(rows[0]["page"], 7)
        self.assertEqual(rows[0]["severity"], 4)
        self.assertIsNone(rows[0]["people_affected"])

    def test_codings_are_normalised_through_the_taxonomy(self):
        # Every coding now carries a role; a payload that states none means
        # 'subject', which is what this fixture does. See RoleTests below.
        codings = parse(load("payload_ok.json"))[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding", "tag_raw": None,
                       "role": "subject"}, codings)
        self.assertIn({"dimension": "need", "tag": "other", "tag_raw": "locusts",
                       "role": "subject"}, codings)

    def test_an_empty_insight_list_is_an_error_not_a_success(self):
        """An MCP or LLM error serialised as [] looks exactly like this."""
        with self.assertRaises(ContractError):
            parse(load("payload_bad.json"))

    def test_a_missing_quote_is_an_error(self):
        payload = load("payload_ok.json")
        del payload["insights"][0]["quote"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_a_blank_quote_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["quote"] = "   "
        with self.assertRaises(ContractError):
            parse(payload)

    def test_a_missing_iso3_is_an_error(self):
        payload = load("payload_ok.json")
        del payload["insights"][0]["iso3"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_an_unknown_voice_type_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["voice_type"] = "hearsay"
        with self.assertRaises(ContractError):
            parse(payload)

    def test_an_unknown_dimension_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"] = [{"dimension": "vibes", "tag": "x"}]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_severity_outside_one_to_five_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["severity"] = 9
        with self.assertRaises(ContractError):
            parse(payload)

    def test_defaults_are_applied_for_optional_fields(self):
        payload = load("payload_ok.json")
        for key in ("quote_language", "people_affected", "severity", "confidence"):
            payload["insights"][0].pop(key, None)
        row = parse(payload)[0]
        self.assertEqual(row["quote_language"], "en")
        self.assertIsNone(row["people_affected"])
        self.assertIsNone(row["severity"])

    def test_severity_true_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["severity"] = True
        with self.assertRaises(ContractError):
            parse(payload)

    def test_severity_false_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["severity"] = False
        with self.assertRaises(ContractError):
            parse(payload)

    def test_people_affected_true_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["people_affected"] = True
        with self.assertRaises(ContractError):
            parse(payload)

    def test_valid_numeric_values_still_work(self):
        """Confirm the fix does not break the valid cases: severity: 4 and people_affected: null."""
        rows = parse(load("payload_ok.json"))
        self.assertEqual(rows[0]["severity"], 4)
        self.assertIsNone(rows[0]["people_affected"])


class RoleTests(SimpleTestCase):
    def test_a_coding_with_no_role_is_a_subject(self):
        """Every payload written before roles existed means 'subject'."""
        codings = parse(load("payload_ok.json"))[0]["codings"]
        self.assertTrue(all(c["role"] == "subject" for c in codings))

    def test_a_stated_role_is_kept(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"][0]["role"] = "driver"
        codings = parse(payload)[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding",
                       "tag_raw": None, "role": "driver"}, codings)

    def test_an_unknown_role_degrades_to_subject(self):
        """A role is an interpretation. A wrong one costs a query, not a fact."""
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"][0]["role"] = "consequence"
        codings = parse(payload)[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding",
                       "tag_raw": None, "role": "subject"}, codings)


class FigureContractTests(SimpleTestCase):
    def test_figures_are_parsed(self):
        row = parse(load("payload_comprehensive.json"))[0]
        self.assertEqual(len(row["figures"]), 2)
        first = row["figures"][0]
        self.assertEqual(first["figure_as_written"], "0.7 million")
        self.assertEqual(first["value"], 700000.0)
        self.assertEqual(first["unit"], "people")

    def test_a_subgroup_is_kept(self):
        figures = parse(load("payload_comprehensive.json"))[0]["figures"]
        self.assertEqual(figures[1]["applies_to"], "Sudanese refugees")

    def test_a_figure_whose_span_is_not_in_the_quote_is_dropped(self):
        """verify.py checks the quote; this is what checks the number."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"][0]["figure_as_written"] = "1.4 million"
        row = parse(payload)[0]
        self.assertEqual(len(row["figures"]), 1)
        self.assertEqual(len(row["drops"]), 1)
        self.assertIn("1.4 million", row["drops"][0])

    def test_an_unknown_unit_drops_the_figure_not_the_payload(self):
        """EVAR states currency amounts too. One EGP must not zero a 43-page run."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"][0]["unit"] = "EGP"
        row = parse(payload)[0]
        self.assertEqual(len(row["figures"]), 1)
        self.assertEqual(len(row["drops"]), 1)
        self.assertTrue(row["quote"].startswith("Since the escalation"))

    def test_a_figure_that_is_not_an_object_is_a_payload_error(self):
        """A broken shape is a broken producer, not a wrong reading."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"] = ["65 percent"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_figures_not_a_list_is_a_payload_error(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"] = {"value": 1}
        with self.assertRaises(ContractError):
            parse(payload)


class MovementContractTests(SimpleTestCase):
    def test_a_corridor_is_parsed_with_both_ends(self):
        movement = parse(load("payload_comprehensive.json"))[0]["movements"][0]
        self.assertEqual(movement["origin_name_as_written"], "Sudan")
        self.assertEqual(movement["origin_iso3"], "SDN")
        self.assertEqual(movement["dest_name_as_written"], "Egypt")
        self.assertEqual(movement["dest_iso3"], "EGY")
        self.assertEqual(movement["flow_type"], "cross_border")
        self.assertEqual(movement["value"], 700000)

    def test_a_corridor_with_one_end_is_allowed(self):
        """'arrivals from Sudan' with no stated destination is a real finding."""
        payload = load("payload_comprehensive.json")
        del payload["insights"][0]["movements"][0]["dest_name_as_written"]
        del payload["insights"][0]["movements"][0]["dest_iso3"]
        row = parse(payload)
        self.assertEqual(len(row[0]["movements"]), 1)
        self.assertIsNone(row[0]["movements"][0]["dest_name_as_written"])
        self.assertEqual(row[0]["drops"], [])

    def test_a_corridor_with_neither_end_is_dropped(self):
        payload = load("payload_comprehensive.json")
        movement = payload["insights"][0]["movements"][0]
        movement.pop("origin_name_as_written")
        movement.pop("dest_name_as_written")
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_an_unknown_flow_type_drops_the_corridor(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["flow_type"] = "circular"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_corridor_may_not_be_measured_as_a_share(self):
        """value is a BigIntegerField. 'percent' has no honest reading in it."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["unit"] = "percent"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_corridor_number_must_also_appear_in_the_quote(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["value_as_written"] = "2.3 million"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_payload_with_no_movements_block_is_fine(self):
        row = parse(load("payload_ok.json"))[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(row["figures"], [])
        self.assertEqual(row["drops"], [])
