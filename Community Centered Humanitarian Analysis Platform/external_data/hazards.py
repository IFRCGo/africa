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
# The UNDRR-ISC slug, the second choice: nat-hyd-flo-flo, tec-ind-che-che.
_SLUG = re.compile(r"^[a-z]{3}(-[a-z]{3}){3}$")
# The GLIDE code, the last: FL, WF, EQ. Two capitals and nothing else, which is
# why it is tested last - it would otherwise match nothing else anyway.
_GLIDE = re.compile(r"^[A-Z]{2}$")

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


def slug_from_codes(codes):
    """The UNDRR-ISC slug out of the list, or None."""
    return next((c for c in (codes or []) if _SLUG.match(c)), None)


def glide_from_codes(codes):
    """The GLIDE code out of the list, or None."""
    return next((c for c in (codes or []) if _GLIDE.match(c)), None)


def for_codes(codes):
    """(category, sub) for Montandon's whole mixed list. THE ONE TO CALL.

    THREE VOCABULARIES, TRIED IN ORDER OF PRECISION, because Montandon sends
    whichever it has and that is not always the same one:

        HIP    EN0205           authoritative, and the only one that tells
                                MH0103 (thunderstorm) from MH0301 (violent wind)
        slug   nat-hyd-flo-flo  present on ~62% of items; cannot separate those two
        GLIDE  FL               coarsest, and sometimes the only thing there is

    The design keyed on the HIP code because the slug is absent on about 38% of
    items. The first live Sudan pull showed the mirror case and cost 133 events:
    125 IDMC-IDU floods carried ONLY nat-hyd-flo-flo, and six GDACS floods
    carried only "FL". Preferring the HIP code stays right - where the
    vocabularies disagree, as on wildfire and extreme heat, it is the one that
    matches the codebook. Giving up when it was absent was the bug.
    """
    codes = codes or []
    hip = hip_from_codes(codes)
    if hip:
        entry = codebook()["hip_codes"].get(hip)
        if entry:
            return entry["category"], entry["sub"]
    slug = slug_from_codes(codes)
    if slug:
        entry = codebook()["slug_codes"].get(slug)
        if entry:
            return entry["category"], entry["sub"]
    glide = glide_from_codes(codes)
    if glide:
        entry = codebook()["glide_codes"].get(glide)
        if entry:
            return entry["category"], entry["sub"]
    return UNCATEGORISED


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
