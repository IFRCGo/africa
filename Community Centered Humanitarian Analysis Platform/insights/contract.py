"""The shape every producer must write, whoever the producer is.

This module is pure - no database access - so a payload can be checked before
anything is opened. It is the machine-readable half of
insights/prompts/extract_insights.md; when one changes, so must the other.

An EMPTY insight list is an error, never a quiet success. An LLM or MCP failure
serialised as [] looks exactly like a document with nothing to say, and treating
the two alike is how a failed run comes to look like a finished one. This is the
same rule external_data/loaders/base.py already enforces, for the same reason.
"""
from insights.taxonomy import normalise_coding

VOICE_TYPES = {"community", "secondary_analysis"}
CONFIDENCES = {"high", "medium", "low"}


class ContractError(Exception):
    """The payload does not meet the contract. Nothing is written."""


def _require(row, key, index):
    value = row.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ContractError(f"insights[{index}]: {key!r} is required and was {value!r}")
    return value


def parse(payload):
    """Validate and normalise. Returns one dict per insight; raises on anything else."""
    if not isinstance(payload, dict):
        raise ContractError(f"payload must be an object, got {type(payload).__name__}")

    raw = payload.get("insights")
    if not isinstance(raw, list) or not raw:
        raise ContractError(
            "payload holds no insights. An LLM or MCP error serialised as an empty "
            "list looks exactly like this - check the run before treating it as "
            "'this document had nothing to say'."
        )

    rows = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ContractError(f"insights[{index}] must be an object")

        quote = _require(item, "quote", index)
        iso3 = _require(item, "iso3", index)

        voice_type = item.get("voice_type", "community")
        if voice_type not in VOICE_TYPES:
            raise ContractError(
                f"insights[{index}]: voice_type {voice_type!r} not in {sorted(VOICE_TYPES)}")

        confidence = item.get("confidence")
        if confidence is not None and confidence not in CONFIDENCES:
            raise ContractError(
                f"insights[{index}]: confidence {confidence!r} not in {sorted(CONFIDENCES)}")

        severity = item.get("severity")
        if severity is not None and not (isinstance(severity, int) and 1 <= severity <= 5):
            raise ContractError(f"insights[{index}]: severity must be 1-5, got {severity!r}")

        people = item.get("people_affected")
        if people is not None and not (isinstance(people, int) and people >= 0):
            raise ContractError(
                f"insights[{index}]: people_affected must be a whole number, got {people!r}")

        codings = []
        for coding in item.get("codings") or []:
            if not isinstance(coding, dict):
                raise ContractError(f"insights[{index}]: each coding must be an object")
            try:
                # An unknown dimension raises; an unknown tag degrades. See taxonomy.py.
                normalised = normalise_coding(coding.get("dimension"), coding.get("tag"))
            except ValueError as exc:
                raise ContractError(f"insights[{index}]: {exc}") from exc
            if normalised not in codings:
                codings.append(normalised)

        rows.append({
            "quote": str(quote).strip(),
            "quote_language": item.get("quote_language") or "en",
            "page": item.get("page"),
            "voice_type": voice_type,
            "place_name_as_written": item.get("place_name_as_written"),
            "iso3": str(iso3).strip().upper(),
            "codings": codings,
            "people_affected": people,
            "severity": severity,
            "confidence": confidence,
        })
    return rows
