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
        codings = parse(load("payload_ok.json"))[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding", "tag_raw": None}, codings)
        self.assertIn({"dimension": "need", "tag": "other", "tag_raw": "locusts"}, codings)

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
