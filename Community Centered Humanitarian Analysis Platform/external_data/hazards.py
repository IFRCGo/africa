"""The hazard vocabulary, read once and answered from memory.

THE CODEBOOK IS A CLUSTERING METHOD, NOT A LIST TO RENDER. It supplies the
categories and the definitions that say what belongs in each; membership comes
from whatever Montandon and the document corpus actually hold. Writing all
sixteen of the codebook's named hazards out would offer a Sahel operation
tsunamis and volcanic eruptions while hiding the convective storms that really
happen here. See
docs/superpowers/specs/2026-09-17-montandon-hazard-layer-design.md.

This module lives in external_data rather than data_pipeline because a fetcher
must not import the pipeline - fetchers/ipc.py says so where it parses
CRISIS_START out of settings for the same reason. The pipeline already imports
this way round (s06_mcp_layers imports external_data.models), so s03_parse and
s06 read the vocabulary from here.
"""
import functools
import json
import re

from django.conf import settings

# A HIP code is two letters and four digits: EN0205, MH0600, GH0101. Montandon
# sends it in a list beside a GLIDE two-letter code ("WF") and a UNDRR slug
# ("nat-cli-wil-wil"), in no fixed order, and the slug is missing about 38% of
# the time - so this pattern, not a position, is how the code is found.
_HIP = re.compile(r"^[A-Z]{2}\d{4}$")

UNCATEGORISED = ("uncategorised", "uncategorised")


@functools.lru_cache(maxsize=1)
def codebook():
    """The parsed file. Cached: it is read on every tag of every document."""
    return json.loads(settings.HAZARD_CODEBOOK.read_text(encoding="utf-8"))


def categories():
    """Every category, in display order. The dashboard's dropdown order."""
    return codebook()["categories"]


def for_hip(code):
    """(category, sub) for a HIP code. Unknown codes are never guessed at."""
    entry = codebook()["hip_codes"].get(code or "")
    return (entry["category"], entry["sub"]) if entry else UNCATEGORISED


def for_tag(tag):
    """(category, sub) for a document tag, or (None, None) if unmapped.

    None rather than 'uncategorised': an unmapped TAG is a bug in this file that
    test_every_taxonomy_hazard_tag_is_mapped exists to catch, whereas an
    unmapped HIP CODE is Montandon publishing something new, which is ordinary.
    """
    entry = codebook()["tags"].get(tag or "")
    return (entry["category"], entry["sub"]) if entry else (None, None)


def hip_from_codes(codes):
    """The HIP code out of Montandon's mixed list, or None."""
    return next((c for c in (codes or []) if _HIP.match(c)), None)


@functools.lru_cache(maxsize=None)
def sub_label(sub_key):
    """The human label for a sub-hazard key, or the key if it is unknown."""
    for cat in categories():
        for sub in cat["sub_hazards"]:
            if sub["key"] == sub_key:
                return sub["label"]
    return sub_key


def is_detection(collection, severity_label, max_impact):
    """Is this a machine observation with no evidence of consequence?

    385 of the first 500 events across the eight countries are GDACS satellite
    fire detections, Green with zero people potentially affected. Everything is
    stored - a real fire beside a displacement site must not be dropped with the
    noise - but a detection draws only under its own sub-hazard, never when a
    whole category is picked.

    Only GDACS is configured, because only GDACS produces the problem. A source
    with no rule publishes events only, which also means a null severity - every
    IDMC-IDU row, since there is no idmc-idu-hazards collection - is never read
    as "no alert".
    """
    rule = codebook()["detection_rules"].get(collection)
    if not rule:
        return False
    if severity_label not in rule["no_alert_severity_labels"]:
        return False
    return not max_impact          # 0 and None both mean "nothing recorded"
