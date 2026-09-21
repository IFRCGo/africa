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
import urllib.error
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from data_track.models import Document
from insights.extractors import get_extractor, prompt_text
from insights.extractors.base import Extractor
from insights.extractors.anthropic_api import AnthropicExtractor
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES,
)
from insights.taxonomy import valid_dimensions
from insights.extractors.openai_compatible import (
    RETRY_ATTEMPTS, OpenAICompatibleExtractor,
)


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

    def test_a_transport_failure_propagates_it_is_not_a_chunk_problem(self):
        """fix-round, task-13-rulings.md-adjacent: a connection failure, rate
        limit, auth failure or 5xx has already exhausted the SDK's own
        retries by the time it reaches here (anthropic 1.5.0's
        DEFAULT_MAX_RETRIES=2) and must propagate rather than be recorded as
        an ordinary chunk problem - swallowing it would let a dead API key
        end a job "loaded" with zero insights, a silent success."""
        extractor = AnthropicExtractor()
        client = MagicMock()
        client.beta.messages.stream.side_effect = ConnectionError("connection reset")
        with patch.object(AnthropicExtractor, "_client", return_value=client):
            with self.assertRaises(ConnectionError):
                extractor.extract(_document(), [(1, "Some page text.")])
        # Not recorded as a chunk problem - it never reached that code path.
        self.assertEqual(extractor.problems, [])

    def test_a_response_with_no_readable_text_is_recorded_not_raised(self):
        """A malformed RESPONSE SHAPE (here: a content block with no .text)
        is the opposite class from a transport failure - the request
        succeeded, so this is recorded like malformed JSON, not raised."""
        message = SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            # No .text attribute at all - not even an empty string.
            content=[SimpleNamespace(type="text")],
        )
        extractor, payload, _ = self._extract_with(message)
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)
        self.assertIn("could not be read", extractor.problems[0])


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

    def test_a_transport_failure_propagates_it_is_not_a_chunk_problem(self):
        """Unlike the Anthropic SDK, urllib has no retry layer of its own -
        so a blip here genuinely could be transient. The choice is still to
        let it propagate: an honest failed job a human re-runs beats a false
        "loaded" with zero insights."""
        extractor = OpenAICompatibleExtractor()
        with patch.object(OpenAICompatibleExtractor, "_post",
                           side_effect=TimeoutError("timed out")):
            with self.assertRaises(TimeoutError):
                extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(extractor.problems, [])

    def test_a_response_missing_the_expected_keys_is_recorded_not_raised(self):
        """A malformed RESPONSE SHAPE - here, a server that does not answer
        in the chat-completions shape at all - is the opposite class from a
        transport failure: the HTTP call succeeded, so this is recorded like
        malformed JSON, not raised."""
        extractor = OpenAICompatibleExtractor()
        with patch.object(OpenAICompatibleExtractor, "_post",
                           return_value={"error": "no choices here"}):
            payload = extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(payload["insights"], [])
        self.assertEqual(len(extractor.problems), 1)
        self.assertIn("could not be read", extractor.problems[0])


@override_settings(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://x/v1", LLM_API_KEY="")
class OpenAICompatibleRetryTests(SimpleTestCase):
    """A transient 503 must not cost a whole document.

    The module docstring already names this gap: urllib has no retry layer of
    its own, so "a transient blip genuinely could be what reaches _post() and
    propagates". Gemini's free tier returns 503 often enough that on a 43-page
    document - six chunks, six chances - losing the run to one blip is the
    normal case rather than the unlucky one.

    What must NOT change: a failure that survives the retries still propagates
    and still fails the job loudly. A job that ends "loaded" with zero insights
    looks exactly like a document with nothing to say, and that is the confusion
    the unguarded call exists to prevent.
    """

    def _http_error(self, code):
        return urllib.error.HTTPError(
            url="http://x/v1/chat/completions", code=code, msg="Service Unavailable",
            hdrs=None, fp=None)

    def _answer(self):
        content = json.dumps({"insights": [{"quote": "They said the water is gone."}]})
        return {"choices": [{"message": {"content": content}}]}

    def test_a_transient_503_is_retried_and_the_chunk_survives(self):
        extractor = OpenAICompatibleExtractor()
        attempts = [self._http_error(503), self._http_error(503), self._answer()]

        def flaky(body):
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once", side_effect=flaky):
                payload = extractor.extract(_document(), [(1, "Some page text.")])

        self.assertEqual(len(payload["insights"]), 1)
        self.assertEqual(extractor.problems, [])
        self.assertEqual(attempts, [])

    def test_a_503_that_never_clears_still_propagates(self):
        """The design rule survives: an honest failed job beats a false 'loaded'."""
        extractor = OpenAICompatibleExtractor()
        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once",
                              side_effect=self._http_error(503)) as posted:
                with self.assertRaises(urllib.error.HTTPError):
                    extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(extractor.problems, [])
        self.assertEqual(posted.call_count, RETRY_ATTEMPTS)

    def test_a_429_is_retried_too(self):
        extractor = OpenAICompatibleExtractor()
        attempts = [self._http_error(429), self._answer()]

        def flaky(body):
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once", side_effect=flaky):
                payload = extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(len(payload["insights"]), 1)

    def test_a_400_is_not_retried(self):
        """A bad request is not transient. Retrying it wastes tokens and time
        and buys nothing - the same request gets the same answer."""
        extractor = OpenAICompatibleExtractor()
        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once",
                              side_effect=self._http_error(400)) as posted:
                with self.assertRaises(urllib.error.HTTPError):
                    extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(posted.call_count, 1)

    def test_a_dead_key_401_is_not_retried(self):
        extractor = OpenAICompatibleExtractor()
        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once",
                              side_effect=self._http_error(401)) as posted:
                with self.assertRaises(urllib.error.HTTPError):
                    extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(posted.call_count, 1)

    def test_a_timeout_is_retried_then_propagates(self):
        """A dropped connection is the same class of transient as a 503."""
        extractor = OpenAICompatibleExtractor()
        with patch("insights.extractors.openai_compatible.time.sleep"):
            with patch.object(OpenAICompatibleExtractor, "_post_once",
                              side_effect=TimeoutError("timed out")) as posted:
                with self.assertRaises(TimeoutError):
                    extractor.extract(_document(), [(1, "Some page text.")])
        self.assertEqual(posted.call_count, RETRY_ATTEMPTS)
        self.assertEqual(extractor.problems, [])


class PromptMentionsMarkdownTests(SimpleTestCase):
    """The model is now reading markdown, and its quotes are matched against it.

    verify._fold_markup absorbs the markers on both sides, so a quote carrying
    them still matches - but a model told nothing may quote a whole table row
    with its pipes, and the fold cannot rescue a quote that spans a row break.
    """

    def test_the_prompt_says_the_text_is_markdown(self):
        body = prompt_text().lower()
        self.assertIn("markdown", body)


class VocabularyIsSentWithTheDocumentTests(SimpleTestCase):
    """The taxonomy travels in the request, because the model cannot read it.

    extract_insights.md says "read data_pipeline/taxonomy.json", which a host
    agent with file access can do and an API model cannot. Left unsent, an
    in-container model guesses from memory: on MSF's "Voices from South
    Darfur" it proposed `financial_barriers` for what the vocabulary calls
    `cash`, and - worse - put the ROLE name `barrier` in the dimension slot,
    which discarded all 30 insights in that payload.

    Sent per REQUEST rather than appended to the prompt file because the
    vocabulary is a JSON file that changes without a migration; reading it at
    request time is what keeps the two from drifting apart.
    """

    def _message(self):
        return Extractor().build_user_message(_document(), [(1, "some page text")])

    def test_every_dimension_is_named(self):
        message = self._message()
        for dimension in valid_dimensions():
            self.assertIn(dimension, message)

    def test_the_tags_of_a_dimension_are_listed(self):
        """'cash' is the tag the South Darfur testimony needed and missed."""
        message = self._message()
        self.assertIn("cash", message)
        self.assertIn("water_wash", message)

    def test_the_three_roles_are_named(self):
        message = self._message()
        for role in ("subject", "driver", "barrier"):
            self.assertIn(role, message)

    def test_the_corridor_and_figure_vocabularies_are_named_too(self):
        """Same near-miss, same cost, one level down.

        The South Darfur run proposed flow_type 'internal_displacement' for
        what this project calls 'internal', and both corridors on that quote
        were dropped for it (contract._movements). A model told the four flow
        types and the two unit lists cannot miss by a synonym.
        """
        # Whole lists, not one value at a time: every flow type is also a
        # substring of some movement_pattern tag ('internal' of
        # 'internal_displacement'), so a per-value assertion would pass on the
        # tag list alone and prove nothing.
        message = self._message()
        self.assertIn("flow_type", message)
        self.assertIn(", ".join(sorted(FLOW_TYPE_VALUES)), message)
        self.assertIn(", ".join(sorted(FIGURE_UNIT_VALUES)), message)
        self.assertIn(", ".join(sorted(MOVEMENT_UNIT_VALUES)), message)

    def test_the_page_text_is_still_there(self):
        message = self._message()
        self.assertIn("--- page 1 ---", message)
        self.assertIn("some page text", message)
        self.assertIn("insights/report.pdf", message)
