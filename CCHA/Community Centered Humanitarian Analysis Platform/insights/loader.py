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
from datetime import date, datetime

from django.db import transaction

from insights import places
from insights.contract import ContractError, parse
from insights.models import Insight, InsightCoding, InsightFigure, InsightMovement
from insights.verify import quote_is_verbatim, quote_sha1


@dataclass
class LoadReport:
    written: int = 0
    rejected_unverifiable: int = 0
    skipped_reviewed: int = 0
    # Codings, figures and corridors dropped for a wrong vocabulary word or an
    # unquoted span. Kept apart from rejected_unverifiable, which means "whole
    # insights that failed the quote gate" and which a reviewer already watches,
    # and kept apart from each other so the changelist says WHICH kind of
    # reading the model is getting wrong.
    codings_rejected: int = 0
    figures_rejected: int = 0
    movements_rejected: int = 0


def _side(iso3, place_name, prefix):
    """Resolve one end of a corridor into prefixed columns.

    places.resolve() is called with the SIDE's own iso3, never the parent
    insight's. On the corridor this exists for - Sudan to Egypt - the parent is
    one of the two countries and inheriting it would place the other end in the
    wrong one.
    """
    placement = places.resolve(iso3, place_name)
    return {
        f"{prefix}_pcode": placement["admin_pcode"],
        f"{prefix}_admin_level": placement["admin_level"],
        f"{prefix}_match_method": placement["match_method"],
        f"{prefix}_lat": placement["lat"],
        f"{prefix}_lon": placement["lon"],
    }


def _coerce_stated_on(value):
    """Reduce whatever the payload or document gave us to a plain date.

    A datetime - or an ISO timestamp string, which is just a datetime spelled
    as text - is a real date wearing extra precision, so its .date() is taken
    without complaint (datetime is a subclass of date, so it is checked first).
    Anything else that is not already a plain date is a malformed payload, not
    ours to guess at, so it becomes a ContractError naming the offending value
    rather than a bare ValueError escaping into a caller that only catches
    ContractError.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            raise ContractError(
                f"payload's date {value!r} is not a valid YYYY-MM-DD date "
                "(or a full ISO timestamp)"
            )
    raise ContractError(
        f"payload's date must be a string (YYYY-MM-DD) or a date, not "
        f"{type(value).__name__}: {value!r}"
    )


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
    # reload would get a str where it expects a date. A falsy value (None, "",
    # 0) is left alone here and caught by the "no usable date" check below,
    # rather than fed to _coerce_stated_on, which would reject it as a bad type.
    if stated_on:
        stated_on = _coerce_stated_on(stated_on)

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

    # A drop must never be silent - a figure nobody is told about is a figure a
    # reviewer cannot ask for. Counted in the report, named in the job log.
    drop_messages = []

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
            # Codings, figures and movements are replaced wholesale: a re-run's
            # reading of the statement supersedes its own earlier one, and merging
            # them would accumulate rows no single reading ever proposed. Neither
            # child table has a natural key, so without this a re-run duplicates
            # every figure and corridor.
            insight.codings.all().delete()
            insight.figures.all().delete()
            insight.movements.all().delete()

        InsightCoding.objects.bulk_create(
            [InsightCoding(insight=insight, **coding) for coding in row["codings"]]
        )
        InsightFigure.objects.bulk_create(
            [InsightFigure(insight=insight, **figure) for figure in row["figures"]]
        )
        InsightMovement.objects.bulk_create([
            InsightMovement(
                insight=insight,
                origin_name_as_written=movement["origin_name_as_written"],
                origin_iso3=movement["origin_iso3"],
                dest_name_as_written=movement["dest_name_as_written"],
                dest_iso3=movement["dest_iso3"],
                flow_type=movement["flow_type"],
                value_as_written=movement["value_as_written"],
                value=movement["value"],
                unit=movement["unit"],
                # Gate 3, once per side.
                **_side(movement["origin_iso3"], movement["origin_name_as_written"], "origin"),
                **_side(movement["dest_iso3"], movement["dest_name_as_written"], "dest"),
            )
            for movement in row["movements"]
        ])

        # Dispatched on the first word contract.parse() gives each message -
        # "coding dropped: ...", "corridor ... dropped: ...", "figure ...".
        for drop in row["drops"]:
            if drop.startswith("corridor"):
                report.movements_rejected += 1
            elif drop.startswith("coding"):
                report.codings_rejected += 1
            else:
                report.figures_rejected += 1
            drop_messages.append(f"{document.file_name if document else 'manual'}: {drop}")

        report.written += 1

    if job is not None:
        job.insights_proposed += len(rows)
        job.insights_rejected_unverifiable += report.rejected_unverifiable
        job.insights_skipped_reviewed += report.skipped_reviewed
        job.codings_rejected += report.codings_rejected
        job.figures_rejected += report.figures_rejected
        job.movements_rejected += report.movements_rejected
        if drop_messages:
            job.log = "\n".join(filter(None, [job.log, *drop_messages]))
        job.save(update_fields=[
            "insights_proposed", "insights_rejected_unverifiable",
            "insights_skipped_reviewed", "codings_rejected", "figures_rejected",
            "movements_rejected",
            "log",
        ])

    return report
