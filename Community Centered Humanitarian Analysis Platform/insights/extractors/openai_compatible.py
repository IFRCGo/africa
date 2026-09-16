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
it is for the Anthropic adapter.

That gap is now closed, and closing it does NOT weaken the rule above.
_post_once() makes one request; _post() calls it up to RETRY_ATTEMPTS times
with exponential backoff, and only for the errors that are actually transient:
429, any 5xx, and the socket-level failures (TimeoutError, URLError). A 4xx
that is not 429 - a bad request, a dead key - is returned to the caller on the
first attempt, because the same request will get the same answer and retrying
it only spends tokens and time. When the retries are exhausted the original
exception is re-raised, so the job still fails loudly: an honest failed job a
human re-runs still beats a false "loaded" with zero insights.

This matters because of how a chunked document fails. One 503 on any one chunk
ends the whole document, so a 43-page report is six independent chances to lose
the entire run - and on a free tier, 503s arrive often enough that losing it is
the normal case rather than the unlucky one.

A malformed RESPONSE SHAPE - `answer` missing the "choices"/"message"/
"content" keys a chat-completions response is supposed to have, or JSON that
will not parse - is the opposite case: the request succeeded and what came
back cannot be read. That stays a recorded chunk problem.
"""
import json
import time
import urllib.error
import urllib.request

from django.conf import settings

from insights.extractors.base import Extractor

TIMEOUT_SECONDS = 300

# Total attempts per chunk, not retries after the first - 3 means one request
# and two more if it keeps failing. Sleeps 2s then 4s, so a chunk costs at most
# ~6 extra seconds before the run fails for real.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

# 429 is rate limiting and every 5xx is the server's own problem; both clear on
# their own. Everything else 4xx is about THIS request - a bad body, a dead key,
# a retired model - and will answer identically however many times it is asked.
RETRYABLE_STATUSES = {429}


class OpenAICompatibleExtractor(Extractor):
    name = "openai_compatible"

    def __init__(self):
        super().__init__()
        self.model = settings.LLM_MODEL or "gpt-4o-mini"
        self.base_url = (settings.LLM_BASE_URL or "").rstrip("/")
        if not self.base_url:
            raise ValueError("LLM_BASE_URL must be set for the openai_compatible provider.")

    @staticmethod
    def _is_transient(exc):
        """Is this worth asking again, or will the answer be the same?"""
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in RETRYABLE_STATUSES or 500 <= exc.code < 600
        # A dropped connection or a read timeout never reached a status code at
        # all. URLError covers DNS and refused connections; note HTTPError is a
        # subclass of it, so this check must come second.
        return isinstance(exc, (TimeoutError, urllib.error.URLError))

    def _post(self, body):
        """One chunk's request, retried only while the failure looks transient.

        Re-raises the LAST failure once the attempts are spent, so extract()
        still propagates it and the job still fails loudly.
        """
        # max(1, ...) so this can never fall out of the loop without either
        # returning or raising. A misconfigured RETRY_ATTEMPTS of 0 would
        # otherwise make _post() return None, and the caller would read that as
        # a response - an empty extraction dressed up as a successful one, which
        # is the exact failure this module is written to prevent.
        attempts = max(1, RETRY_ATTEMPTS)
        for attempt in range(1, attempts + 1):
            try:
                return self._post_once(body)
            except Exception as exc:
                if attempt == attempts or not self._is_transient(exc):
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    def _post_once(self, body):
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
