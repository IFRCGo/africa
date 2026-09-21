"""The shape every producer must write, whoever the producer is.

This module is pure - no database access - so a payload can be checked before
anything is opened. It is one of THREE halves of the same thing, and they move
together:

  1. this module                            what is accepted
  2. insights/prompts/extract_insights.md   what is asked for
  3. insights/extractors/anthropic_api.py   SCHEMA - what CAN be emitted

The third is easy to miss and it is load-bearing. SCHEMA is passed as the
request's json_schema output format with "additionalProperties": False, so a
field this module accepts but that schema omits is forbidden rather than
ignored: the model never emits it, and the run looks healthy while returning
nothing new. openai_compatible.py asks for a bare json_object and is governed by
the prompt alone.

An EMPTY insight list is an error, never a quiet success. An LLM or MCP failure
serialised as [] looks exactly like a document with nothing to say, and treating
the two alike is how a failed run comes to look like a finished one. This is the
same rule external_data/loaders/base.py already enforces, for the same reason.
"""
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES, ROLE_VALUES,
)
from insights.taxonomy import normalise_coding
from insights.verify import normalise

VOICE_TYPES = {"community", "secondary_analysis"}
CONFIDENCES = {"high", "medium", "low"}


class ContractError(Exception):
    """The payload does not meet the contract. Nothing is written."""


def _require(row, key, index):
    value = row.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ContractError(f"insights[{index}]: {key!r} is required and was {value!r}")
    return value


def _number(value, index, field):
    """A JSON number, with bool excluded the way severity and people_affected do it."""
    if type(value) is bool:
        raise ContractError(f"insights[{index}]: {field} must be a number, got a boolean")
    if not isinstance(value, (int, float)):
        raise ContractError(f"insights[{index}]: {field} must be a number, got {value!r}")
    return value


def _figures(item, index, quote_key):
    """Parse figures[]. Returns (rows, drops).

    A malformed SHAPE raises - that is a broken producer. A wrong vocabulary word
    or a span that is not in the quote drops its own row and is reported, because
    the widened prompt asks for many small structured items per document and one
    bad reading must not cost the other forty.
    """
    raw = item.get("figures") or []
    if not isinstance(raw, list):
        raise ContractError(
            f"insights[{index}]: 'figures' must be a list, got {type(raw).__name__}")

    rows, drops = [], []
    for figure in raw:
        if not isinstance(figure, dict):
            raise ContractError(f"insights[{index}]: each figure must be an object")

        written = figure.get("figure_as_written")
        if not written or not str(written).strip():
            drops.append(f"figure dropped: no figure_as_written ({figure!r})")
            continue

        unit = figure.get("unit")
        if unit not in FIGURE_UNIT_VALUES:
            drops.append(f"figure {written!r} dropped: unit {unit!r} is not one of "
                         f"{sorted(FIGURE_UNIT_VALUES)}")
            continue

        # THE CHECK THAT MAKES THE NUMBER HONEST. verify.py re-matches the quote
        # against the page; nothing re-matches a number typed beside it. Folding
        # the span the same way the quote gate folds text means a PDF's line wrap
        # does not cause a false drop, while a changed digit does.
        if normalise(written) not in normalise(quote_key):
            drops.append(f"figure {written!r} dropped: that span is not in the quote")
            continue

        measures = figure.get("measures")
        if not measures or not str(measures).strip():
            drops.append(f"figure {written!r} dropped: no 'measures'")
            continue

        rows.append({
            "figure_as_written": str(written).strip(),
            "value": float(_number(figure.get("value"), index, "figure value")),
            "unit": unit,
            "measures": str(measures).strip(),
            "applies_to": (str(figure["applies_to"]).strip()
                           if figure.get("applies_to") else None),
        })
    return rows, drops


def _movements(item, index, quote_key):
    """Parse movements[]. Returns (rows, drops). Same shape/vocabulary split as _figures."""
    raw = item.get("movements") or []
    if not isinstance(raw, list):
        raise ContractError(
            f"insights[{index}]: 'movements' must be a list, got {type(raw).__name__}")

    rows, drops = [], []
    for movement in raw:
        if not isinstance(movement, dict):
            raise ContractError(f"insights[{index}]: each movement must be an object")

        origin = movement.get("origin_name_as_written")
        destination = movement.get("dest_name_as_written")
        # One end named is a half-known corridor, and that is a finding. Neither
        # end named is not a corridor: "they fled here" states nothing to draw.
        if not (origin or destination):
            drops.append("corridor dropped: neither end is named")
            continue

        flow_type = movement.get("flow_type")
        if flow_type not in FLOW_TYPE_VALUES:
            drops.append(f"corridor {origin!r}->{destination!r} dropped: flow_type "
                         f"{flow_type!r} is not one of {sorted(FLOW_TYPE_VALUES)}")
            continue

        unit = movement.get("unit")
        written = movement.get("value_as_written")
        value = movement.get("value")
        if unit is not None and unit not in MOVEMENT_UNIT_VALUES:
            drops.append(f"corridor {origin!r}->{destination!r} dropped: unit {unit!r} "
                         f"is not one of {sorted(MOVEMENT_UNIT_VALUES)}. A corridor "
                         f"counts people or households; a share is a figure.")
            continue
        if written and normalise(written) not in normalise(quote_key):
            drops.append(f"corridor {origin!r}->{destination!r} dropped: the span "
                         f"{written!r} is not in the quote")
            continue

        rows.append({
            "origin_name_as_written": str(origin).strip() if origin else None,
            "origin_iso3": (str(movement["origin_iso3"]).strip().upper()
                            if movement.get("origin_iso3") else None),
            "dest_name_as_written": str(destination).strip() if destination else None,
            "dest_iso3": (str(movement["dest_iso3"]).strip().upper()
                          if movement.get("dest_iso3") else None),
            "flow_type": flow_type,
            "value_as_written": str(written).strip() if written else None,
            "value": int(_number(value, index, "corridor value")) if value is not None else None,
            "unit": unit,
        })
    return rows, drops


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
        if severity is not None:
            # bool subclasses int in Python, so isinstance(True, int) is True. Reject it explicitly
            # to prevent a JSON boolean from silently becoming 1/0 in an integer database column.
            if type(severity) is bool:
                raise ContractError(f"insights[{index}]: severity must be a number 1-5, got a boolean")
            if not (isinstance(severity, int) and 1 <= severity <= 5):
                raise ContractError(f"insights[{index}]: severity must be 1-5, got {severity!r}")

        people = item.get("people_affected")
        if people is not None:
            # bool subclasses int in Python, so isinstance(True, int) is True. Reject it explicitly
            # to prevent a JSON boolean from silently becoming 1/0 in an integer database column.
            if type(people) is bool:
                raise ContractError(f"insights[{index}]: people_affected must be a whole number, got a boolean")
            if not (isinstance(people, int) and people >= 0):
                raise ContractError(
                    f"insights[{index}]: people_affected must be a whole number, got {people!r}")

        codings, coding_drops = [], []
        for coding in item.get("codings") or []:
            if not isinstance(coding, dict):
                raise ContractError(f"insights[{index}]: each coding must be an object")
            try:
                # An unknown tag degrades to 'other'; an unknown dimension has no
                # row to write at all, so taxonomy.py raises. What that COSTS is
                # decided here, and it costs the coding - not the payload.
                #
                # It used to cost the payload. On MSF's "Voices from South
                # Darfur" (2026-09-21) one coding out of 30 insights put the
                # role name "barrier" in the dimension slot, and all 30 -
                # including the three community testimonies on page 9 - were
                # discarded for it. That is the same silent loss _figures and
                # _movements exist to prevent, and an unknown ROLE already
                # degrades six lines below rather than raising.
                normalised = normalise_coding(coding.get("dimension"), coding.get("tag"))
            except ValueError as exc:
                coding_drops.append(f"coding dropped: {exc}")
                continue
            # A role is an interpretation, so an unknown one degrades to 'subject'
            # the same way an unknown tag degrades to 'other'.
            role = coding.get("role")
            normalised["role"] = role if role in ROLE_VALUES else "subject"
            if normalised not in codings:
                codings.append(normalised)

        figures, figure_drops = _figures(item, index, quote)
        movements, movement_drops = _movements(item, index, quote)

        rows.append({
            "quote": str(quote).strip(),
            "quote_language": item.get("quote_language") or "en",
            "page": item.get("page"),
            "voice_type": voice_type,
            "place_name_as_written": item.get("place_name_as_written"),
            "iso3": str(iso3).strip().upper(),
            "codings": codings,
            "figures": figures,
            "movements": movements,
            "drops": coding_drops + figure_drops + movement_drops,
            "people_affected": people,
            "severity": severity,
            "confidence": confidence,
        })
    return rows
