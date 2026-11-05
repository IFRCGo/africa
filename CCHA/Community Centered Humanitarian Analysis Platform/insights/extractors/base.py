"""What both adapters share: how a document is turned into a request, and how
a chunk whose RESPONSE went wrong - JSON that will not parse, or parses
without an "insights" list - is recorded instead of losing the whole
document. That guarantee is narrower than it sounds: it covers a malformed
answer, not a failed request. A transport/SDK failure (a dropped connection,
a rate limit, a dead key) is a different class of error and is NOT this
module's concern - each adapter leaves that to propagate out of its own
extract(), on purpose, so the caller sees a real failure instead of a job
that quietly "succeeded" with nothing in it. See the "TRANSPORT VS
RESPONSE-SHAPE ERRORS" note at the top of each adapter module.
"""
import json
from functools import lru_cache

from insights.extractors import prompt_text
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES, ROLE_VALUES,
)
from insights.taxonomy import OTHER, tags_by_dimension

# One request per chunk of pages. Chunking rather than sending a whole report
# keeps the page numbers the model must cite close to the text it is reading,
# which is the field it most often gets wrong.
PAGES_PER_REQUEST = 8


@lru_cache(maxsize=1)
def vocabulary_block():
    """The coding vocabulary, spelled out for a model that cannot read the file.

    insights/prompts/extract_insights.md tells the reader to consult
    `data_pipeline/taxonomy.json`. A host agent with file access does exactly
    that; an API model has no filesystem and guesses from memory instead - and
    the guesses are near-misses against tags that exist (`water` for
    `water_wash`, `financial_barriers` for `cash`), so they land as `other` with
    tag_raw preserved and tag-level filtering on the dashboard stops working.
    Worse, an unguided model puts a ROLE name in the dimension slot, which is
    what cost MSF's "Voices from South Darfur" all 30 of its insights on
    2026-09-21 - see the note in contract.parse().

    Sent with each request rather than pasted into the prompt file, because
    taxonomy.json changes without a migration: read at request time, the asked-
    for vocabulary and the enforced one cannot drift apart. Cached because it is
    the same text for every chunk of every document in a run.
    """
    lines = [
        "CODING VOCABULARY. Use these keys exactly as written.",
        "",
        "'dimension' is one of these five and nothing else:",
    ]
    for dimension, tags in tags_by_dimension().items():
        lines.append(f"  {dimension}: {', '.join(tags)}")
    lines += [
        "",
        f"If no tag fits, keep the dimension and write your own words in 'tag' - "
        f"it is recorded as '{OTHER}' with your suggestion kept for a reviewer.",
        f"'role' is one of {', '.join(sorted(ROLE_VALUES))}, and it belongs in the "
        f"'role' field. A role name is NEVER a dimension.",
        "",
        # The same near-miss one level down, and it costs the corridor:
        # 'internal_displacement' (a movement_pattern TAG) was proposed as a
        # flow_type on two South Darfur corridors, and contract._movements
        # dropped both.
        f"A corridor's 'flow_type' is one of {', '.join(sorted(FLOW_TYPE_VALUES))}.",
        f"A figure's 'unit' is one of {', '.join(sorted(FIGURE_UNIT_VALUES))}; a "
        f"corridor's is {', '.join(sorted(MOVEMENT_UNIT_VALUES))} only - a corridor "
        f"counts people or households, never a share.",
    ]
    return "\n".join(lines)


class Extractor:
    name = ""
    # Every subclass sets this in __init__ (settings.LLM_MODEL, with its own
    # fallback default) - declared here so the contract empty_payload() and
    # extract_insights.py both rely on (self.name, self.model) is explicit on
    # the base class rather than merely assumed of whatever __init__ happens
    # to set.
    model = None

    def __init__(self):
        # Refusals and malformed chunks hit during the extract() call in
        # progress. Reset at the top of each extract(), read by
        # extract_insights straight after and folded into ExtractionJob.log -
        # there is no model field for this (task-13-rulings.md §4) and a
        # problem must never be silently dropped (§2-3): a chunk the model
        # refused, or one whose JSON did not parse, is lost community
        # testimony if nobody is told about it.
        self.problems = []

    def extract(self, document, pages):
        """Return a payload dict matching insights/contract.py. Subclasses implement."""
        raise NotImplementedError

    def build_user_message(self, document, chunk):
        body = "\n\n".join(f"--- page {number} ---\n{text}" for number, text in chunk)
        return (
            f"Document: {document.file_name}\n"
            f"rel_path: {document.rel_path}\n"
            f"report_date: {document.report_date or 'unknown'}\n\n"
            f"{vocabulary_block()}\n\n"
            f"{body}"
        )

    def empty_payload(self, document):
        return {
            "source": {
                "rel_path": document.rel_path,
                "sha1": document.sha1,
                "report_date": document.report_date.isoformat() if document.report_date else None,
            },
            "producer": {"agent": self.name, "model": self.model},
            "insights": [],
        }

    def chunks(self, pages):
        for start in range(0, len(pages), PAGES_PER_REQUEST):
            yield pages[start:start + PAGES_PER_REQUEST]

    @staticmethod
    def chunk_label(chunk):
        """'page 4' or 'pages 4-11' - for a problem message a reviewer can act on."""
        numbers = [number for number, _ in chunk]
        if len(numbers) == 1:
            return f"page {numbers[0]}"
        return f"pages {numbers[0]}-{numbers[-1]}"

    @staticmethod
    def parse_json(text):
        """Models sometimes wrap JSON in a fence. Tolerate that and nothing else.

        A fence with nothing after its opening line (just "```" or "```json"
        with no newline - the shape a mid-stream fallback handoff can leave
        behind, see parse_insights()) must still reach json.loads() and fail
        there as a JSONDecodeError, not raise IndexError from the split: that
        is the one exception parse_insights() catches to turn a bad chunk
        into a recorded problem instead of a crashed extract() call.
        """
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("\n", 1)
            text = parts[1].rsplit("```", 1)[0] if len(parts) > 1 else ""
        return json.loads(text)

    def parse_insights(self, text):
        """Parse one chunk's raw text and pull out its "insights" list.

        Raises ValueError - never json.JSONDecodeError - on anything that does
        not parse as a JSON object with an "insights" list, so both adapters
        can catch exactly one exception type around a chunk and record it as a
        problem rather than let it kill the whole extract() call (see the
        module docstring, and task-13-rulings.md §3: this applies to BOTH
        adapters, and it is required to happen here rather than only for the
        Anthropic one, because a mid-stream server-side fallback hands off
        between two models and the joined text is not guaranteed to parse
        even when neither model individually refused).
        """
        try:
            parsed = self.parse_json(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"the model's output was not valid JSON ({exc})") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("insights"), list):
            raise ValueError('the model\'s JSON had no "insights" list')
        return parsed["insights"]

    @property
    def system_prompt(self):
        return prompt_text()
