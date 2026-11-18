"""What date is this document, and are we sure enough to use it without asking?

A wrong `report_date` is not a small error. `Insight.stated_on` rides on it, the
dashboard timeline rides on that, and once an insight is published nothing on
the page says the date was guessed. So this module is built to be honest about
uncertainty rather than to always produce an answer.

THE RANKING, AND WHY IT IS THIS WAY ROUND. Measured against the seven documents
already uploaded through the wizard, not chosen on taste:

  1. `filename`      right on both documents that had a parseable one. It read
                     EVAR_2025_FINAL_March_2026 as 2026-03-15, correctly
                     ignoring the bare 2025.
  2. `pdf_metadata`  present on all seven, and within two weeks of the filename
                     wherever both fired. The quiet workhorse: it is the only
                     source that fired on the four documents with nothing else.
  3. `text`          last, because it was WRONG on ROSEA_El-Nino_..._20260813 by
                     seven weeks - it read 2026-10-01 out of "October-December",
                     which is the El Nino forecast season, not a publication
                     date. That is not a parser bug to fix; humanitarian reports
                     are full of forward-looking dates, so prose is structurally
                     the least safe place to read a publication date from.

DISAGREEMENT IS NOT RESOLVED SILENTLY. When any source that fired differs from
the winner by more than AGREEMENT_DAYS, the guess is still offered but
`needs_person` is set and `catalogue_file` leaves `report_date` null. ROSEA is
the worked example: inference SUCCEEDED and was wrong, which is worse than
failing, because failing is visible.

The date parsers themselves are the pipeline's own - `parse_date_from_name` and
`parse_date_from_text` in data_pipeline/common.py, which between them have dated
900 documents. This module ranks and arbitrates; it does not re-implement them.
`date_source` on Document already uses this vocabulary.
"""
import datetime
import re
from dataclasses import dataclass, field

from data_pipeline.common import parse_date_from_name, parse_date_from_text

# Most preferred first. `decide` takes the first of these that fired.
SOURCE_RANKING = ("filename", "pdf_metadata", "text")

# How far apart two sources may be before a person is asked. A month, because
# the convention for a month-only date is mid-month (the pipeline's
# parse_date_from_name returns 2026-03-15 for "March 2026"), so two sources
# naming the same month can legitimately sit up to ~30 days apart.
AGREEMENT_DAYS = 31

# Only the first two pages: a publication date is printed on the cover or in the
# running header. Reading further finds the forecast seasons described above.
TEXT_PAGES = 2

# A PDF date is "D:YYYYMMDDHHmmSS" plus an optional timezone, and the "D:" is
# optional in the wild.
_PDF_DATE = re.compile(r"^D?:?(\d{4})(\d{2})(\d{2})")

# Below this, the clock that wrote the PDF was wrong (an epoch default, usually),
# and a confidently wrong date is worse than no date at all.
_EARLIEST_SANE_YEAR = 1990


@dataclass
class DateGuess:
    """A proposal, plus everything a person needs to overrule it."""

    date: datetime.date | None
    source: str | None
    needs_person: bool
    candidates: dict = field(default_factory=dict)
    # Which source disagreed, when one did. Named so the wizard can say
    # "the text says 2026-10-01" rather than only "check this".
    disagreement: str | None = None


def parse_pdf_date(value):
    """'D:20260326151033+02'00'' -> date(2026, 3, 26). None for anything else."""
    if not value:
        return None
    match = _PDF_DATE.match(str(value).strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if year < _EARLIEST_SANE_YEAR:
        return None
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def decide(candidates):
    """Rank the candidates and say whether a person has to look.

    `candidates` is {source: date} for whichever sources found one.
    """
    found = {source: value for source, value in candidates.items() if value}
    if not found:
        return DateGuess(date=None, source=None, needs_person=True, candidates={})

    source = next(name for name in SOURCE_RANKING if name in found)
    winner = found[source]

    disagreement = next(
        (name for name in SOURCE_RANKING
         if name in found and abs((found[name] - winner).days) > AGREEMENT_DAYS),
        None,
    )

    return DateGuess(
        date=winner,
        source=source,
        needs_person=disagreement is not None,
        candidates=dict(found),
        disagreement=disagreement,
    )


def gather(path, pages, pdf_metadata=None):
    """Read every source this document offers. Returns {source: date}.

    `pages` is [(number, text)] as intake._pages_of returns it, so the text is
    the one already extracted rather than a second read of the file.
    """
    head = "\n".join(
        text or "" for number, text in (pages or []) if number <= TEXT_PAGES)

    return {
        "filename": parse_date_from_name(getattr(path, "name", str(path))),
        "pdf_metadata": parse_pdf_date((pdf_metadata or {}).get("creationDate")),
        "text": parse_date_from_text(head) if head else None,
    }


def infer(path, pages, pdf_metadata=None):
    """The whole job: gather, rank, arbitrate."""
    return decide(gather(path, pages, pdf_metadata))
