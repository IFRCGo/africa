"""One adapter for every server that speaks the OpenAI chat-completions format:
OpenAI, Codex, Ollama, LM Studio, vLLM.

A local model is just LLM_BASE_URL pointing at host.docker.internal. Nothing here
is Anthropic-specific and nothing here should become so - that is the whole point
of having two adapters rather than one.

No refusal handling here - the OpenAI wire format has no stop_reason=="refusal"
equivalent this project can rely on across every server on the list above.
Malformed JSON is still recorded rather than raised (task-13-rulings.md §3),
using the same base.Extractor.parse_insights() the Anthropic adapter uses.

TRANSPORT ERRORS ARE NOT CHUNK PROBLEMS (fix-round, 2026-09-14) - the same
asymmetry as anthropic_api.py, and for the same reason: a dead API key or
an unreachable base_url must fail the job loudly, not end it "loaded" with
zero insights, which looks exactly like a document with nothing to say. So
_post()'s call to urllib.request.urlopen() is left unguarded here too, and
its exception is left to propagate out of extract().

The asymmetry within this asymmetry: unlike the Anthropic SDK, urllib has NO
retry layer of its own, so a transient blip genuinely could be what reaches
_post() and propagates - this is not "already exhausted its retries" the way
it is for the Anthropic adapter. The choice is the same anyway: failing the
job honestly, so a human re-runs it, beats reporting a false "loaded".

A malformed RESPONSE SHAPE - `answer` missing the "choices"/"message"/
"content" keys a chat-completions response is supposed to have, or JSON that
will not parse - is the opposite case: the request succeeded and what came
back cannot be read. That stays a recorded chunk problem.
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
            # The HTTP call itself is unguarded - see the module docstring,
            # its exception is a transport error and must propagate. Reading
            # the response body and parsing it are the "answered but
            # unreadable" class instead, so both live in one guarded region:
            # KeyError/IndexError/TypeError for a response shaped wrong,
            # ValueError (via parse_insights) for JSON that will not parse.
            answer = self._post(body)
            try:
                text = answer["choices"][0]["message"]["content"]
                insights = self.parse_insights(text)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self.problems.append(
                    f"{document.file_name} {self.chunk_label(chunk)}: "
                    f"the model's response could not be read ({exc})"
                )
                continue
            payload["insights"].extend(insights)

        return payload
