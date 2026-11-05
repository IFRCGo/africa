"""The one place the coding vocabulary is enforced.

Codings are constrained to the keys already in data_pipeline/taxonomy.json, and
that is what lets an insight inherit the dashboard's existing dimension colours
and labels (DIM_META in app.js) without a single new mapping.

A proposal outside the vocabulary is NOT an error. The dimension is kept, the tag
becomes 'other', and what was actually proposed is preserved in tag_raw so a
reviewer can see it and decide whether the taxonomy should grow. The taxonomy
grows by a human decision, never by a model's.

There is no database CHECK constraint behind this, deliberately: taxonomy.json
changes without a migration, and a constraint would have to be rewritten every
time it did.
"""
from functools import lru_cache

from data_pipeline.common import load_taxonomy

OTHER = "other"


@lru_cache(maxsize=1)
def _vocabulary():
    """{dimension: {tag}} - the real dimensions only, '_comment' dropped."""
    return {
        dimension: set(tags)
        for dimension, tags in load_taxonomy().items()
        if not dimension.startswith("_") and isinstance(tags, dict)
    }


def valid_dimensions():
    return set(_vocabulary())


def tags_by_dimension():
    """{dimension: [tag, ...]} with both levels sorted.

    For SHOWING the vocabulary rather than enforcing it: the in-container
    adapters send this with every request, because extract_insights.md tells the
    model to read data_pipeline/taxonomy.json and only a host agent with file
    access can do that. Sorted so the same taxonomy always produces the same
    text - a set's iteration order varies between processes, and a prompt that
    changes shape run to run cannot be cached or compared.
    """
    return {
        dimension: sorted(tags) for dimension, tags in sorted(_vocabulary().items())
    }


def _slug(text):
    """'Water WASH' -> 'water_wash'. Tolerates spacing and case, nothing more."""
    return "_".join(str(text).strip().lower().split()).replace("-", "_")


def normalise_coding(dimension, tag):
    """Return the coding to store. Raises ValueError on an unknown dimension.

    An unknown TAG degrades; an unknown DIMENSION does not, because there is no
    sensible row to write for it and a payload proposing one is malformed.
    """
    vocabulary = _vocabulary()
    if dimension not in vocabulary:
        raise ValueError(
            f"unknown dimension {dimension!r}; expected one of {sorted(vocabulary)}"
        )

    candidate = _slug(tag)
    if candidate in vocabulary[dimension]:
        return {"dimension": dimension, "tag": candidate, "tag_raw": None}
    return {"dimension": dimension, "tag": OTHER, "tag_raw": str(tag).strip()}
