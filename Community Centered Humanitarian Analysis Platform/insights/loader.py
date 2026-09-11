"""Apply the four gates, then write. One payload is one transaction.

The gates, in order (spec §6.4):

  1. verbatim     the quote must occur in the page it names - SKIPPED when the
                  insight has no document, because there is nothing to check
                  against and no pretence that there is
  2. vocabulary   applied in contract.parse() before we get here
  3. place        resolved, or honestly recorded as unmatched
  4. conflict     a row a human has reviewed is SKIPPED, never overwritten

Gate 4 is the deliberate difference from external_data/loaders/base.py, which
upserts on conflict. That is right for API data and wrong here: re-running an
extraction would silently discard every correction a reviewer had made.
"""
from dataclasses import dataclass
from datetime import date

from django.db import transaction

from insights import places
from insights.contract import ContractError, parse
from insights.models import Insight, InsightCoding
from insights.verify import quote_is_verbatim, quote_sha1


@dataclass
class LoadReport:
    written: int = 0
    rejected_unverifiable: int = 0
    skipped_reviewed: int = 0


@transaction.atomic
def load(payload, document=None, job=None, method="llm", model_used=None):
    """Write every insight in `payload` that passes the gates.

    `document` may be None for a manual or primary-collected statement, in which
    case gate 1 does not apply - see the module docstring.
    """
    rows = parse(payload)
    report = LoadReport()

    stated_on = (payload.get("source") or {}).get("report_date")
    if document is not None and not stated_on:
        stated_on = document.report_date
    # Same guard intake uses: Django stores a string date happily, but the
    # in-memory object keeps the string, so anything reading .stated_on before a
    # reload would get a str where it expects a date.
    if isinstance(stated_on, str):
        stated_on = date.fromisoformat(stated_on)

    # stated_on is what the dashboard's month timeline rides on, so a dateless
    # insight could never be displayed even if it were stored - refuse the whole
    # payload here rather than let a NOT NULL column turn this into a bare
    # IntegrityError. report_date lives on the payload's source block, not per
    # insight, so an undated payload is undated for every row in it.
    if not stated_on:
        raise ContractError(
            "payload has no usable date: set source.report_date (YYYY-MM-DD), "
            "or attach it to a document whose report_date is set"
        )

    for row in rows:
        # Gate 1 - only where there is a document to check against.
        if document is not None and not quote_is_verbatim(document.id, row["page"], row["quote"]):
            report.rejected_unverifiable += 1
            continue

        sha1 = quote_sha1(row["quote"])
        page = row["page"] if document is not None else None

        existing = Insight.objects.filter(
            document=document, page=page, quote_sha1=sha1).first()

        # Gate 4 - a reviewer owns this row now.
        if existing is not None and existing.status != "pending":
            report.skipped_reviewed += 1
            continue

        # Gate 3.
        placement = places.resolve(row["iso3"], row["place_name_as_written"])

        fields = dict(
            quote=row["quote"],
            quote_language=row["quote_language"],
            quote_sha1=sha1,
            voice_type=row["voice_type"],
            channel="document_ai" if document is not None else "manual",
            document=document,
            page=page,
            stated_on=stated_on,
            iso3=row["iso3"],
            place_name_as_written=row["place_name_as_written"],
            people_affected=row["people_affected"],
            severity=row["severity"],
            method=method,
            model_used=model_used or (payload.get("producer") or {}).get("model"),
            confidence=row["confidence"],
            status="pending",
            job=job,
            **placement,
        )

        if existing is None:
            insight = Insight.objects.create(**fields)
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.save()
            insight = existing
            # Codings are replaced wholesale: a re-run's reading of the statement
            # supersedes its own earlier one, and merging them would accumulate
            # tags no single reading ever proposed.
            insight.codings.all().delete()

        InsightCoding.objects.bulk_create(
            [InsightCoding(insight=insight, **coding) for coding in row["codings"]]
        )
        report.written += 1

    if job is not None:
        job.insights_proposed += len(rows)
        job.insights_rejected_unverifiable += report.rejected_unverifiable
        job.insights_skipped_reviewed += report.skipped_reviewed
        job.save(update_fields=["insights_proposed", "insights_rejected_unverifiable",
                                "insights_skipped_reviewed"])

    return report
