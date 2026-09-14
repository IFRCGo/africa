"""Selecting an adapter, building the prompt, and what each adapter does with
a chunk that came back wrong. No network calls anywhere in this file: the
Anthropic client and the OpenAI-compatible _post() are both mocked.

The adapters themselves are thin - one HTTP round trip each - so what is worth
testing is the selection, the configuration falling back correctly on an empty
env var, that the prompt file is actually read rather than inlined, that the
Anthropic call shape is exactly what task-13-rulings.md §2 specifies (the
fallback beta plus the scalar "default"), and that a refusal or a malformed
chunk is recorded rather than either dropped silently or left to raise and
kill the whole document (§3).
"""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from data_track.models import Document
from insights.extractors import get_extractor, prompt_text
from insights.extractors.anthropic_api import AnthropicExtractor
from insights.extractors.openai_compatible import OpenAICompatibleExtractor


class SelectionTests(SimpleTestCase):
    @override_settings(LLM_PROVIDER="anthropic", LLM_MODEL="claude-opus-5")
    def test_anthropic_is_selected(self):
        self.assertIsInstance(get_extractor(), AnthropicExtractor)

    @override_settings(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://x/v1")
    def test_openai_compatible_is_selected(self):
        self.assertIsInstance(get_extractor(), OpenAICompatibleExtractor)

    @override_settings(LLM_PROVIDER="nonesuch")
    def test_an_unknown_provider_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            get_extractor()


class PromptTests(SimpleTestCase):
    def test_the_prompt_is_read_from_the_file(self):
        text = prompt_text()
        self.assertIn("community insight", text.lower())
        self.assertIn("verbatim", text.lower())
        self.assertIn("mcp_cache/insights", text)


def _document():
    # Unsaved on purpose - extract() never touches the database, only the
    # attributes build_user_message() and empty_payload() read off it.
    return Document(
        file_name="report.pdf", rel_path="insights/report.pdf",
        sha1="a" * 40, report_date=date(2026, 3, 14),
    )


def _stream_context(message):
    """A `with client.beta.messages.stream(...) as stream:` block whose
    stream.get_final_message() returns `message`."""
    stream = MagicMock()
    stream.get_final_message.return_value = message
    context = MagicMock()
    context.__enter__.return_value = stream
    context.__exit__.return_value = False
    return context


@override_settings(LLM_PROVIDER="anthropic", LLM_MODEL="claude-opus-5", LLM_API_KEY="")
class AnthropicAdapterTests(SimpleTestCase):
    def _extract_with(self, message):
        extractor = AnthropicExtractor()
        client = MagicMock()
        client.beta.messages.stream.return_value = _stream_context(message)
        with patch.object(AnthropicExtractor, "_client", return_value=client):
            payload = extractor.extract(_document(), [(1, "Some page text.")])
        return extractor, payload, client

    def test_the_call_carries_the_fallback_beta_and_the_scalar_default(self):
        # task-13-rulings.md §2: fallbacks="default" (the scalar form) is
        # only valid paired with this exact beta header - the array form's
        # header is a different date and a 400 if the two are swapped.
        message = SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            content=[SimpleNamespace(type="text", text=json.dumps({"insights": []}))],
        )
        extractor, _, client = self._extract_with(message)
        _, kwargs = client.beta.messages.stream.call_args
        self.assertEqual(kwargs["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kwargs["fallbacks"], "default")
        # And it must be the beta namespace, not client.messages.
        client.messages.stream.assert_not_called()
        self.assertEqual(extractor.problems, [])

    def test_a_final_refusal_is_recorded_with_its_category_not_dropped(self):
        message = SimpleNamespace(
            stop_reason="refusal",
            stop_details=SimpleNamespace(category="sexual_content"),
            content=[],
        )
        extractor, payload, _ = self._extract_with(message)
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)
        self.assertIn("refused", extractor.problems[0])
        self.assertIn("sexual_content", extractor.problems[0])

    def test_a_refusal_with_no_stop_details_is_still_recorded(self):
        """stop_details, and its .category, may both be None - both are valid
        states (task-13-rulings.md §2), not something to crash on."""
        message = SimpleNamespace(stop_reason="refusal", stop_details=None, content=[])
        extractor, payload, _ = self._extract_with(message)
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)
        self.assertIn("refused", extractor.problems[0])

    def test_malformed_json_is_recorded_not_raised(self):
        message = SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            content=[SimpleNamespace(type="text", text="not json at all")],
        )
        extractor, payload, _ = self._extract_with(message)
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)

    def test_a_well_formed_chunk_is_parsed_into_the_payload(self):
        message = SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            content=[SimpleNamespace(
                type="text",
                text=json.dumps({"insights": [{"quote": "They said the water is gone."}]}),
            )],
        )
        extractor, payload, _ = self._extract_with(message)
        self.assertEqual(len(payload["insights"]), 1)
        self.assertEqual(extractor.problems, [])


@override_settings(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://x/v1", LLM_API_KEY="")
class OpenAICompatibleAdapterTests(SimpleTestCase):
    def _extract_with(self, content):
        extractor = OpenAICompatibleExtractor()
        answer = {"choices": [{"message": {"content": content}}]}
        with patch.object(OpenAICompatibleExtractor, "_post", return_value=answer):
            payload = extractor.extract(_document(), [(1, "Some page text.")])
        return extractor, payload

    def test_malformed_json_is_recorded_not_raised(self):
        extractor, payload = self._extract_with("not json")
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)

    def test_a_fence_with_nothing_after_its_opening_line_is_recorded_not_raised(self):
        """A bare "```" or "```json" with no newline after it would otherwise
        hit text.split("\\n", 1)[1] with only one element - an IndexError,
        not the JSONDecodeError parse_insights() catches. This is exactly the
        shape a mid-stream fallback handoff (rulings §3) can leave behind."""
        extractor, payload = self._extract_with("```json")
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)

    def test_json_without_an_insights_list_is_recorded_not_raised(self):
        """An LLM error serialised as a bare object with no "insights" key is
        exactly as much a problem as text that fails to parse at all."""
        extractor, payload = self._extract_with(json.dumps({"not_insights": []}))
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)

    def test_a_well_formed_chunk_is_parsed_into_the_payload(self):
        content = json.dumps({"insights": [{"quote": "They said the water is gone."}]})
        extractor, payload = self._extract_with(content)
        self.assertEqual(len(payload["insights"]), 1)
        self.assertEqual(extractor.problems, [])

    def test_a_missing_base_url_is_a_clear_error(self):
        with override_settings(LLM_BASE_URL=""):
            with self.assertRaises(ValueError):
                OpenAICompatibleExtractor()
