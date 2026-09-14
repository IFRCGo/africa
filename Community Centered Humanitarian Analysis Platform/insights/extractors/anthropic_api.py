"""Anthropic native. Structured outputs, adaptive thinking, streaming, and
server-side fallback.

budget_tokens is REMOVED on claude-opus-5 and returns a 400 - adaptive thinking
replaces it, with output_config.effort controlling depth.

Structured outputs and Citations cannot be combined (the API returns 400), which
is a second reason the verbatim guarantee lives in insights/verify.py: it costs
nothing there and works for every provider, including the local ones this
package also supports.

FALLBACKS (verified against the anthropic==1.5.0 wheel - see
task-13-rulings.md §2): `client.beta.messages.stream` takes `fallbacks` and
`betas` as first-class keywords; the scalar fallbacks="default" routes by
refusal category rather than naming a model that can go stale, and it must be
paired with the "server-side-fallback-2026-07-01" beta header - the older
"-2026-06-01" header is for the array form only and pairing them wrong is a
400. This is why it is client.beta.messages, not client.messages.

REFUSALS are never a silent `continue`. The taxonomy this project extracts
against covers GBV, sexual violence and attacks on civilians - exactly where a
safety classifier may decline - so a refusal is recorded as a problem (see
base.Extractor.problems) and extract_insights writes it to ExtractionJob.log.
"""
from django.conf import settings

from insights.extractors.base import Extractor

SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "quote_language": {"type": "string"},
                    "page": {"type": "integer"},
                    "voice_type": {"type": "string", "enum": ["community", "secondary_analysis"]},
                    "place_name_as_written": {"type": ["string", "null"]},
                    "iso3": {"type": "string"},
                    "codings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "tag": {"type": "string"},
                            },
                            "required": ["dimension", "tag"],
                            "additionalProperties": False,
                        },
                    },
                    "people_affected": {"type": ["integer", "null"]},
                    "severity": {"type": ["integer", "null"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["quote", "page", "voice_type", "iso3", "codings"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}


class AnthropicExtractor(Extractor):
    name = "anthropic"

    def __init__(self):
        super().__init__()
        self.model = settings.LLM_MODEL or "claude-opus-5"

    def _client(self):
        import anthropic

        # An unset key is not the same as no credentials: the SDK also reads
        # ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile. Never log the
        # key - not here, and nowhere it is read from either.
        return anthropic.Anthropic(api_key=settings.LLM_API_KEY or None)

    def extract(self, document, pages):
        client = self._client()
        payload = self.empty_payload(document)
        self.problems = []

        for chunk in self.chunks(pages):
            with client.beta.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=self.system_prompt,
                thinking={"type": "adaptive"},
                output_config={"effort": "high", "format": {"type": "json_schema",
                                                            "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user",
                           "content": self.build_user_message(document, chunk)}],
            ) as stream:
                message = stream.get_final_message()

            # Checked BEFORE .content: a stop_reason of "refusal" means the
            # whole fallback chain declined, and message.content is not the
            # answer in that case. stop_details, and its .category, may both
            # be None - both are valid states, not bugs to work around.
            if message.stop_reason == "refusal":
                category = getattr(message.stop_details, "category", None) \
                    if message.stop_details is not None else None
                detail = f" (category: {category})" if category else ""
                self.problems.append(
                    f"{document.file_name} {self.chunk_label(chunk)}: refused by the "
                    f"model{detail}"
                )
                continue

            text = "".join(b.text for b in message.content if b.type == "text")
            try:
                insights = self.parse_insights(text)
            except ValueError as exc:
                self.problems.append(
                    f"{document.file_name} {self.chunk_label(chunk)}: {exc}"
                )
                continue
            payload["insights"].extend(insights)

        return payload
