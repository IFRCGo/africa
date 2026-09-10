# Community Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the platform a home for what a community actually said — a verbatim statement, the codings derived from it, three ways in, a human review gate in Django Admin, and a dashboard panel and map layer that show only what a person has published.

**Architecture:** A new Django app `insights` holds four tables that no pipeline step ever writes to. One JSON contract is produced by any agent — Claude Code, Codex, a local model or an in-container adapter — and a loader applies four gates before a row exists: the quote must occur verbatim in the stored page text, tags must be in the existing taxonomy, the place is resolved against `admin_areas`, and a row a human has already reviewed is never overwritten. Everything lands `pending`; Admin publishes; the dashboard reads published rows from a live endpoint.

**Tech Stack:** Django 5.0.6, PostgreSQL 16 + PostGIS 3.4, psycopg 3, PyMuPDF, python-docx. One new dependency (`anthropic`) and only in Task 13.

**Spec:** `docs/superpowers/specs/2026-09-10-community-insights-design.md`

**Scope note:** This plan implements spec §5–§13 and §15. Spec **§14** — deleting `updater/`, moving the pipeline run into an Admin action, and making `dashboard/data/` a rebuild-on-demand cache — is an independent subsystem that neither depends on this work nor is depended on by it. It gets its own plan: `docs/superpowers/plans/2026-09-10-updater-absorption.md`, to be written after this one.

## Global Constraints

- **Everything runs in Docker:** `docker compose exec web python manage.py <cmd>`. The host has no Django environment.
- **Tests use Django's built-in runner** (`manage.py test`), with `django.test.TestCase` and fixtures under `<app>/tests/fixtures/`. There is no pytest in this project and this plan does not add one. Follow `external_data/tests/test_loader.py` for style.
- **No new Python dependencies before Task 13.** Tasks 1–12 add nothing to `requirements.txt`.
- **No GeoDjango.** `lat`/`lon` are plain floats; `admin_pcode` is plain text, never a ForeignKey. See spec §5.5.
- **`nulls_distinct=False` on every unique constraint containing a nullable column.** PostgreSQL treats two NULLs as distinct, which would let duplicate manual insights through on `document`/`page`. Same trap `admin_areas.uniq_area_identity` and `source_sync.uniq_source_sync_identity` already document.
- **Upserts use `bulk_create(update_conflicts=True, unique_fields=..., update_fields=...)`**, which Django 5.0 compiles to `ON CONFLICT DO UPDATE` on PostgreSQL.
- **Settings read as `os.environ.get(X) or default`**, never `get(X, default)` — an empty string in `.env` must fall through to the default.
- **Never write to `/work`.** It is mounted read-only (`docker-compose.yml`, mount 1). Payloads go to `data_pipeline/mcp_cache/insights/`, uploads to `MEDIA_ROOT` under `/app`.
- **Do not touch `data_track` models, `data_pipeline/steps/`, or `updater/`.** This plan adds an app; it changes no pipeline behaviour.
- **`app.js` is ~2900 lines. Do not edit it with shell heredocs** — large payloads break. Write the change to a patch file in the scratchpad and apply it, or use the Edit tool.
- **The dashboard renders at `--ui-scale: 0.8`.** Anything computing pointer position from raw event coordinates must account for it; this matters for the map bubble click handling in Task 12.

---

### Task 1: App skeleton, the four models, and the migration

**Files:**
- Create: `insights/__init__.py`, `insights/apps.py`, `insights/models.py`, `insights/migrations/__init__.py`
- Create: `insights/tests/__init__.py`, `insights/tests/test_models.py`
- Modify: `config/settings.py` (INSTALLED_APPS, after `"external_data",`)

**Interfaces:**
- Consumes: nothing.
- Produces: `insights.models.Insight`, `InsightCoding`, `InsightFolder`, `ExtractionJob`. Field names are exactly as written below and every later task depends on them.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/__init__.py` (empty) and `insights/tests/test_models.py`:

```python
"""The constraints, proved rather than assumed.

The duplicate-manual-entry test is the one that matters: a hand-typed insight has
a null document and a null page, and under PostgreSQL's default rule two NULLs
never collide - so without nulls_distinct=False every duplicate would be accepted
silently. This is the same trap admin_areas and source_sync already document.
"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from insights.models import ExtractionJob, Insight, InsightCoding


def make_insight(**kwargs):
    defaults = dict(
        quote="We have cholera now and nowhere to take the sick.",
        quote_sha1="a" * 40,
        voice_type="community",
        channel="manual",
        stated_on="2026-03-14",
        iso3="ETH",
        method="manual",
        status="pending",
    )
    defaults.update(kwargs)
    return Insight.objects.create(**defaults)


class InsightConstraintTests(TestCase):
    def test_two_identical_manual_insights_collide(self):
        """Null document and null page: quote_sha1 alone must distinguish them."""
        make_insight()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_insight()

    def test_the_same_quote_on_two_pages_is_two_rows(self):
        make_insight(quote_sha1="b" * 40, page=1)
        make_insight(quote_sha1="b" * 40, page=2)
        self.assertEqual(Insight.objects.count(), 2)

    def test_status_defaults_to_pending(self):
        self.assertEqual(make_insight().status, "pending")

    def test_people_affected_and_severity_are_optional(self):
        row = make_insight()
        self.assertIsNone(row.people_affected)
        self.assertIsNone(row.severity)


class InsightCodingTests(TestCase):
    def test_a_coding_cannot_repeat_within_one_insight(self):
        insight = make_insight()
        InsightCoding.objects.create(insight=insight, dimension="hazard", tag="flooding")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InsightCoding.objects.create(
                    insight=insight, dimension="hazard", tag="flooding")

    def test_one_insight_carries_many_codings(self):
        insight = make_insight()
        for dim, tag in [("hazard", "flooding"), ("hazard", "disease_outbreak"),
                         ("need", "health"), ("need", "water_wash")]:
            InsightCoding.objects.create(insight=insight, dimension=dim, tag=tag)
        self.assertEqual(insight.codings.count(), 4)


class ExtractionJobTests(TestCase):
    def test_counters_start_at_zero(self):
        job = ExtractionJob.objects.create(producer="external")
        self.assertEqual(job.insights_proposed, 0)
        self.assertEqual(job.insights_rejected_unverifiable, 0)
        self.assertEqual(job.insights_skipped_reviewed, 0)
        self.assertEqual(job.status, "queued")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights'`

- [ ] **Step 3: Create the app skeleton**

Create `insights/__init__.py` (empty), `insights/migrations/__init__.py` (empty), and `insights/apps.py`:

```python
from django.apps import AppConfig


class InsightsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "insights"
    verbose_name = "Community insights (statements, codings, intake, extraction jobs)"
```

- [ ] **Step 4: Write the models**

Create `insights/models.py`:

```python
"""What a community said, and everything derived from it.

    Insight         one statement, verbatim and whole - THE record
      |- InsightCoding   the hazards, needs and vulnerabilities read out of it
    InsightFolder   a registered folder of source documents
    ExtractionJob   one run: what it read, what it proposed, what it rejected

WHY THIS IS NOT data_track.NarrativeTag. That table records "a UNHCR report
mentioned flooding" - a keyword match on an analyst's prose, rebuilt from scratch
by s03_parse on every pipeline run. This one records "a community in Afar said
this", kept because a person reviewed it and published it. Nothing in
data_pipeline writes here, and nothing here is ever truncated.

The statement and its interpretation are deliberately two tables. Flattening the
codings into one tagged row per theme would lose the statement, which is the only
part no model can reconstruct.
"""
from django.conf import settings
from django.db import models

VOICE_TYPES = [("community", "Community voice"), ("secondary_analysis", "Secondary analysis")]
CHANNELS = [("document_ai", "Document (AI)"), ("manual", "Typed by hand"), ("primary", "Primary collection")]
STATUSES = [("pending", "Pending review"), ("published", "Published"), ("rejected", "Rejected")]
DIMENSIONS = [("hazard", "Hazard"), ("vulnerability", "Vulnerability"), ("need", "Need"),
              ("coping", "Coping"), ("movement_pattern", "Movement pattern")]


class InsightFolder(models.Model):
    """A folder of source documents, registered once and re-read on demand."""

    label = models.TextField(help_text="e.g. 'IOM DTM Chad round 12'")
    path = models.TextField(unique=True, help_text="Must resolve inside the container")
    default_iso3 = models.CharField(max_length=3, null=True, blank=True)
    recursive = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "insight_folders"
        ordering = ["label"]

    def __str__(self):
        return self.label


class ExtractionJob(models.Model):
    """One extraction run, and what it cost in rejected quotes.

    insights_rejected_unverifiable is the number worth watching: it is a direct
    per-run measurement of how much a given model invents, and it is why pointing
    an unknown local model at this is safe to try.
    """

    folder = models.ForeignKey(InsightFolder, on_delete=models.SET_NULL, null=True, blank=True)
    producer = models.TextField(default="external", help_text="external / anthropic / openai_compatible")
    model_used = models.TextField(null=True, blank=True)
    status = models.TextField(default="queued", help_text="queued / running / loaded / failed")
    documents_total = models.IntegerField(default=0)
    documents_done = models.IntegerField(default=0)
    insights_proposed = models.IntegerField(default=0)
    insights_rejected_unverifiable = models.IntegerField(default=0)
    insights_skipped_reviewed = models.IntegerField(default=0)
    log = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "insight_jobs"
        ordering = ["-id"]

    def __str__(self):
        return f"job {self.id} ({self.producer}, {self.status})"


class Insight(models.Model):
    """One thing a community said, kept whole."""

    # ---- the record itself
    quote = models.TextField(help_text="Verbatim, in full. Never summarised or trimmed.")
    quote_language = models.CharField(max_length=8, default="en")
    quote_translated = models.TextField(null=True, blank=True)
    # Fingerprint of the normalised quote. Part of the natural key, which is why
    # editing the quote in Admin has to recompute it.
    quote_sha1 = models.CharField(max_length=40)

    voice_type = models.TextField(choices=VOICE_TYPES, default="community")
    channel = models.TextField(choices=CHANNELS, default="document_ai")

    # ---- where it came from
    document = models.ForeignKey(
        "data_track.Document", on_delete=models.CASCADE, related_name="insights",
        null=True, blank=True, help_text="Null for manual and primary-collected statements",
    )
    page = models.IntegerField(null=True, blank=True)
    stated_on = models.DateField(
        db_index=True, help_text="Report date, or collection date. The dashboard timeline rides on this.",
    )

    # ---- where the people are
    iso3 = models.CharField(max_length=3, db_index=True)
    place_name_as_written = models.TextField(null=True, blank=True)
    admin_pcode = models.TextField(null=True, blank=True)
    admin_level = models.IntegerField(null=True, blank=True)
    match_method = models.TextField(default="unmatched", help_text="pcode / name / unmatched")
    # Copied from AdminArea.center_lat/center_lon - a point guaranteed inside the
    # polygon. A LABEL POSITION, not an address. See the popup note in the spec.
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    # ---- optional, and usually absent
    people_affected = models.BigIntegerField(null=True, blank=True)
    severity = models.IntegerField(null=True, blank=True, help_text="1-5, as Event.severity")

    # ---- provenance
    method = models.TextField(default="llm", help_text="llm / manual")
    model_used = models.TextField(null=True, blank=True)
    confidence = models.TextField(null=True, blank=True, help_text="high / medium / low")

    # ---- review
    status = models.TextField(choices=STATUSES, default="pending", db_index=True)
    rejection_reason = models.TextField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    job = models.ForeignKey(ExtractionJob, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="insights")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "insights"
        ordering = ["-stated_on", "id"]
        constraints = [
            # nulls_distinct=False because a manual insight has a null document AND
            # a null page. Under PostgreSQL's default rule two NULLs never collide,
            # so every duplicate hand-typed statement would be accepted silently.
            models.UniqueConstraint(
                fields=["document", "page", "quote_sha1"],
                name="uniq_insight_quote", nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["status", "voice_type", "stated_on"], name="idx_insight_publish"),
            models.Index(fields=["iso3", "stated_on"], name="idx_insight_place"),
        ]

    def __str__(self):
        return f"{self.iso3} {self.stated_on}: {self.quote[:60]}"


class InsightCoding(models.Model):
    """One theme read out of one statement.

    `tag` is constrained to taxonomy.json at load time rather than by a database
    check, because the vocabulary is a JSON file that changes without a migration.
    See insights/taxonomy.py, which is the single place that enforces it.
    """

    insight = models.ForeignKey(Insight, on_delete=models.CASCADE, related_name="codings")
    dimension = models.TextField(choices=DIMENSIONS)
    tag = models.TextField(help_text="A key in taxonomy.json under this dimension, or 'other'")
    tag_raw = models.TextField(
        null=True, blank=True, help_text="What was proposed, when it fell outside the vocabulary")

    class Meta:
        db_table = "insight_codings"
        ordering = ["dimension", "tag"]
        constraints = [
            models.UniqueConstraint(
                fields=["insight", "dimension", "tag"], name="uniq_insight_coding"),
        ]

    def __str__(self):
        return f"{self.dimension}:{self.tag}"
```

- [ ] **Step 5: Register the app**

In `config/settings.py`, add `"insights",` to `INSTALLED_APPS` immediately after `"external_data",`, with a comment matching the surrounding style:

```python
    "external_data",                 # IPC, FEWS NET, DTM, UNHCR + their freshness
    "insights",                      # what communities said, and who reviewed it
```

- [ ] **Step 6: Make and apply the migration**

```bash
docker compose exec web python manage.py makemigrations insights
docker compose exec web python manage.py migrate
```

Expected: creates `insights/migrations/0001_initial.py` with four tables.

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: 7 tests, all PASS.

- [ ] **Step 8: Commit**

```bash
git add insights config/settings.py
git commit -m "insights: four tables the pipeline never writes to

Insight is the statement, kept whole; InsightCoding is what was read out of
it. Keeping them apart is the point - flattening the codings into tagged rows
would lose the statement, which is the only part no model can reconstruct.

nulls_distinct=False on uniq_insight_quote because a hand-typed insight has a
null document and a null page, and PostgreSQL would otherwise treat every
duplicate as distinct."
```

---

### Task 2: The taxonomy vocabulary gate

**Files:**
- Create: `insights/taxonomy.py`
- Create: `insights/tests/test_taxonomy.py`

**Interfaces:**
- Consumes: `data_pipeline.common.load_taxonomy()` — returns the parsed `taxonomy.json` as `{dimension: {tag: [patterns]}}`, plus a `_comment` key that is not a dimension.
- Produces: `insights.taxonomy.normalise_coding(dimension, tag) -> dict` returning `{"dimension": str, "tag": str, "tag_raw": str | None}`, and `insights.taxonomy.valid_dimensions() -> set[str]`. Tasks 6 and 8 both call `normalise_coding`.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_taxonomy.py`:

```python
"""The vocabulary gate: a model may not grow the taxonomy by itself."""
from django.test import SimpleTestCase

from insights.taxonomy import normalise_coding, valid_dimensions


class VocabularyTests(SimpleTestCase):
    def test_a_known_tag_passes_through_untouched(self):
        self.assertEqual(
            normalise_coding("hazard", "flooding"),
            {"dimension": "hazard", "tag": "flooding", "tag_raw": None},
        )

    def test_an_unknown_tag_degrades_and_keeps_what_was_proposed(self):
        self.assertEqual(
            normalise_coding("hazard", "locusts"),
            {"dimension": "hazard", "tag": "other", "tag_raw": "locusts"},
        )

    def test_a_tag_from_the_wrong_dimension_degrades(self):
        """'flooding' is a hazard, not a need. The dimension is kept, the tag is not."""
        self.assertEqual(
            normalise_coding("need", "flooding"),
            {"dimension": "need", "tag": "other", "tag_raw": "flooding"},
        )

    def test_an_unknown_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            normalise_coding("vibes", "flooding")

    def test_the_comment_key_is_not_a_dimension(self):
        self.assertNotIn("_comment", valid_dimensions())

    def test_the_five_real_dimensions_are_present(self):
        self.assertEqual(
            valid_dimensions(),
            {"hazard", "vulnerability", "coping", "need", "movement_pattern"},
        )

    def test_tags_are_matched_case_and_space_insensitively(self):
        self.assertEqual(normalise_coding("need", "Water WASH")["tag"], "water_wash")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_taxonomy -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.taxonomy'`

- [ ] **Step 3: Write the implementation**

Create `insights/taxonomy.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_taxonomy -v 2`
Expected: 7 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add insights/taxonomy.py insights/tests/test_taxonomy.py
git commit -m "insights: constrain codings to the existing taxonomy

Reusing taxonomy.json's keys is what lets these rows inherit the dashboard's
dimension colours and labels with no new mapping. An off-vocabulary tag
degrades to 'other' and keeps what was proposed in tag_raw, so the taxonomy
grows by a reviewer's decision rather than a model's."
```

---

### Task 3: The verbatim gate

**Files:**
- Create: `insights/verify.py`
- Create: `insights/tests/test_verify.py`

**Interfaces:**
- Consumes: `data_track.models.DocumentText`.
- Produces: `insights.verify.normalise(text) -> str`, `insights.verify.quote_sha1(text) -> str`, and `insights.verify.quote_is_verbatim(document_id, page, quote) -> bool`. Tasks 6 and 8 both call `quote_sha1`; Task 6 and Task 8 both call `quote_is_verbatim`.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_verify.py`:

```python
"""The gate that makes an unknown model safe to use.

This is the only guard in the design that does not depend on which provider
produced the payload, which is exactly why it is the one that matters. A model
that invents produces FEWER insights, not wrong ones.
"""
from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.verify import normalise, quote_is_verbatim, quote_sha1

PAGE_TEXT = (
    "Participants explained:  “When it rains we get flash floods,\n"
    "and with the fighting around us the hospitals are gone — we have\n"
    "cholera now and nowhere to take the sick.”\n"
)


class NormaliseTests(TestCase):
    def test_runs_of_whitespace_collapse(self):
        self.assertEqual(normalise("a   b\n\nc"), "a b c")

    def test_unicode_dashes_fold_to_hyphen(self):
        self.assertEqual(normalise("a — b"), normalise("a - b"))

    def test_curly_quotes_fold_to_straight(self):
        self.assertEqual(normalise("“hi”"), normalise('"hi"'))

    def test_case_is_ignored(self):
        self.assertEqual(normalise("Flood"), normalise("flood"))


class Sha1Tests(TestCase):
    def test_the_same_quote_formatted_differently_hashes_the_same(self):
        self.assertEqual(quote_sha1("a  b"), quote_sha1("a b"))

    def test_a_different_quote_hashes_differently(self):
        self.assertNotEqual(quote_sha1("a b"), quote_sha1("a c"))


class VerbatimTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(file_name="x.pdf", rel_path="insights/x.pdf")
        DocumentText.objects.create(document=self.doc, page=7, text=PAGE_TEXT)

    def test_a_real_quote_is_found_across_line_breaks(self):
        quote = ("When it rains we get flash floods, and with the fighting around us "
                 "the hospitals are gone — we have cholera now and nowhere to take the sick.")
        self.assertTrue(quote_is_verbatim(self.doc.id, 7, quote))

    def test_an_invented_quote_is_not_found(self):
        self.assertFalse(quote_is_verbatim(
            self.doc.id, 7, "We were promised boreholes and nothing came."))

    def test_a_real_quote_on_the_wrong_page_is_not_found(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 3, "we have cholera now"))

    def test_a_missing_page_is_not_found_rather_than_an_error(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 99, "anything"))

    def test_an_empty_quote_is_never_verbatim(self):
        self.assertFalse(quote_is_verbatim(self.doc.id, 7, "   "))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_verify -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.verify'`

- [ ] **Step 3: Write the implementation**

Create `insights/verify.py`:

```python
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

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‚‛"), "'")
_QUOTES.update(dict.fromkeys(map(ord, "“”„‟"), '"'))


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
    """
    from data_track.models import DocumentText

    needle = normalise(quote)
    if not needle:
        return False

    row = DocumentText.objects.filter(document_id=document_id, page=page).first()
    if row is None or not row.text:
        return False
    return needle in normalise(row.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_verify -v 2`
Expected: 11 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add insights/verify.py insights/tests/test_verify.py
git commit -m "insights: reject any quote that is not in the page it claims

The only gate in this design that does not depend on which model produced the
payload, which is why it is the one that matters: it makes a local model as
safe to point at this as Claude. Normalisation absorbs how a PDF wraps a line
and nothing more - a changed word is what this exists to catch."
```

---

### Task 4: Place resolution against the boundary library

**Files:**
- Create: `insights/places.py`
- Create: `insights/tests/test_places.py`

**Interfaces:**
- Consumes: `boundaries.models.AdminArea` — fields `iso3`, `level`, `pcode`, `name`, `name_alt` (JSON list), `center_lat`, `center_lon`.
- Produces: `insights.places.resolve(iso3, place_name) -> dict` returning `{"admin_pcode", "admin_level", "match_method", "lat", "lon"}`. Tasks 6 and 8 call it.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_places.py`:

```python
"""Placing a statement, and being honest when we cannot.

Unmatched is a NORMAL outcome, not a failure: camps, informal settlements and
neighbourhoods are not in the boundary library and never will be. Those insights
stay off the map and keep their place name as the source wrote it.
"""
from django.test import TestCase

from boundaries.models import AdminArea, BoundarySource
from insights.places import resolve


class ResolveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        source = BoundarySource.objects.create(name="test", kind="test")
        AdminArea.objects.create(
            source=source, kind="admin", iso3="ETH", country_name="Ethiopia",
            level=1, pcode="ET02", name="Afar", name_alt=["Afar Region", "Afaar"],
            center_lat=11.75, center_lon=40.95,
        )
        AdminArea.objects.create(
            source=source, kind="admin", iso3="SDN", country_name="Sudan",
            level=1, pcode="SD08", name="North Darfur", name_alt=[],
            center_lat=15.5, center_lon=25.0,
        )

    def test_an_exact_name_matches_and_copies_the_label_point(self):
        self.assertEqual(resolve("ETH", "Afar"), {
            "admin_pcode": "ET02", "admin_level": 1, "match_method": "name",
            "lat": 11.75, "lon": 40.95,
        })

    def test_matching_ignores_case_and_spacing(self):
        self.assertEqual(resolve("SDN", "  north darfur ")["admin_pcode"], "SD08")

    def test_an_alternate_spelling_matches(self):
        self.assertEqual(resolve("ETH", "Afaar")["admin_pcode"], "ET02")

    def test_a_pcode_given_instead_of_a_name_matches_as_pcode(self):
        self.assertEqual(resolve("ETH", "ET02"), {
            "admin_pcode": "ET02", "admin_level": 1, "match_method": "pcode",
            "lat": 11.75, "lon": 40.95,
        })

    def test_an_unknown_place_is_unmatched_with_no_coordinates(self):
        self.assertEqual(resolve("ETH", "Kebribeyah camp"), {
            "admin_pcode": None, "admin_level": None, "match_method": "unmatched",
            "lat": None, "lon": None,
        })

    def test_the_right_name_in_the_wrong_country_does_not_match(self):
        self.assertEqual(resolve("SDN", "Afar")["match_method"], "unmatched")

    def test_no_place_name_is_unmatched(self):
        self.assertEqual(resolve("ETH", None)["match_method"], "unmatched")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_places -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.places'`

- [ ] **Step 3: Write the implementation**

Create `insights/places.py`:

```python
"""Turn 'Afar' plus 'ETH' into a polygon, or admit that we could not.

WHAT lat/lon MEAN HERE. They are copied from AdminArea.center_lat/center_lon, a
point guaranteed to be inside the polygon - a LABEL POSITION, not an address.
The dashboard popup says so. This is the same care HumanitarianServicePoint takes
in its own docstring about not reading its dots as building locations, and for
the same reason: the finest truthful placement the source supports.

`match_method` records how far we got - 'pcode', 'name' or 'unmatched' - because
"somewhere in Afar" and "we do not know where" are different findings and only
this column tells them apart afterwards.
"""
from boundaries.models import AdminArea

UNMATCHED = {"admin_pcode": None, "admin_level": None,
             "match_method": "unmatched", "lat": None, "lon": None}


def _key(text):
    return " ".join(str(text).strip().lower().split())


def _hit(area, method):
    return {
        "admin_pcode": area.pcode,
        "admin_level": area.level,
        "match_method": method,
        "lat": area.center_lat,
        "lon": area.center_lon,
    }


def resolve(iso3, place_name):
    """Best placement for a place named the way a source wrote it.

    Returns UNMATCHED rather than raising. An unplaced insight is a normal
    outcome: camps, settlements and neighbourhoods are not in the library.
    """
    if not place_name or not iso3:
        return dict(UNMATCHED)

    candidates = list(
        AdminArea.objects.filter(iso3=iso3, kind="admin")
        .only("pcode", "level", "name", "name_alt", "center_lat", "center_lon")
        .order_by("level")
    )
    if not candidates:
        return dict(UNMATCHED)

    wanted = _key(place_name)

    # A p-code is checked first: when a payload gives one it is a stronger claim
    # than a name, and it is the only match that cannot be a coincidence.
    for area in candidates:
        if _key(area.pcode) == wanted:
            return _hit(area, "pcode")

    for area in candidates:
        names = [area.name, *(area.name_alt or [])]
        if any(_key(n) == wanted for n in names if n):
            return _hit(area, "name")

    return dict(UNMATCHED)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_places -v 2`
Expected: 7 tests, all PASS.

If `BoundarySource` requires fields beyond `name`/`kind`, read `boundaries/models.py` and pass what it needs — do not change the model to suit the test.

- [ ] **Step 5: Commit**

```bash
git add insights/places.py insights/tests/test_places.py
git commit -m "insights: resolve a written place name against the boundary library

lat/lon are AdminArea.center_lat/lon - a label position inside the polygon, not
an address - and match_method records how far the match got, because 'somewhere
in Afar' and 'we do not know' are different findings.

Unmatched is a normal outcome. Camps and settlements are not in the library and
those insights simply stay off the map."
```

---

### Task 5: Payload contract validation

**Files:**
- Create: `insights/contract.py`
- Create: `insights/tests/test_contract.py`
- Create: `insights/tests/fixtures/payload_ok.json`, `insights/tests/fixtures/payload_bad.json`

**Interfaces:**
- Consumes: `insights.taxonomy.normalise_coding`.
- Produces: `insights.contract.ContractError` (exception) and `insights.contract.parse(payload: dict) -> list[dict]`, each dict having keys `quote, quote_language, page, voice_type, place_name_as_written, iso3, codings, people_affected, severity, confidence`. `codings` is a list of `{dimension, tag, tag_raw}`. Task 6 consumes this.

- [ ] **Step 1: Write the fixtures**

Create `insights/tests/fixtures/payload_ok.json`:

```json
{
  "source": {"rel_path": "insights/x.pdf", "sha1": "abc", "report_date": "2026-03-14"},
  "producer": {"agent": "claude-code", "model": "claude-opus-5"},
  "insights": [
    {
      "quote": "When it rains we get flash floods, and with the fighting around us the hospitals are gone — we have cholera now and nowhere to take the sick.",
      "quote_language": "en",
      "page": 7,
      "voice_type": "community",
      "place_name_as_written": "Afar",
      "iso3": "ETH",
      "codings": [
        {"dimension": "hazard", "tag": "flooding"},
        {"dimension": "hazard", "tag": "disease_outbreak"},
        {"dimension": "need", "tag": "health"},
        {"dimension": "need", "tag": "locusts"}
      ],
      "people_affected": null,
      "severity": 4,
      "confidence": "high"
    }
  ]
}
```

Create `insights/tests/fixtures/payload_bad.json`:

```json
{"producer": {"agent": "claude-code"}, "insights": []}
```

- [ ] **Step 2: Write the failing test**

Create `insights/tests/test_contract.py`:

```python
"""What a payload must contain, and what happens when it does not."""
import json
from pathlib import Path

from django.test import SimpleTestCase

from insights.contract import ContractError, parse

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ParseTests(SimpleTestCase):
    def test_a_good_payload_yields_one_row(self):
        rows = parse(load("payload_ok.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["iso3"], "ETH")
        self.assertEqual(rows[0]["page"], 7)
        self.assertEqual(rows[0]["severity"], 4)
        self.assertIsNone(rows[0]["people_affected"])

    def test_codings_are_normalised_through_the_taxonomy(self):
        codings = parse(load("payload_ok.json"))[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding", "tag_raw": None}, codings)
        self.assertIn({"dimension": "need", "tag": "other", "tag_raw": "locusts"}, codings)

    def test_an_empty_insight_list_is_an_error_not_a_success(self):
        """An MCP or LLM error serialised as [] looks exactly like this."""
        with self.assertRaises(ContractError):
            parse(load("payload_bad.json"))

    def test_a_missing_quote_is_an_error(self):
        payload = load("payload_ok.json")
        del payload["insights"][0]["quote"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_a_blank_quote_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["quote"] = "   "
        with self.assertRaises(ContractError):
            parse(payload)

    def test_a_missing_iso3_is_an_error(self):
        payload = load("payload_ok.json")
        del payload["insights"][0]["iso3"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_an_unknown_voice_type_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["voice_type"] = "hearsay"
        with self.assertRaises(ContractError):
            parse(payload)

    def test_an_unknown_dimension_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"] = [{"dimension": "vibes", "tag": "x"}]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_severity_outside_one_to_five_is_an_error(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["severity"] = 9
        with self.assertRaises(ContractError):
            parse(payload)

    def test_defaults_are_applied_for_optional_fields(self):
        payload = load("payload_ok.json")
        for key in ("quote_language", "people_affected", "severity", "confidence"):
            payload["insights"][0].pop(key, None)
        row = parse(payload)[0]
        self.assertEqual(row["quote_language"], "en")
        self.assertIsNone(row["people_affected"])
        self.assertIsNone(row["severity"])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_contract -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.contract'`

- [ ] **Step 4: Write the implementation**

Create `insights/contract.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_contract -v 2`
Expected: 10 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add insights/contract.py insights/tests/
git commit -m "insights: validate the payload contract before anything is opened

Pure, no database, so a malformed payload fails before a file is touched. An
empty insight list is an error rather than a quiet success - an LLM failure
serialised as [] looks exactly like a document with nothing to say, and
external_data's loader already refuses to conflate the two."
```

---

### Task 6: The loader, the conflict rule, and `load_insights`

**Files:**
- Create: `insights/loader.py`
- Create: `insights/management/__init__.py`, `insights/management/commands/__init__.py`, `insights/management/commands/load_insights.py`
- Create: `insights/tests/test_loader.py`

**Interfaces:**
- Consumes: `insights.contract.parse`, `insights.verify.quote_is_verbatim`, `insights.verify.quote_sha1`, `insights.places.resolve`, all four models.
- Produces: `insights.loader.load(payload, document, job=None, method="llm", model_used=None) -> LoadReport`, where `LoadReport` is a dataclass with `written, rejected_unverifiable, skipped_reviewed`. Task 8 (Admin action) calls it.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_loader.py`:

```python
"""The four gates, and the one rule that protects a reviewer.

Gate 4 is where this loader deliberately parts company with
external_data/loaders/base.py. That one overwrites on conflict, which is right
for API data and wrong here: it would discard a reviewer's corrections on every
re-run.
"""
import json
from pathlib import Path

from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.loader import load
from insights.models import ExtractionJob, Insight

FIXTURES = Path(__file__).parent / "fixtures"
QUOTE = ("When it rains we get flash floods, and with the fighting around us the "
         "hospitals are gone — we have cholera now and nowhere to take the sick.")


class LoaderTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="x.pdf", rel_path="insights/x.pdf", report_date="2026-03-14")
        DocumentText.objects.create(document=self.doc, page=7, text=f"Participants said: “{QUOTE}”")
        self.payload = json.loads((FIXTURES / "payload_ok.json").read_text(encoding="utf-8"))

    def test_a_verifiable_insight_is_written_as_pending(self):
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        row = Insight.objects.get()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.document_id, self.doc.id)
        self.assertEqual(row.page, 7)
        self.assertEqual(row.stated_on.isoformat(), "2026-03-14")

    def test_the_codings_are_written(self):
        load(self.payload, self.doc)
        codings = set(Insight.objects.get().codings.values_list("dimension", "tag"))
        self.assertIn(("hazard", "flooding"), codings)
        self.assertIn(("need", "other"), codings)

    def test_an_invented_quote_is_rejected_and_counted(self):
        self.payload["insights"][0]["quote"] = "We were promised boreholes and none came."
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 0)
        self.assertEqual(report.rejected_unverifiable, 1)
        self.assertEqual(Insight.objects.count(), 0)

    def test_loading_twice_writes_one_row(self):
        load(self.payload, self.doc)
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.count(), 1)

    def test_a_pending_row_is_updated_by_a_rerun(self):
        """The loader still owns a row no human has touched."""
        load(self.payload, self.doc)
        self.payload["insights"][0]["severity"] = 2
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.get().severity, 2)

    def test_a_published_row_is_never_overwritten(self):
        load(self.payload, self.doc)
        Insight.objects.update(status="published", severity=5)
        self.payload["insights"][0]["severity"] = 1
        report = load(self.payload, self.doc)
        self.assertEqual(report.skipped_reviewed, 1)
        row = Insight.objects.get()
        self.assertEqual(row.severity, 5)
        self.assertEqual(row.status, "published")

    def test_the_place_is_resolved_or_left_unmatched(self):
        load(self.payload, self.doc)
        self.assertEqual(Insight.objects.get().match_method, "unmatched")

    def test_job_counters_are_written(self):
        job = ExtractionJob.objects.create(producer="external")
        self.payload["insights"].append(dict(self.payload["insights"][0],
                                             quote="An invented sentence."))
        load(self.payload, self.doc, job=job)
        job.refresh_from_db()
        self.assertEqual(job.insights_proposed, 2)
        self.assertEqual(job.insights_rejected_unverifiable, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_loader -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.loader'`

- [ ] **Step 3: Write the loader**

Create `insights/loader.py`:

```python
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

from django.db import transaction

from insights import places
from insights.contract import parse
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
```

- [ ] **Step 4: Write the management command**

Create `insights/management/__init__.py` and `insights/management/commands/__init__.py` (both empty), then `insights/management/commands/load_insights.py`:

```python
"""Load one payload file, or every payload in mcp_cache/insights/.

    manage.py load_insights                       # everything not yet loaded
    manage.py load_insights path/to/one.json      # just this one
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from data_track.models import Document
from insights.contract import ContractError
from insights.loader import load
from insights.models import ExtractionJob


def payload_dir():
    return Path(settings.MCP_CACHE_DIR) / "insights"


class Command(BaseCommand):
    help = "Load community-insight payloads written by an extraction agent."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="One payload file. Default: all of them.")
        parser.add_argument("--job", type=int, help="Attribute the load to this ExtractionJob.")

    def handle(self, *args, **options):
        if options["path"]:
            files = [Path(options["path"])]
        else:
            files = sorted(payload_dir().glob("*.json"))
        if not files:
            raise CommandError(f"no payloads found in {payload_dir()}")

        job = ExtractionJob.objects.filter(id=options["job"]).first() if options["job"] else None

        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rel = (payload.get("source") or {}).get("rel_path")
            document = Document.objects.filter(rel_path=rel).first() if rel else None
            if rel and document is None:
                self.stderr.write(f"{path.name}: no document with rel_path {rel!r}; skipped")
                continue
            try:
                report = load(payload, document, job=job)
            except ContractError as exc:
                self.stderr.write(f"{path.name}: {exc}")
                continue
            self.stdout.write(
                f"{path.name}: {report.written} written, "
                f"{report.rejected_unverifiable} unverifiable, "
                f"{report.skipped_reviewed} already reviewed"
            )

        if job is not None:
            job.status = "loaded"
            job.save(update_fields=["status"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: all tests from Tasks 1–6 PASS.

- [ ] **Step 6: Commit**

```bash
git add insights/loader.py insights/management insights/tests/test_loader.py
git commit -m "insights: the four gates, and never overwrite a reviewer

Gate 4 is where this parts company with external_data's loader. That one
upserts on conflict, which is right for API data and wrong here - a re-run
would discard every correction a reviewer had made. A pending row is still
the loader's to replace; anything else is a person's.

Gate 1 applies only where there is a document to check against. A manual
statement has none, and the human who typed it is the guarantee."
```

---

### Task 7: Intake — folders and uploads become documents

**Files:**
- Create: `insights/intake.py`
- Create: `insights/tests/test_intake.py`
- Modify: `config/settings.py` (add `MEDIA_ROOT` / `MEDIA_URL` beside `DASHBOARD_DATA_DIR`)

**Interfaces:**
- Consumes: `insights.models.InsightFolder`, `ExtractionJob`; `data_track.models.Document`, `DocumentText`.
- Produces: `insights.intake.catalogue_file(path, iso3=None, report_date=None) -> Document` and `insights.intake.catalogue_folder(folder) -> ExtractionJob`. Task 8 calls both.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_intake.py`:

```python
"""Getting a document in, and staying out of the pipeline's way.

The pipeline-invisibility test is the important one. s02_extract_text selects
documents that have NO page rows; because intake writes DocumentText itself,
these documents are never selected, so s02 never tries to reopen a file at a
path it cannot resolve.
"""
import tempfile
from pathlib import Path

import fitz
from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.intake import catalogue_file, catalogue_folder
from insights.models import InsightFolder


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


class CatalogueFileTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_pdf_becomes_a_document_with_its_pages(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["First page words.", "Second page words."])
        document = catalogue_file(pdf, iso3="TCD", report_date="2026-03-14")
        self.assertEqual(document.file_name, "assessment.pdf")
        self.assertEqual(document.source_collection, "insights")
        self.assertEqual(document.family, "insight_source")
        self.assertEqual(document.date_source, "intake")
        self.assertEqual(document.texts.count(), 2)
        self.assertIn("First page", DocumentText.objects.get(document=document, page=1).text)

    def test_the_same_file_is_not_catalogued_twice(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words."])
        first = catalogue_file(pdf)
        second = catalogue_file(pdf)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Document.objects.count(), 1)

    def test_a_sha1_and_page_count_are_recorded(self):
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words.", "More."])
        document = catalogue_file(pdf)
        self.assertEqual(len(document.sha1), 40)
        self.assertEqual(document.pages, 2)

    def test_the_pipeline_will_not_select_it_for_text_extraction(self):
        """s02 selects documents with no page rows. These have them already."""
        pdf = self.dir / "assessment.pdf"
        write_pdf(pdf, ["Words."])
        catalogue_file(pdf)
        self.assertEqual(Document.objects.filter(texts__isnull=True).count(), 0)


class CatalogueFolderTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_every_pdf_in_the_folder_is_catalogued_and_a_job_opened(self):
        for name in ("a.pdf", "b.pdf"):
            write_pdf(self.dir / name, ["Words."])
        (self.dir / "notes.txt").write_text("ignored")
        folder = InsightFolder.objects.create(
            label="test", path=str(self.dir), default_iso3="TCD")
        job = catalogue_folder(folder)
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(job.documents_total, 2)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.folder_id, folder.id)

    def test_an_unreachable_path_raises_rather_than_opening_an_empty_job(self):
        folder = InsightFolder.objects.create(label="gone", path="/nowhere/at/all")
        with self.assertRaises(FileNotFoundError):
            catalogue_folder(folder)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_intake -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.intake'`

- [ ] **Step 3: Add the media settings**

In `config/settings.py`, immediately after the `DASHBOARD_DATA_DIR` line, add:

```python
# Documents uploaded through the insights intake screen. Inside /app because
# /work is mounted read-only - see docker-compose.yml, mount 1.
MEDIA_ROOT = env_path("MEDIA_ROOT", BASE_DIR / "media")
MEDIA_URL = "/media/"
```

- [ ] **Step 4: Write the implementation**

Create `insights/intake.py`:

```python
"""Turn a file on disk into a Document plus its page text.

WHY THIS DOES NOT COLLIDE WITH THE PIPELINE (spec §7.2), all verified:

  s01_catalog  walks only SOURCE_COLLECTIONS and never deletes, so it neither
               sees nor removes these documents.
  s02_extract  selects Document.objects.filter(texts__isnull=True). Because we
               write DocumentText here, these are never selected - so s02 never
               tries to reopen a file at a path it cannot resolve.
  s03_parse    dispatches its positional parsers on `family` alone (811/813/817).
               'insight_source' matches none of them. Its taxonomy tagger does run
               over every document with text, so these get regex-tagged into
               narrative_tags like any other - which is harmless: those tags are
               analyst voice, they live in a table rebuilt on every run, and they
               never touch `insights`.

rel_path is relative to SOURCE_ROOT when the file is under it, so it resolves
exactly as a UNHCR PDF's does; otherwise it is 'media/<name>'. It is unique
either way, which is what s01 matches on.
"""
import hashlib
from pathlib import Path

import fitz
from django.conf import settings

from data_track.models import Document, DocumentText
from insights.models import ExtractionJob

SUFFIXES = {".pdf", ".docx"}


def sha1_of(path, chunk=1 << 20):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path):
    """Relative to SOURCE_ROOT when it is under it; 'media/<name>' otherwise."""
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(settings.SOURCE_ROOT).resolve()).as_posix()
    except ValueError:
        return f"media/{path.name}"


def _pages_of(path):
    """[(page_number, text)] - PyMuPDF for PDF, python-docx for DOCX."""
    if path.suffix.lower() == ".docx":
        from docx import Document as Docx
        # A DOCX has no pages until it is rendered, so the whole body is page 1.
        # Saying so here is cheaper than someone later reading page 1 as "the
        # first page of the printed document".
        body = "\n".join(p.text for p in Docx(str(path)).paragraphs)
        return [(1, body)]

    with fitz.open(str(path)) as pdf:
        return [(n + 1, pdf[n].get_text("text")) for n in range(len(pdf))]


def catalogue_file(path, iso3=None, report_date=None):
    """Create the Document and its page rows. Returns the existing one if known."""
    path = Path(path)
    rel = relative_path(path)

    existing = Document.objects.filter(rel_path=rel).first()
    if existing is not None:
        return existing

    pages = _pages_of(path)
    document = Document.objects.create(
        file_name=path.name,
        rel_path=rel,
        source_collection="insights",
        family="insight_source",
        country_focus=iso3,
        report_date=report_date or None,
        date_source="intake",
        pages=len(pages),
        file_size=path.stat().st_size,
        sha1=sha1_of(path),
    )
    DocumentText.objects.bulk_create(
        [DocumentText(document=document, page=number, text=text) for number, text in pages]
    )
    return document


def catalogue_folder(folder):
    """Catalogue everything in a registered folder and open a job for it."""
    root = Path(folder.path)
    if not root.is_dir():
        raise FileNotFoundError(
            f"{folder.path} is not a directory inside this container. Folders must "
            f"live under a mounted path - /work covers the whole SUDAN Ops folder."
        )

    pattern = "**/*" if folder.recursive else "*"
    files = sorted(p for p in root.glob(pattern) if p.suffix.lower() in SUFFIXES)

    job = ExtractionJob.objects.create(folder=folder, producer="external", status="queued")
    for path in files:
        catalogue_file(path, iso3=folder.default_iso3)
    job.documents_total = len(files)
    job.save(update_fields=["documents_total"])
    return job
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_intake -v 2`
Expected: 6 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add insights/intake.py insights/tests/test_intake.py config/settings.py
git commit -m "insights: catalogue a folder or an upload without touching the pipeline

Intake writes DocumentText itself, which is what keeps these documents
invisible to s02 - it only ever selects documents with no page rows, so it
never tries to reopen a file at a path it cannot resolve. family is
'insight_source', which matches none of s03's positional parsers.

MEDIA_ROOT lives under /app because /work is mounted read-only."
```

---

### Task 8: Django Admin — the review queue and the form

**Files:**
- Create: `insights/admin.py`
- Create: `insights/tests/test_admin.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: registered `ModelAdmin`s and three admin actions: `publish_selected`, `reject_selected`, `load_payloads_for_job`. No later task imports from here.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_admin.py`:

```python
"""What Admin must guarantee: nothing publishes itself, and a quote cannot be
quietly rewritten.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from data_track.models import Document, DocumentText
from insights.models import Insight
from insights.verify import quote_sha1

QUOTE = "We have cholera now and nowhere to take the sick."


class AdminReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.doc = Document.objects.create(file_name="x.pdf", rel_path="insights/x.pdf")
        DocumentText.objects.create(document=self.doc, page=1, text=f"They said: {QUOTE}")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), document=self.doc, page=1,
            voice_type="community", channel="document_ai", stated_on="2026-03-14",
            iso3="ETH", method="llm", status="pending",
        )

    def test_the_changelist_loads(self):
        response = self.client.get(reverse("admin:insights_insight_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_publishing_records_who_and_when(self):
        self.client.post(reverse("admin:insights_insight_changelist"), {
            "action": "publish_selected",
            "_selected_action": [str(self.insight.id)],
        }, follow=True)
        self.insight.refresh_from_db()
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertIsNotNone(self.insight.reviewed_at)

    def test_editing_the_quote_recomputes_the_fingerprint(self):
        self.insight.quote = "We have cholera now and nowhere to take the sick!"
        self.insight.save()
        self.assertEqual(self.insight.quote_sha1, quote_sha1(self.insight.quote))

    def test_a_manual_insight_saves_without_a_document(self):
        row = Insight.objects.create(
            quote="A statement relayed by the field team.",
            quote_sha1=quote_sha1("A statement relayed by the field team."),
            voice_type="community", channel="manual", stated_on="2026-04-01",
            iso3="TCD", method="manual", status="published",
        )
        self.assertIsNone(row.document_id)
        self.assertEqual(row.status, "published")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_admin -v 2`
Expected: FAIL — `NoReverseMatch: 'insights_insight_changelist' is not a registered namespace`

- [ ] **Step 3: Recompute the fingerprint on save**

In `insights/models.py`, add to `Insight` (immediately before `__str__`):

```python
    def save(self, *args, **kwargs):
        # The fingerprint is part of the natural key, so it must follow the quote.
        # Editing a quote in Admin is allowed only to repair an OCR artefact; this
        # keeps the key honest when that happens.
        from insights.verify import quote_sha1 as _sha1
        self.quote_sha1 = _sha1(self.quote)
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Write the admin**

Create `insights/admin.py`:

```python
"""The review queue, and the form for typing one in by hand.

They are the same screen deliberately: once saved, a reviewed AI insight and a
hand-keyed one should be indistinguishable, because they are.

The reviewer reads the quote FIRST - it is the top fieldset, alone - and only
then sees what the model made of it. That ordering is the whole point of the
screen, so do not fold it into a general "details" block.
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from data_track.models import Document
from insights.contract import ContractError
from insights.intake import catalogue_folder
from insights.loader import load
from insights.models import ExtractionJob, Insight, InsightCoding, InsightFolder


class InsightCodingInline(admin.TabularInline):
    model = InsightCoding
    extra = 1
    fields = ("dimension", "tag", "tag_raw")
    readonly_fields = ("tag_raw",)


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    inlines = [InsightCodingInline]
    list_display = ("opening", "iso3", "place_name_as_written", "voice_type",
                    "themes", "status", "stated_on", "method")
    list_filter = ("status", "voice_type", "channel", "method", "iso3", "match_method", "job")
    search_fields = ("quote", "quote_translated", "place_name_as_written")
    date_hierarchy = "stated_on"
    actions = ["publish_selected", "reject_selected"]
    readonly_fields = ("quote_sha1", "source_link", "reviewed_by", "reviewed_at", "created_at")
    fieldsets = (
        ("The statement", {
            "fields": ("quote", "quote_language", "quote_translated"),
            "description": "Read this first. Edit only to repair an OCR artefact.",
        }),
        ("What it is", {"fields": ("voice_type", "channel", "stated_on")}),
        ("Where", {"fields": ("iso3", "place_name_as_written", "admin_pcode",
                              "admin_level", "match_method", "lat", "lon")}),
        ("Scale (usually blank)", {"fields": ("people_affected", "severity")}),
        ("Source", {"fields": ("source_link", "document", "page")}),
        ("Provenance", {"fields": ("method", "model_used", "confidence", "job",
                                   "quote_sha1", "created_at")}),
        ("Review", {"fields": ("status", "rejection_reason", "reviewed_by", "reviewed_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("document").prefetch_related("codings")

    @admin.display(description="Statement")
    def opening(self, obj):
        return obj.quote[:90] + ("…" if len(obj.quote) > 90 else "")

    @admin.display(description="Themes")
    def themes(self, obj):
        return ", ".join(f"{c.dimension}:{c.tag}" for c in obj.codings.all()) or "—"

    @admin.display(description="Document")
    def source_link(self, obj):
        if not obj.document_id:
            return "— typed by hand, no source document"
        return format_html("{} (page {})", obj.document.file_name, obj.page or "?")

    @admin.action(description="Publish selected insights")
    def publish_selected(self, request, queryset):
        updated = queryset.update(
            status="published", reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f"{updated} published.", messages.SUCCESS)

    @admin.action(description="Reject selected insights")
    def reject_selected(self, request, queryset):
        updated = queryset.update(
            status="rejected", reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(
            request,
            f"{updated} rejected. Add a reason on each one - a rejected extraction is "
            f"evidence about the model, not rubbish.",
            messages.WARNING,
        )


@admin.register(InsightFolder)
class InsightFolderAdmin(admin.ModelAdmin):
    list_display = ("label", "path", "default_iso3", "reachable", "recursive")
    actions = ["catalogue_selected"]

    @admin.display(boolean=True, description="Reachable")
    def reachable(self, obj):
        return Path(obj.path).is_dir()

    @admin.action(description="Catalogue and queue for extraction")
    def catalogue_selected(self, request, queryset):
        for folder in queryset:
            try:
                job = catalogue_folder(folder)
            except FileNotFoundError as exc:
                self.message_user(request, str(exc), messages.ERROR)
                continue
            self.message_user(
                request,
                f"{folder.label}: {job.documents_total} documents catalogued, job {job.id} queued. "
                f"Run your extraction agent, then use 'Load payloads' on the job.",
                messages.SUCCESS,
            )


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = ("id", "folder", "producer", "status", "documents_total",
                    "insights_proposed", "insights_rejected_unverifiable",
                    "insights_skipped_reviewed")
    list_filter = ("status", "producer")
    readonly_fields = ("insights_proposed", "insights_rejected_unverifiable",
                       "insights_skipped_reviewed", "log", "started_at", "finished_at")
    actions = ["load_payloads_for_job"]

    @admin.action(description="Load payloads written by the agent")
    def load_payloads_for_job(self, request, queryset):
        folder = Path(settings.MCP_CACHE_DIR) / "insights"
        files = sorted(folder.glob("*.json"))
        if not files:
            self.message_user(request, f"No payloads in {folder}.", messages.WARNING)
            return

        for job in queryset:
            for path in files:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rel = (payload.get("source") or {}).get("rel_path")
                document = Document.objects.filter(rel_path=rel).first() if rel else None
                if rel and document is None:
                    self.message_user(
                        request, f"{path.name}: no document with rel_path {rel!r}.",
                        messages.ERROR)
                    continue
                try:
                    report = load(payload, document, job=job)
                except ContractError as exc:
                    self.message_user(request, f"{path.name}: {exc}", messages.ERROR)
                    continue
                self.message_user(
                    request,
                    f"{path.name}: {report.written} pending, "
                    f"{report.rejected_unverifiable} unverifiable, "
                    f"{report.skipped_reviewed} already reviewed.",
                    messages.SUCCESS,
                )
            job.status = "loaded"
            job.save(update_fields=["status"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: all tests from Tasks 1–8 PASS.

- [ ] **Step 6: Commit**

```bash
git add insights/admin.py insights/models.py insights/tests/test_admin.py
git commit -m "insights: the review queue and the manual form, one screen

The quote is its own fieldset at the top so a reviewer reads the words before
seeing what the model made of them. voice_type is prominent because it is the
field a model gets wrong most often and the one the dashboard tabs depend on.

Editing a quote recomputes quote_sha1, which is part of the natural key - so
what a community said cannot be quietly rewritten out from under the key."
```

---

### Task 9: The `/api/insights/` endpoint

**Files:**
- Create: `insights/views.py`, `insights/urls.py`
- Create: `insights/tests/test_api.py`
- Modify: `config/urls.py` (mount before `data_track`'s catch-all, and update the module docstring)

**Interfaces:**
- Consumes: `insights.models.Insight`.
- Produces: `GET /api/insights/` returning `{"count": int, "results": [...]}`. Task 11 fetches it.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_api.py`:

```python
"""Only published rows leave the building."""
from django.test import TestCase

from insights.models import Insight, InsightCoding
from insights.verify import quote_sha1


def make(quote, **kwargs):
    defaults = dict(
        quote=quote, quote_sha1=quote_sha1(quote), voice_type="community",
        channel="manual", stated_on="2026-03-14", iso3="ETH", method="manual",
        status="published",
    )
    defaults.update(kwargs)
    return Insight.objects.create(**defaults)


class InsightApiTests(TestCase):
    def setUp(self):
        self.published = make("We have cholera and no clinic.", lat=11.75, lon=40.95,
                              admin_pcode="ET02", match_method="name",
                              place_name_as_written="Afar")
        InsightCoding.objects.create(insight=self.published, dimension="hazard",
                                     tag="disease_outbreak")
        make("A pending statement.", status="pending")
        make("An analyst passage.", voice_type="secondary_analysis", iso3="SDN")

    def get(self, query=""):
        return self.client.get(f"/api/insights/{query}").json()

    def test_only_published_rows_are_returned(self):
        body = self.get()
        quotes = [row["quote"] for row in body["results"]]
        self.assertIn("We have cholera and no clinic.", quotes)
        self.assertNotIn("A pending statement.", quotes)

    def test_codings_travel_with_the_row(self):
        row = next(r for r in self.get()["results"] if r["quote"].startswith("We have"))
        self.assertEqual(row["codings"], [{"dimension": "hazard", "tag": "disease_outbreak"}])

    def test_placement_is_reported_honestly(self):
        row = next(r for r in self.get()["results"] if r["quote"].startswith("We have"))
        self.assertEqual(row["match_method"], "name")
        self.assertEqual(row["lat"], 11.75)

    def test_filtering_by_voice_type(self):
        body = self.get("?voice_type=community")
        self.assertTrue(all(r["voice_type"] == "community" for r in body["results"]))

    def test_filtering_by_country(self):
        self.assertEqual(len(self.get("?iso3=SDN")["results"]), 1)

    def test_filtering_by_tag(self):
        self.assertEqual(len(self.get("?tag=disease_outbreak")["results"]), 1)

    def test_free_text_search(self):
        self.assertEqual(len(self.get("?q=cholera")["results"]), 1)

    def test_the_count_reflects_the_filter(self):
        self.assertEqual(self.get("?iso3=SDN")["count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_api -v 2`
Expected: FAIL — the response is a 404, so `.json()` raises.

- [ ] **Step 3: Write the view**

Create `insights/views.py`:

```python
"""The one panel that reads PostgreSQL live.

Quotes are low-volume text, so serving them live costs nothing and lets Publish
mean published: refresh the page and it is there. The map's own layers keep
reading their pre-built files, so nothing about map performance changes - see
spec §14.1 for why geometry stays on files.

PUBLISHED ROWS ONLY. There is no query parameter that will return a pending or
rejected insight, and there should never be one.
"""
from django.db.models import Q
from django.http import JsonResponse

from insights.models import Insight

MAX_LIMIT = 2000


def _limit(request):
    try:
        return max(1, min(int(request.GET.get("limit", 500)), MAX_LIMIT))
    except (TypeError, ValueError):
        return 500


def insights(request):
    """Published community insights. Filters: ?voice_type= &iso3= &dimension=
    &tag= &admin_pcode= &from= &to= &q=
    """
    rows = (Insight.objects.filter(status="published")
            .select_related("document").prefetch_related("codings"))

    for field in ("voice_type", "iso3", "admin_pcode"):
        if value := request.GET.get(field):
            rows = rows.filter(**{field: value})
    if dimension := request.GET.get("dimension"):
        rows = rows.filter(codings__dimension=dimension)
    if tag := request.GET.get("tag"):
        rows = rows.filter(codings__tag=tag)
    if start := request.GET.get("from"):
        rows = rows.filter(stated_on__gte=start)
    if end := request.GET.get("to"):
        rows = rows.filter(stated_on__lte=end)
    if q := request.GET.get("q"):
        rows = rows.filter(
            Q(quote__icontains=q)
            | Q(quote_translated__icontains=q)
            | Q(place_name_as_written__icontains=q)
        )

    rows = rows.distinct()
    total = rows.count()

    data = [
        {
            "id": row.id,
            "quote": row.quote,
            "quote_language": row.quote_language,
            "quote_translated": row.quote_translated,
            "voice_type": row.voice_type,
            "channel": row.channel,
            "date": row.stated_on.isoformat() if row.stated_on else None,
            "iso3": row.iso3,
            "place_name": row.place_name_as_written,
            "admin_pcode": row.admin_pcode,
            "admin_level": row.admin_level,
            "match_method": row.match_method,
            "lat": row.lat,
            "lon": row.lon,
            "people_affected": row.people_affected,
            "severity": row.severity,
            "codings": [{"dimension": c.dimension, "tag": c.tag} for c in row.codings.all()],
            "source_document": row.document.file_name if row.document_id else None,
            "page": row.page,
        }
        for row in rows.order_by("-stated_on", "id")[: _limit(request)]
    ]
    return JsonResponse({"count": total, "results": data})
```

Create `insights/urls.py`:

```python
from django.urls import path

from insights import views

urlpatterns = [
    path("insights/", views.insights, name="insights-list"),
]
```

- [ ] **Step 4: Mount it**

In `config/urls.py`, add the include **before** the `data_track` catch-all, matching the existing comment style:

```python
    # Same reason: insights owns a specific path under api/, so it is matched
    # before data_track's catch-all include.
    path("api/", include("insights.urls")),
    path("api/", include("data_track.urls")),
```

And add a line to the module docstring's address list, after the `/api/...` line:

```
  /api/insights/    -> published community statements, read live       insights app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_api -v 2`
Expected: 8 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add insights/views.py insights/urls.py insights/tests/test_api.py config/urls.py
git commit -m "insights: serve published statements live at /api/insights/

Quotes are low-volume text, so a live read costs nothing and lets Publish mean
published. The map layers keep their pre-built files; geometry is why those
stay files.

Published rows only, with no parameter that can return a pending one."
```

---

### Task 10: The prompt file, CLAUDE.md and AGENTS.md

**Files:**
- Create: `insights/prompts/extract_insights.md`
- Create: `CLAUDE.md` (repo root), `AGENTS.md` (repo root)

**Interfaces:**
- Consumes: the contract from Task 5 — this file must describe exactly the JSON `insights.contract.parse` accepts.
- Produces: the instructions every producer reads. Task 13's adapters load `insights/prompts/extract_insights.md` at runtime.

- [ ] **Step 1: Write the prompt file**

Create `insights/prompts/extract_insights.md`:

````markdown
# Extracting community insights from a document

You are reading humanitarian documents to find **what communities themselves said**.

## What to extract

A **community insight** is a statement about a community's situation, quoted
**verbatim** from the document. Two kinds count, and you must label which:

- `community` — the document is reporting what people said: a quote, a focus-group
  or key-informant finding, a participatory assessment, a perception survey result.
- `secondary_analysis` — an analyst's own description of a community's hazards,
  needs or vulnerabilities.

**Most sitreps contain no community voice at all. Returning only
`secondary_analysis` passages, or a short list, is the correct answer for such a
document. Do not pad.**

## The rules that matter

1. **Quote verbatim.** Copy the sentence exactly as printed, including its
   punctuation. Do not paraphrase, tidy, translate or join two separate passages.
   Every quote is checked against the stored page text and a quote that does not
   match is discarded.
2. **Give the page number the quote is printed on.**
3. **Never invent a number.** Leave `people_affected` null unless the passage
   states a figure. Most do not.
4. **Keep the original language.** Set `quote_language` (`en`, `fr`, `ar`). Do not
   translate.
5. **Name the place as the document writes it** in `place_name_as_written`. Do not
   convert it to a p-code and do not guess a finer location than the text gives.

## Codings

Each insight carries the themes read out of it. `dimension` must be one of
`hazard`, `vulnerability`, `need`, `coping`, `movement_pattern`. `tag` should be a
key from `data_pipeline/taxonomy.json` under that dimension — read that file. If
nothing fits, put your own words in `tag` anyway: it will be recorded as `other`
with your suggestion kept for a reviewer, which is how the vocabulary grows.

## Output

Write one JSON file per document to `data_pipeline/mcp_cache/insights/<stem>.json`:

```json
{
  "source": {"rel_path": "<as in the documents table>", "sha1": "…", "report_date": "YYYY-MM-DD"},
  "producer": {"agent": "claude-code", "model": "claude-opus-5"},
  "insights": [
    {
      "quote": "…verbatim…",
      "quote_language": "en",
      "page": 7,
      "voice_type": "community",
      "place_name_as_written": "Afar",
      "iso3": "ETH",
      "codings": [
        {"dimension": "hazard", "tag": "flooding"},
        {"dimension": "need", "tag": "health"}
      ],
      "people_affected": null,
      "severity": 4,
      "confidence": "high"
    }
  ]
}
```

`severity` is 1–5 on the same scale the events timeline uses, or null.
`confidence` is `high`, `medium` or `low`.

**An empty `insights` list is rejected as a failed run.** If a document genuinely
holds nothing, do not write a file for it.

Then, in Django Admin, open the extraction job and run **Load payloads**.
````

- [ ] **Step 2: Write CLAUDE.md**

Create `CLAUDE.md` at the repo root:

```markdown
# Working in this repository

The Community Centered Humanitarian Analysis Platform: a Django + PostGIS
application that reads humanitarian documents and APIs into a database and draws
the result on a MapLibre dashboard.

Everything runs in Docker. There is no Django environment on the host:

    docker compose exec web python manage.py <command>
    docker compose exec web python manage.py test <app> -v 2

## The two jobs an agent does here

### 1. Pull external data through the MCP servers

`.mcp.json` in this folder configures five humanitarian MCP servers — `hdx`,
`fewsnet`, `ifrc-go`, `unhcr-refugees`, `ipc`. Claude Code reads it
automatically; nothing else needs configuring.

The rule is **fetch, save, then load** — never fetch straight into the database:

1. Check what is already held: `manage.py external_status`.
2. Call the MCP tool for what is missing or newer.
3. Save the raw response under `data_pipeline/mcp_cache/`.
4. Load it: `manage.py load_external <dataset> <path> --iso3 <ISO3>`.

Loaders live in `external_data/loaders/`; `external_data/loaders/base.py` states
the four guarantees each one keeps.

**Never pull two IPC countries in parallel.** Recorded incident: the connection
closed and the server stayed down for the rest of the session.

### 2. Extract community insights from documents

Read `insights/prompts/extract_insights.md` and follow it exactly. That file is
the single source of truth for the extraction and its output format; this section
does not restate it.

## Things worth knowing before changing anything

- `/work` is mounted **read-only**. Anything written goes under `/app`.
- `data_pipeline/steps/s03_parse.py` deletes and rebuilds `population_figures`,
  `movement_flows` and `narrative_tags` on every run, and `s04_events.py` deletes
  every row in `events`. Do not put hand-curated data in those tables.
- The `insights` app is never written to by any pipeline step. That is deliberate.
- Settings read `os.environ.get(X) or default`, never `get(X, default)`.
- Specs are in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`.
```

- [ ] **Step 3: Point AGENTS.md at the same file**

Create `AGENTS.md` at the repo root:

```markdown
# Agent instructions

This repository's instructions live in [CLAUDE.md](CLAUDE.md). They are
tool-agnostic — read that file.

For extracting community insights specifically, read
[insights/prompts/extract_insights.md](insights/prompts/extract_insights.md),
which is the single source of truth for that task and its output format.
```

- [ ] **Step 4: Verify the prompt matches the contract**

Run: `docker compose exec web python manage.py test insights.tests.test_contract -v 2`
Expected: PASS. Then read `insights/prompts/extract_insights.md` beside
`insights/contract.py` and confirm every field named in one appears in the other.
Fix the prompt, not the contract, if they disagree.

- [ ] **Step 5: Commit**

```bash
git add insights/prompts CLAUDE.md AGENTS.md
git commit -m "insights: the prompt file, and the repo's first CLAUDE.md

.mcp.json never needed changing - Claude Code and Codex both read it already.
What was missing was an instructions file telling an agent what to do here,
which this repository has never had.

The prompt file is the single source of truth for extraction: CLAUDE.md and
AGENTS.md point at it rather than restating it, so there is one place to edit
when the extraction changes."
```

---

### Task 11: Dashboard — three tabs and tab-scoped search

**Files:**
- Modify: `dashboard/templates/dashboard/index.html:203-210`
- Modify: `dashboard/static/dashboard/js/app.js` (state at ~151-157, `allVoices` ~1693, `renderVoices` ~1720, `initVoiceSearch` ~2808, `loadData` ~548)
- Modify: `dashboard/static/dashboard/css/app.css`

**Interfaces:**
- Consumes: `GET /api/insights/` from Task 9.
- Produces: `state.data.insights` (array of API rows), `state.voiceTab` (`"community" | "analyst" | "both"`), and `allVoices()` returning rows shaped `{dim, tag, mk, text, voice, full, place, date, source, lat, lon, id}`. Task 12 reads `allVoices()` and `state.voiceTab`.

- [ ] **Step 1: Add the tab markup**

In `dashboard/templates/dashboard/index.html`, replace lines 203–210 with:

```html
    <section class="panel" id="voices-panel">
      <h2>Community Insights <span id="voice-count" class="panel-count"></span></h2>
      <div class="voice-tabs" role="tablist">
        <button class="voice-tab is-active" data-tab="community" role="tab">Community</button>
        <button class="voice-tab" data-tab="analyst" role="tab">Analyst</button>
        <button class="voice-tab" data-tab="both" role="tab">Both</button>
      </div>
      <label class="sr-only" for="voice-search">Search community quotes</label>
      <input type="search" id="voice-search" placeholder="Search the selected tab…"
             autocomplete="off">
      <div id="voices"></div>
    </section>
```

- [ ] **Step 2: Style the tabs**

Append to `dashboard/static/dashboard/css/app.css`:

```css
/* Community Insights: three tabs over one list. The active tab decides both
   what is listed and what the search box searches. */
.voice-tabs { display: flex; gap: 2px; margin: 6px 0; }
.voice-tab {
  flex: 1; padding: 4px 6px; font-size: 11px; cursor: pointer;
  border: 1px solid var(--line); background: transparent; color: var(--ink-dim);
}
.voice-tab.is-active { background: var(--ink); color: var(--bg); font-weight: 600; }
.voice .v-voice {
  font-size: 10px; text-transform: uppercase; letter-spacing: .04em; opacity: .65;
}
.voice.is-community { border-left-width: 3px; }
.voice .v-full { white-space: pre-wrap; }
.voice .v-translated { opacity: .75; font-style: italic; margin-top: 4px; }
.voices-unmapped { font-size: 11px; opacity: .7; margin-top: 6px; }
```

If `--line`, `--ink`, `--ink-dim` or `--bg` are not the names this stylesheet
uses, read the `:root` block at the top of `app.css` and substitute the real
variable names — do not introduce new ones.

- [ ] **Step 3: Fetch the insights**

In `app.js`, inside `loadData()` after the boundary-layer `Promise.all` block
(around line 561), add:

```javascript
  // Community insights are the one panel that reads the database live, so a
  // statement published in Admin appears on the next refresh. Failure is not
  // fatal: the panel falls back to the analyst snippets from tags.json.
  state.data.insights = await fetch("api/insights/?limit=2000")
    .then((r) => (r.ok ? r.json() : { results: [] }))
    .then((body) => body.results)
    .catch(() => []);
```

- [ ] **Step 4: Add the tab to state**

In `app.js`, beside `voiceSearch` (line ~157), add:

```javascript
  voiceTab: "community",   // which Community Insights tab is showing
```

- [ ] **Step 5: Rewrite `allVoices` to serve all three tabs**

Replace the whole `allVoices()` function (from `function allVoices() {` to its
closing brace, ~1693–1710) with:

```javascript
/* Every quote the panel can show, from both sources, in one shape.

   Two sources, deliberately not merged into one table upstream:
     - tags.json snippets: regex matches on analyst prose, rebuilt by s03_parse
       on every pipeline run. These are secondary_analysis by definition.
     - /api/insights/: statements a person reviewed and published.

   Both filters are applied HERE, as the comment on monthTagTotals requires, so
   the panel and the map cannot drift apart. */
function allVoices() {
  const rows = [];

  // Analyst voice: the regex snippets, exactly as before.
  for (const [dim, tags] of Object.entries(state.data.tags)) {
    if (!DIM_META[dim]) continue;
    const only = activeTagsIn(dim);
    for (const [tag, tagData] of Object.entries(tags)) {
      if (only && !only.has(tag)) continue;
      for (const mk of Object.keys(tagData.snippets)) {
        if (filtered() && !tagCount(tagData, mk)) continue;
        const text = snippetFor(tagData, mk);
        if (text) rows.push({ dim, tag, mk, text, full: text, voice: "secondary_analysis" });
      }
    }
  }

  // Published insights, community and analyst alike.
  for (const row of state.data.insights || []) {
    const mk = (row.date || "").slice(0, 7);
    for (const coding of row.codings.length ? row.codings : [{ dimension: null, tag: null }]) {
      const dim = coding.dimension;
      if (dim && !DIM_META[dim]) continue;
      // Same theme filter the map layers use - one filter, four consumers.
      if (dim) {
        const only = activeTagsIn(dim);
        if (only && !only.has(coding.tag)) continue;
      }
      rows.push({
        dim: dim || "need", tag: coding.tag || "other", mk,
        text: row.quote, full: row.quote, translated: row.quote_translated,
        voice: row.voice_type, place: row.place_name, date: row.date,
        source: row.source_document, matchMethod: row.match_method,
        lat: row.lat, lon: row.lon, id: row.id,
      });
    }
  }

  return rows.sort((a, b) => (a.mk < b.mk ? 1 : a.mk > b.mk ? -1 : 0));
}

/* The rows the active tab shows. Search is scoped to this, which is the point
   of the tabs: with Community selected, a search never returns analyst prose. */
function voicesForTab() {
  const all = allVoices();
  if (state.voiceTab === "community") return all.filter((v) => v.voice === "community");
  if (state.voiceTab === "analyst") return all.filter((v) => v.voice === "secondary_analysis");
  return all;
}
```

- [ ] **Step 6: Rewrite `renderVoices` to use the tab**

Replace the body of `renderVoices()` (~1720–1765) with:

```javascript
function renderVoices() {
  const el = $("#voices"), q = state.voiceSearch.trim().toLowerCase();
  const searching = q.length > 0;
  const pool = voicesForTab();
  let picks;

  if (searching) {
    picks = pool.filter((v) =>
      v.full.toLowerCase().includes(q) ||
      (v.translated || "").toLowerCase().includes(q) ||
      (v.place || "").toLowerCase().includes(q) ||
      v.tag.replace(/_/g, " ").toLowerCase().includes(q) ||
      DIM_META[v.dim].label.toLowerCase().includes(q)).slice(0, 40);
  } else {
    const mk = monthKey(state.current);
    const month = pool.filter((v) => v.mk === mk);
    // Community voice is scarce, so show all of it for the month. Analyst
    // snippets are plentiful: keep the old one-per-dimension behaviour.
    picks = state.voiceTab === "analyst" ? month.slice(0, 3) : month.slice(0, 12);
  }

  if (!picks.length) {
    el.innerHTML = `<div class="voices-empty">${searching
      ? `No quote matches “${escapeHTML(state.voiceSearch)}” in this tab.`
      : state.voiceTab === "community"
        ? "No community statement recorded for this month."
        : "No narrative reporting captured for this month."}</div>`;
    $("#voice-count").textContent = "";
    return;
  }

  $("#voice-count").textContent = searching
    ? `${picks.length}${picks.length === 40 ? "+" : ""} across all months` : "";

  const unmapped = picks.filter((v) => v.voice === "community" && v.lat == null).length;

  el.innerHTML = picks.map((p, i) => `<div class="voice${
      p.voice === "community" ? " is-community" : ""}${searching ? " voice-hit" : ""}"
      style="border-color:${DIM_META[p.dim].color}"
      data-month="${p.mk}" data-i="${i}" data-id="${p.id || ""}">
      <div class="v-full">${searching ? highlight(p.full, q) : escapeHTML(p.full)}</div>
      ${p.translated ? `<div class="v-translated">${escapeHTML(p.translated)}</div>` : ""}
      <div class="v-meta">
        <span class="v-voice">${p.voice === "community" ? "Community" : "Analyst"}</span>
        · ${DIM_META[p.dim].label} · ${escapeHTML(p.tag.replace(/_/g, " "))}
        ${p.place ? ` · ${escapeHTML(p.place)}` : ""} · ${monthLabel(p.mk)}
        ${p.source ? ` · ${escapeHTML(p.source)}` : ""}
      </div>
    </div>`).join("") + (unmapped
      ? `<div class="voices-unmapped">${unmapped} of these could not be placed on the map.</div>`
      : "");

  if (searching)
    for (const node of el.querySelectorAll(".voice-hit"))
      node.addEventListener("click", () => goToMonth(node.dataset.month));
}
```

If the existing click handler at the end of `renderVoices` calls something other
than `goToMonth`, keep the original call — read lines 1758–1765 before replacing.

- [ ] **Step 7: Wire the tabs**

In `initVoiceSearch()` (~2808), add before its closing brace:

```javascript
  for (const tab of document.querySelectorAll(".voice-tab"))
    tab.addEventListener("click", () => {
      state.voiceTab = tab.dataset.tab;
      for (const other of document.querySelectorAll(".voice-tab"))
        other.classList.toggle("is-active", other === tab);
      renderVoices();
      if (typeof renderInsightBubbles === "function") renderInsightBubbles();
    });
```

- [ ] **Step 8: Verify in the browser**

```bash
docker compose restart web
```

Open <http://localhost:2026/>. Confirm: three tabs appear; Community is active and
shows either statements or "No community statement recorded for this month";
Analyst shows the snippets the panel showed before this change; typing in the
search box with Community active never returns an analyst passage.

- [ ] **Step 9: Commit**

```bash
git add dashboard/templates/dashboard/index.html dashboard/static/dashboard/js/app.js dashboard/static/dashboard/css/app.css
git commit -m "dashboard: three tabs over Community Insights, search scoped to each

The panel was named for something it did not contain: every snippet in it is
regex-matched analyst prose. Those become the Analyst tab; published community
statements become the Community tab.

Both filters are applied in allVoices(), as the comment on monthTagTotals
requires - one filter, four consumers, so the panel cannot drift from the map."
```

---

### Task 12: Dashboard — quote bubbles on the map

**Files:**
- Modify: `dashboard/static/dashboard/js/app.js` (map layer setup, and `renderMapLayers`)
- Modify: `dashboard/static/dashboard/css/app.css`

**Interfaces:**
- Consumes: `voicesForTab()` and `state.voiceTab` from Task 11; `state.activeTags` and `activeTagsIn` (existing).
- Produces: `renderInsightBubbles()`, called from `renderMapLayers` and from the tab handler added in Task 11 Step 7.

- [ ] **Step 1: Add the source and layer**

In `app.js`, find where the other map sources are added after the style loads
(search for `map.addSource(`). Add alongside them:

```javascript
  // Quote bubbles. Deliberately NOT sized by anything: a single statement is not
  // a quantity, and scaling it would imply one.
  map.addSource("insight-bubbles", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    cluster: true,
    clusterRadius: 28,
  });
  map.addLayer({
    id: "insight-bubbles",
    type: "circle",
    source: "insight-bubbles",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": 6,
      "circle-color": ["get", "colour"],
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#fff",
      "circle-opacity": 0.9,
    },
  });
  map.addLayer({
    id: "insight-clusters",
    type: "circle",
    source: "insight-bubbles",
    filter: ["has", "point_count"],
    paint: {
      "circle-radius": 12,
      "circle-color": "#555",
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#fff",
      "circle-opacity": 0.85,
    },
  });
  map.addLayer({
    id: "insight-cluster-count",
    type: "symbol",
    source: "insight-bubbles",
    filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11 },
    paint: { "text-color": "#fff" },
  });
```

- [ ] **Step 2: Write the renderer**

Add near `renderMapLayers` in `app.js`:

```javascript
/* Bubbles for every published insight whose place resolved.

   Unplaced insights are simply absent - camps, settlements and neighbourhoods
   are not in the boundary library and never will be. That absence is honest,
   and the panel reports how many are missing rather than hiding it.

   The set shown is voicesForTab(), so the theme filter, the country filter and
   the active tab all apply here exactly as they do to the cards. */
function renderInsightBubbles() {
  const source = map.getSource("insight-bubbles");
  if (!source) return;

  const seen = new Set();
  const features = [];
  for (const row of voicesForTab()) {
    if (row.lat == null || row.lon == null || !row.id) continue;
    if (seen.has(row.id)) continue;   // one bubble per statement, not per coding
    seen.add(row.id);
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [row.lon, row.lat] },
      properties: {
        id: row.id,
        colour: DIM_META[row.dim].color,
        quote: row.full,
        place: row.place || "",
        date: row.date || "",
        source: row.source || "",
        matchMethod: row.matchMethod || "unmatched",
        voice: row.voice,
      },
    });
  }
  source.setData({ type: "FeatureCollection", features });
}
```

- [ ] **Step 3: Call it wherever the layers refresh**

In `renderMapLayers()`, add `renderInsightBubbles();` as its last statement. In
the render pass that already calls `renderVoices()` (~line 2238), add
`renderInsightBubbles();` immediately after it.

- [ ] **Step 4: Add the popup**

After the layers are added in Step 1, add:

```javascript
  // A bubble sits at the matched polygon's label point, NOT where anyone stood.
  // The popup says which, because match_method knows the difference and a reader
  // should not have to guess.
  map.on("click", "insight-bubbles", (e) => {
    const p = e.features[0].properties;
    const placed = p.matchMethod === "unmatched"
      ? "" : `<div class="ip-place">Located to ${escapeHTML(p.place)}${
          p.matchMethod === "name" ? " (named area, label position)" : " (p-code)"}</div>`;
    new maplibregl.Popup({ maxWidth: "320px" })
      .setLngLat(e.features[0].geometry.coordinates)
      .setHTML(`<div class="insight-popup">
          <div class="ip-voice">${p.voice === "community" ? "Community" : "Analyst"}</div>
          <blockquote>${escapeHTML(p.quote)}</blockquote>
          ${placed}
          <div class="ip-meta">${escapeHTML(p.date)}${
            p.source ? ` · ${escapeHTML(p.source)}` : ""}</div>
        </div>`)
      .addTo(map);

    // Tie the map back to the panel: highlight the card for this statement.
    for (const node of document.querySelectorAll("#voices .voice"))
      node.classList.toggle("is-selected", node.dataset.id === String(p.id));
  });

  map.on("mouseenter", "insight-bubbles", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "insight-bubbles", () => { map.getCanvas().style.cursor = ""; });
```

MapLibre reports click coordinates in map space, so the page's `--ui-scale: 0.8`
does not affect this handler. Do not add a scale correction here.

- [ ] **Step 5: Style the popup**

Append to `dashboard/static/dashboard/css/app.css`:

```css
.insight-popup blockquote {
  margin: 4px 0; font-size: 12px; line-height: 1.45; white-space: pre-wrap;
}
.insight-popup .ip-voice {
  font-size: 10px; text-transform: uppercase; letter-spacing: .04em; opacity: .65;
}
.insight-popup .ip-place { font-size: 11px; opacity: .8; }
.insight-popup .ip-meta { font-size: 10px; opacity: .6; margin-top: 4px; }
.voice.is-selected { outline: 2px solid var(--ink); }
```

- [ ] **Step 6: Verify in the browser**

```bash
docker compose restart web
```

Publish a test insight in Admin with a place that resolves (e.g. `iso3=SDN`,
place `North Darfur`), then open the dashboard. Confirm: a bubble appears; ticking
only the flooding hazard hides it unless it carries that tag; the Analyst tab
changes which bubbles show; clicking a bubble opens the statement and highlights
its card.

- [ ] **Step 7: Commit**

```bash
git add dashboard/static/dashboard/js/app.js dashboard/static/dashboard/css/app.css
git commit -m "dashboard: quote bubbles, filtered by the same theme selection

The bubbles read voicesForTab(), so the theme filter, the country filter and
the active tab all apply to the map exactly as they do to the cards - which is
what app.js:1632 already required of every panel.

Not sized by anything: a single statement is not a quantity. The popup says
whether a bubble is a p-code match or a named area's label point, because
match_method knows and a reader should not have to guess."
```

---

### Task 13: Phase 2 — in-container extraction adapters

**Files:**
- Create: `insights/extractors/__init__.py`, `insights/extractors/base.py`, `insights/extractors/anthropic_api.py`, `insights/extractors/openai_compatible.py`
- Create: `insights/management/commands/extract_insights.py`
- Create: `insights/tests/test_extractors.py`
- Modify: `config/settings.py` (LLM settings), `requirements.txt`, `docker-compose.yml` (web `environment:`), `env.example`

**Interfaces:**
- Consumes: `insights.contract.parse`, `insights.loader.load`, `insights.intake`.
- Produces: `insights.extractors.get_extractor() -> Extractor` with `Extractor.extract(document, pages) -> dict` (a payload matching Task 5's contract).

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_extractors.py`:

```python
"""Selecting an adapter, and building the prompt. No network calls here.

The adapters themselves are thin - one HTTP round trip each - so what is worth
testing is the selection, the configuration falling back correctly on an empty
env var, and that the prompt file is actually read rather than inlined.
"""
from django.test import SimpleTestCase, override_settings

from insights.extractors import get_extractor, prompt_text
from insights.extractors.anthropic_api import AnthropicExtractor
from insights.extractors.openai_compatible import OpenAICompatibleExtractor


class SelectionTests(SimpleTestCase):
    @override_settings(LLM_PROVIDER="anthropic", LLM_MODEL="claude-opus-5")
    def test_anthropic_is_selected(self):
        self.assertIsInstance(get_extractor(), AnthropicExtractor)

    @override_settings(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://x/v1")
    def test_openai_compatible_is_selected(self):
        self.assertIsInstance(get_extractor(), OpenAICompatibleExtractor)

    @override_settings(LLM_PROVIDER="nonesuch")
    def test_an_unknown_provider_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            get_extractor()


class PromptTests(SimpleTestCase):
    def test_the_prompt_is_read_from_the_file(self):
        text = prompt_text()
        self.assertIn("community insight", text.lower())
        self.assertIn("verbatim", text.lower())
        self.assertIn("mcp_cache/insights", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_extractors -v 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'insights.extractors'`

- [ ] **Step 3: Add the settings**

In `config/settings.py`, after the `MEDIA_ROOT` block from Task 7:

```python
# The in-container extraction adapter (spec §8.2). Optional: with nothing set,
# extraction is run by an agent on the host and loaded from mcp_cache/insights/.
# `or` rather than a default argument - an empty value in .env must fall back.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER") or "anthropic"
LLM_MODEL = os.environ.get("LLM_MODEL") or "claude-opus-5"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or ""
LLM_API_KEY = os.environ.get("LLM_API_KEY") or ""
```

In `docker-compose.yml`, in the `web` service's `environment:` block after `TZ`:

```yaml
      # Optional in-container insight extraction. Leave unset to run extraction
      # with an agent on the host instead. For a local model, point LLM_BASE_URL
      # at http://host.docker.internal:11434/v1 and set LLM_PROVIDER to
      # openai_compatible.
      LLM_PROVIDER: ${LLM_PROVIDER:-}
      LLM_MODEL: ${LLM_MODEL:-}
      LLM_BASE_URL: ${LLM_BASE_URL:-}
      LLM_API_KEY: ${LLM_API_KEY:-}
```

Add the same four keys, commented out with the same explanation, to `env.example`.

In `requirements.txt`, after the `python-docx` line:

```
anthropic==1.2.0         # optional: in-container insight extraction (insights/extractors/)
```

Then: `docker compose build web && docker compose up -d web`

- [ ] **Step 4: Write the adapters**

Create `insights/extractors/__init__.py`:

```python
"""Pick an adapter. Two are enough.

The OpenAI-compatible one covers OpenAI, Codex, Ollama, LM Studio and vLLM,
because they all speak the same wire format - a local model is a base_url
pointing at host.docker.internal. So the choice is Anthropic native or that.

Both build their prompt from insights/prompts/extract_insights.md, which is the
single source of truth an agent on the host reads too. There is no second copy
of the instructions in this package, and there must never be.
"""
from functools import lru_cache
from pathlib import Path

from django.conf import settings

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract_insights.md"


@lru_cache(maxsize=1)
def prompt_text():
    return PROMPT_PATH.read_text(encoding="utf-8")


def get_extractor():
    from insights.extractors.anthropic_api import AnthropicExtractor
    from insights.extractors.openai_compatible import OpenAICompatibleExtractor

    provider = (settings.LLM_PROVIDER or "").strip().lower()
    if provider == "anthropic":
        return AnthropicExtractor()
    if provider in {"openai_compatible", "openai", "codex", "ollama", "local"}:
        return OpenAICompatibleExtractor()
    raise ValueError(
        f"LLM_PROVIDER={provider!r} is not one of 'anthropic' or 'openai_compatible'."
    )
```

Create `insights/extractors/base.py`:

```python
"""What both adapters share: how a document is turned into a request."""
import json

from insights.extractors import prompt_text

# One request per chunk of pages. Chunking rather than sending a whole report
# keeps the page numbers the model must cite close to the text it is reading,
# which is the field it most often gets wrong.
PAGES_PER_REQUEST = 8


class Extractor:
    name = ""

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
    def parse_json(text):
        """Models sometimes wrap JSON in a fence. Tolerate that and nothing else."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)

    @property
    def system_prompt(self):
        return prompt_text()
```

Create `insights/extractors/anthropic_api.py`:

```python
"""Anthropic native. Structured outputs, adaptive thinking, streaming.

budget_tokens is REMOVED on claude-opus-5 and returns a 400 - adaptive thinking
replaces it, with output_config.effort controlling depth.

Structured outputs and Citations cannot be combined (the API returns 400), which
is a second reason the verbatim guarantee lives in insights/verify.py: it costs
nothing there and works for every provider, including the local ones this
package also supports.
"""
from django.conf import settings

from insights.extractors.base import Extractor

SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "quote_language": {"type": "string"},
                    "page": {"type": "integer"},
                    "voice_type": {"type": "string", "enum": ["community", "secondary_analysis"]},
                    "place_name_as_written": {"type": ["string", "null"]},
                    "iso3": {"type": "string"},
                    "codings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "tag": {"type": "string"},
                            },
                            "required": ["dimension", "tag"],
                            "additionalProperties": False,
                        },
                    },
                    "people_affected": {"type": ["integer", "null"]},
                    "severity": {"type": ["integer", "null"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["quote", "page", "voice_type", "iso3", "codings"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}


class AnthropicExtractor(Extractor):
    name = "anthropic"

    def __init__(self):
        self.model = settings.LLM_MODEL or "claude-opus-5"

    def _client(self):
        import anthropic

        # An unset key is not the same as no credentials: the SDK also reads
        # ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile.
        return anthropic.Anthropic(api_key=settings.LLM_API_KEY or None)

    def extract(self, document, pages):
        client = self._client()
        payload = self.empty_payload(document)

        for chunk in self.chunks(pages):
            with client.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=self.system_prompt,
                thinking={"type": "adaptive"},
                output_config={"effort": "high", "format": {"type": "json_schema",
                                                            "schema": SCHEMA}},
                messages=[{"role": "user",
                           "content": self.build_user_message(document, chunk)}],
            ) as stream:
                message = stream.get_final_message()

            if message.stop_reason == "refusal":
                continue
            text = "".join(b.text for b in message.content if b.type == "text")
            payload["insights"].extend(self.parse_json(text).get("insights", []))

        return payload
```

Create `insights/extractors/openai_compatible.py`:

```python
"""One adapter for every server that speaks the OpenAI chat-completions format:
OpenAI, Codex, Ollama, LM Studio, vLLM.

A local model is just LLM_BASE_URL pointing at host.docker.internal. Nothing here
is Anthropic-specific and nothing here should become so - that is the whole point
of having two adapters rather than one.
"""
import json
import urllib.request

from django.conf import settings

from insights.extractors.base import Extractor

TIMEOUT_SECONDS = 300


class OpenAICompatibleExtractor(Extractor):
    name = "openai_compatible"

    def __init__(self):
        self.model = settings.LLM_MODEL or "gpt-4o-mini"
        self.base_url = (settings.LLM_BASE_URL or "").rstrip("/")
        if not self.base_url:
            raise ValueError("LLM_BASE_URL must be set for the openai_compatible provider.")

    def _post(self, body):
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Local servers accept and ignore an empty bearer token.
                "Authorization": f"Bearer {settings.LLM_API_KEY or 'not-needed'}",
            },
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    def extract(self, document, pages):
        payload = self.empty_payload(document)
        for chunk in self.chunks(pages):
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": self.build_user_message(document, chunk)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            }
            answer = self._post(body)
            text = answer["choices"][0]["message"]["content"]
            payload["insights"].extend(self.parse_json(text).get("insights", []))
        return payload
```

- [ ] **Step 5: Write the command**

Create `insights/management/commands/extract_insights.py`:

```python
"""Run extraction in-container for one job, then load the result.

    manage.py extract_insights --job 4

Every payload is still written to mcp_cache/insights/ before it is loaded, so an
in-container run leaves exactly the same evidence on disk as an agent on the host
does, and can be re-loaded without re-paying for the model.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from data_track.models import Document, DocumentText
from insights.contract import ContractError
from insights.extractors import get_extractor
from insights.loader import load
from insights.models import ExtractionJob


class Command(BaseCommand):
    help = "Extract community insights from a job's documents using the configured model."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, required=True)

    def handle(self, *args, **options):
        job = ExtractionJob.objects.filter(id=options["job"]).first()
        if job is None:
            raise CommandError(f"no ExtractionJob with id {options['job']}")

        extractor = get_extractor()
        out_dir = Path(settings.MCP_CACHE_DIR) / "insights"
        out_dir.mkdir(parents=True, exist_ok=True)

        documents = Document.objects.filter(source_collection="insights").order_by("id")
        job.status = "running"
        job.producer = extractor.name
        job.model_used = extractor.model
        job.started_at = timezone.now()
        job.documents_total = documents.count()
        job.save()

        for document in documents:
            pages = list(DocumentText.objects.filter(document=document)
                         .order_by("page").values_list("page", "text"))
            payload = extractor.extract(document, pages)

            if payload["insights"]:
                path = out_dir / f"{Path(document.rel_path).stem}.json"
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                encoding="utf-8")
                try:
                    report = load(payload, document, job=job,
                                  model_used=extractor.model)
                    self.stdout.write(
                        f"{document.file_name}: {report.written} pending, "
                        f"{report.rejected_unverifiable} unverifiable")
                except ContractError as exc:
                    self.stderr.write(f"{document.file_name}: {exc}")
            else:
                self.stdout.write(f"{document.file_name}: nothing to extract")

            job.documents_done += 1
            job.save(update_fields=["documents_done"])

        job.status = "loaded"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: every test from Tasks 1–13 PASS.

- [ ] **Step 7: Commit**

```bash
git add insights/extractors insights/management/commands/extract_insights.py insights/tests/test_extractors.py config/settings.py requirements.txt docker-compose.yml env.example
git commit -m "insights: in-container extraction, two adapters

Anthropic native (adaptive thinking, structured outputs - budget_tokens is
removed on claude-opus-5 and 400s) and one OpenAI-compatible path covering
OpenAI, Codex, Ollama, LM Studio and vLLM, because they share a wire format. A
local model is a base_url pointing at host.docker.internal.

Both build their prompt from insights/prompts/extract_insights.md - the same
file an agent on the host reads. There is no second copy of the instructions.

Every in-container run still writes its payload to mcp_cache/insights/ before
loading, so it leaves the same evidence on disk as a host run and can be
re-loaded without re-paying for the model."
```

---

## Self-Review

**Spec coverage.** §5.1–5.4 → Task 1. §5.5 → Task 4 and the Global Constraints. §5.6 (name collision) → Task 9, which mounts `/api/insights/` and leaves `/api/community-insights/` untouched. §6.1 → Task 10. §6.2–6.3 → Tasks 5 and 10. §6.4 gates 1–4 → Tasks 3, 2, 4 and 6 respectively. §6.5 → Task 6. §7 and §7.1–7.2 → Task 7. §8.1 → Tasks 6 and 8; §8.2 → Task 13. §9 → Task 8. §10 → Task 9. §11.1–11.2 → Task 11; §11.3 → Task 12. §12 verification items 1–10 are covered by the test suites in Tasks 1, 3, 6, 7 and 9 plus the browser checks in Tasks 11 and 12. §13 → Task 10's `CLAUDE.md`. §14 → deliberately out of scope, own plan. §15 limits are documentation, not tasks.

**Gap found and closed:** spec §12 item 6 (duplicate manual entries colliding) had no test until it was added as `test_two_identical_manual_insights_collide` in Task 1.

**Type consistency.** `quote_sha1` is a function in `insights/verify.py` and a column on `Insight`; Task 8 imports it as `_sha1` inside `save()` to avoid shadowing the field — checked. `resolve()` returns exactly the five keys `Insight` expects, and Task 6 splats them with `**placement` — checked. `LoadReport` fields (`written`, `rejected_unverifiable`, `skipped_reviewed`) match the counters Task 6's tests and Task 8's messages read — checked. `allVoices()` rows gain `full`, `voice`, `id`, `lat`, `lon` in Task 11 and Task 12 consumes exactly those — checked. `normalise_coding` returns `{dimension, tag, tag_raw}`, which is what `InsightCoding(**coding)` needs — checked.

**Known soft spot for the executor:** Task 11 and Task 12 give line numbers from the current `app.js`. Those shift as soon as Task 11 lands. Read the surrounding function before applying Task 12's edits rather than trusting the numbers.
