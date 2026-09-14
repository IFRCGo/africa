"""What both adapters share: how a document is turned into a request, and how
a chunk that went wrong is recorded instead of losing the whole document.
"""
import json

from insights.extractors import prompt_text

# One request per chunk of pages. Chunking rather than sending a whole report
# keeps the page numbers the model must cite close to the text it is reading,
# which is the field it most often gets wrong.
PAGES_PER_REQUEST = 8


class Extractor:
    name = ""

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
