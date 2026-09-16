"""Does this quote actually appear in the document it claims to come from?

WHY THIS EXISTS IN DJANGO RATHER THAN IN THE PROMPT. Anthropic's Citations API
would guarantee a verbatim, page-anchored quote natively - but only for Claude,
and this design accepts payloads from Codex, from a local model, and from
whatever an analyst runs next year. Re-matching the returned quote against the
page text we already store works identically for all of them, costs one query,
and cannot be talked out of by a persuasive model.

Normalisation is deliberately shallow: whitespace, unicode dashes, curly quotes
and case. It must absorb how a PDF wraps a line without absorbing a changed word,
because a changed word is exactly what this is here to catch.
"""
import hashlib
import re
import unicodedata

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b"), "'")
_QUOTES.update(dict.fromkeys(map(ord, "\u201c\u201d\u201e\u201f"), '"'))


def normalise(text):
    """Fold the differences a PDF introduces, and nothing else."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", str(text))
    folded = folded.translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", folded).strip().lower()


def quote_sha1(text):
    """Fingerprint of the normalised quote - part of the natural key."""
    return hashlib.sha1(normalise(text).encode("utf-8")).hexdigest()


def quote_is_verbatim(document_id, page, quote):
    """True when `quote` occurs on that page of that document.

    A missing page is False rather than an exception: a payload naming a page the
    document does not have is a failed extraction, which is a result, not a crash.

    Guard against degenerate fragments: a quote must have at least 3 words and at
    least 12 characters after normalisation. This is not a quality bar — human
    review filters whether a statement is worth keeping. This is purely a guard
    against "the", "the hospitals", or other trivial substrings that match
    everywhere and undermine why this gate exists in the first place.
    """
    from data_track.models import DocumentText

    needle = normalise(quote)
    if not needle:
        return False

    # Enforce minimum length: 3 words and 12 characters.
    words = needle.split()
    if len(words) < 3 or len(needle) < 12:
        return False

    row = DocumentText.objects.filter(document_id=document_id, page=page).first()
    if row is None or not row.text:
        return False
    return needle in normalise(row.text)
