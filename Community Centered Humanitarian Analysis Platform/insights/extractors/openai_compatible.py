"""One adapter for every server that speaks the OpenAI chat-completions format:
OpenAI, Codex, Ollama, LM Studio, vLLM.

A local model is just LLM_BASE_URL pointing at host.docker.internal. Nothing here
is Anthropic-specific and nothing here should become so - that is the whole point
of having two adapters rather than one.

No refusal handling here - the OpenAI wire format has no stop_reason=="refusal"
equivalent this project can rely on across every server on the list above.
Malformed JSON is still recorded rather than raised (task-13-rulings.md §3),
using the same base.Extractor.parse_insights() the Anthropic adapter uses.
"""
import json
import urllib.request

from django.conf import settings

from insights.extractors.base import Extractor

TIMEOUT_SECONDS = 300


class OpenAICompatibleExtractor(Extractor):
    name = "openai_compatible"

    def __init__(self):
        super().__init__()
        self.model = settings.LLM_MODEL or "gpt-4o-mini"
        self.base_url = (settings.LLM_BASE_URL or "").rstrip("/")
        if not self.base_url:
            raise ValueError("LLM_BASE_URL must be set for the openai_compatible provider.")

    def _post(self, body):
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Local servers accept and ignore an empty bearer token. Never
                # log this header - LLM_API_KEY must not reach a log line.
                "Authorization": f"Bearer {settings.LLM_API_KEY or 'not-needed'}",
            },
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    def extract(self, document, pages):
        payload = self.empty_payload(document)
        self.problems = []

        for chunk in self.chunks(pages):
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": self.build_user_message(document, chunk)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            }
            answer = self._post(body)
            text = answer["choices"][0]["message"]["content"]
            try:
                insights = self.parse_insights(text)
            except ValueError as exc:
                self.problems.append(
                    f"{document.file_name} {self.chunk_label(chunk)}: {exc}"
                )
                continue
            payload["insights"].extend(insights)

        return payload
