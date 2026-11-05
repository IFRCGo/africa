# Docling Read Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a visible "Read these documents" step between choosing files and paying the model, in which Docling converts each PDF or Word file to per-page markdown that replaces the PyMuPDF text the model reads today.

**Architecture:** Intake keeps its fast PyMuPDF pass as a placeholder, so no document is ever textless (the pipeline's `s02_extract_text` would grab it). A new detached management command then converts each document with Docling and replaces its `DocumentText` rows, recording what happened in a new `insights.Conversion` row. A document Docling cannot read keeps its PyMuPDF text and is badged on the preview. Quote verification gains a markdown-folding pass so a model quoting words still matches a stored line carrying markup — confined to `quote_is_verbatim` so `quote_sha1`, a unique-constraint natural key, never changes.

**Tech Stack:** Django 5.0.6, PostgreSQL/PostGIS, Docling (+ CPU-only PyTorch, EasyOCR), PyMuPDF (retained), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-21-docling-read-step-design.md`

## Global Constraints

- **Everything runs in Docker.** There is no Django environment on the host. Every command is `docker compose exec web python manage.py <command>`; tests are `docker compose exec web python manage.py test <label> -v 2`.
- **`web` runs gunicorn, which never autoreloads.** After any model change: `docker compose restart web`. Migrating alone is not enough — `AddField` sets a DB default only to backfill it and then drops it, so a worker that booted before the field existed omits the column from its INSERT and the next request raises `NotNullViolation`. `manage.py test` forks a fresh process, so the suite stays green while the running site is broken.
- **`/work` is mounted read-only.** Anything written goes under `/app`.
- **Settings use `os.environ.get(X) or default`** (or `env_path`/`env_paths`), never `get(X, default)`, so an empty `.env` value falls back instead of being read as empty.
- **Never widen `verify.normalise()` or `verify.quote_sha1()`.** They feed the `(document, page, quote_sha1)` unique constraint at `insights/models.py:248`. Changing them would make a re-extraction insert duplicates beside published rows instead of matching them.
- **The `insights` app is never written to by any pipeline step**, and `data_pipeline/` and `data_track/` are not modified by this plan at all.
- **Exception reporting is type and message only** — `f"{type(exc).__name__}: {exc}"` — never the repr and never an SDK exception's request object, which can carry `LLM_API_KEY`.
- Exact pinned values: `DOCLING_OCR_LANGS` defaults to `en,ar` (EasyOCR will not load Arabic beside another non-English language); `DOCLING_MAX_PAGES` defaults to `40`; `DOCLING_TIMEOUT_SECONDS` defaults to `900`; `DOCLING_ARTIFACTS_PATH` defaults to `/opt/docling/models`; `DOCLING_ENABLED` defaults to `True`.

## File Structure

| File | Responsibility |
|---|---|
| `config/settings.py` (modify) | The five `DOCLING_*` settings |
| `requirements.txt` (modify) | `torch` (pinned, CPU), `docling`, `easyocr` |
| `Dockerfile` (modify) | CPU torch index, model prefetch layers |
| `insights/verify.py` (modify) | `_fold_markup`, applied inside `quote_is_verbatim` only |
| `insights/models.py` (modify) | `Conversion`; `ExtractionJob.status` help text |
| `insights/docling_reader.py` (create) | The only module that imports Docling. Path in, `[(page, markdown)]` + version out. |
| `insights/convert.py` (create) | Orchestration: refusal gate, cache, atomic row replacement, fallback, re-dating |
| `insights/management/commands/convert_documents.py` (create) | The detached per-job run, mirroring `extract_insights.py` |
| `insights/wizard.py` (modify) | `read`, `read_done`, staged `log_path`, `step_links`, `job_step`, `batch_ready` |
| `insights/templates/insights/wizard_read.html` (create) | Step 2's page |
| `insights/static/insights/wizard_read.js` (create) | Its polling loop |
| `insights/admin.py` (modify) | Two `status="queued"` call sites, `reset_stuck_job`, the new URLs |
| `insights/intake.py` (modify) | `_pdf_metadata` → `pdf_metadata`; `catalogue_folder` opens at `collected` |
| `insights/prompts/extract_insights.md` (modify) | One sentence: the text is markdown |

---

### Task 1: Docling in the image, and its settings

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`
- Modify: `config/settings.py:50` (after `MCP_CACHE_DIR`)
- Test: `insights/tests/test_docling_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.DOCLING_ENABLED: bool`, `settings.DOCLING_OCR_LANGS: list[str]`, `settings.DOCLING_MAX_PAGES: int`, `settings.DOCLING_TIMEOUT_SECONDS: int`, `settings.DOCLING_ARTIFACTS_PATH: Path`. An importable `docling` package inside the `web` container with its weights already on disk.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_docling_settings.py`:

```python
"""The Docling settings exist, and an empty .env value falls back.

The empty-value case is the one that bites: `os.environ.get(X, default)`
returns "" for a key present but blank in .env, which would hand EasyOCR an
empty language list and Docling a max_pages of 0.
"""
import importlib

from django.test import TestCase


class DoclingSettingsTests(TestCase):
    def reload(self, **env):
        import os

        import config.settings as settings_module

        previous = {k: os.environ.get(k) for k in env}
        os.environ.update({k: v for k, v in env.items()})
        try:
            return importlib.reload(settings_module)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(settings_module)

    def test_defaults(self):
        reloaded = self.reload(DOCLING_OCR_LANGS="", DOCLING_MAX_PAGES="")
        self.assertEqual(reloaded.DOCLING_OCR_LANGS, ["en", "fr", "ar"])
        self.assertEqual(reloaded.DOCLING_MAX_PAGES, 40)
        self.assertEqual(reloaded.DOCLING_TIMEOUT_SECONDS, 900)
        self.assertTrue(reloaded.DOCLING_ENABLED)
        self.assertEqual(str(reloaded.DOCLING_ARTIFACTS_PATH), "/opt/docling/models")

    def test_langs_are_split_and_stripped(self):
        reloaded = self.reload(DOCLING_OCR_LANGS=" en , ar ")
        self.assertEqual(reloaded.DOCLING_OCR_LANGS, ["en", "ar"])

    def test_enabled_is_off_for_the_word_false(self):
        reloaded = self.reload(DOCLING_ENABLED="false")
        self.assertFalse(reloaded.DOCLING_ENABLED)

    def test_docling_is_installed(self):
        import docling  # noqa: F401
        from docling.document_converter import DocumentConverter  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_docling_settings -v 2`
Expected: FAIL — `AttributeError: module 'config.settings' has no attribute 'DOCLING_OCR_LANGS'`, and `ModuleNotFoundError: No module named 'docling'`.

- [ ] **Step 3: Add the settings**

In `config/settings.py`, directly after the `MCP_CACHE_DIR` block:

```python
# Reading documents for the insights wizard (spec 2026-09-21 §11). Docling
# converts a PDF or Word file to per-page markdown before the model sees it;
# PyMuPDF stays as the per-document fallback.
# `or` rather than a default argument throughout - an empty value in .env must
# fall back, not be read as "no languages" or "no pages".
DOCLING_ENABLED = (os.environ.get("DOCLING_ENABLED") or "true").strip().lower() not in (
    "0", "false", "no", "off")
DOCLING_OCR_LANGS = [
    part.strip() for part in (os.environ.get("DOCLING_OCR_LANGS") or "en,fr,ar").split(",")
    if part.strip()
]
# The same ceiling s02_extract_text.MAX_PAGES has always held, and it matters
# far more here: with OCR on, every page is paid for in minutes.
DOCLING_MAX_PAGES = int(os.environ.get("DOCLING_MAX_PAGES") or 40)
DOCLING_TIMEOUT_SECONDS = int(os.environ.get("DOCLING_TIMEOUT_SECONDS") or 900)
# Where the Docker build baked the layout, table and OCR weights.
DOCLING_ARTIFACTS_PATH = env_path("DOCLING_ARTIFACTS_PATH", Path("/opt/docling/models"))
```

- [ ] **Step 4: Add the dependencies**

In `requirements.txt`, append (keeping the existing comment style, and pinning
`torch` to the same version the Dockerfile installs):

```
torch==2.4.1             # docling's model runtime; installed CPU-only, see Dockerfile
docling==2.54.0          # converts PDFs/Word to per-page markdown before the model reads them
easyocr==1.7.2           # the OCR engine docling is told to use (Arabic and French, unlike the default)
```

- [ ] **Step 5: Add the build layers**

In `Dockerfile`, replace the single `RUN pip install` line with:

```dockerfile
# PyTorch first, from its CPU-only index. docling depends on torch, and the
# default PyPI wheel drags in the CUDA runtime - about 2GB of GPU libraries
# this container can never use. The version is pinned HERE AND IN
# requirements.txt to the same value on purpose: without the pin, the resolve
# below is free to decide docling wants a different torch and replace this
# wheel with the CUDA one, silently undoing the whole layer.
RUN pip install --no-cache-dir torch==2.4.1 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Bake the model weights into the image. Without this, the FIRST click on
# "Read these documents" downloads ~500MB inside a detached subprocess with no
# progress anywhere a person can see it, and fails outright with no internet.
ENV DOCLING_ARTIFACTS_PATH=/opt/docling/models
RUN HOME=/opt/docling docling-tools models download \
    && mkdir -p /opt/docling/models

# EasyOCR fetches its own detection and recognition weights, which
# docling-tools does not cover. Instantiating the Reader once is what pulls
# them. Keep the language list in step with DOCLING_OCR_LANGS.
RUN python -c "import easyocr; easyocr.Reader(['en','fr','ar'], gpu=False, \
    model_storage_directory='/opt/docling/models', download_enabled=True)"
```

- [ ] **Step 6: Rebuild and run the test**

Run:
```bash
docker compose build web
docker compose up -d
docker compose exec web python manage.py test insights.tests.test_docling_settings -v 2
```
Expected: PASS, all five tests.

- [ ] **Step 7: Record the real image size**

Run: `docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | grep -i web`

The spec predicts 2.5–3.5GB. Note the actual number in the commit message — a figure far outside that range means the CPU torch pin did not hold, and step 5's warning is the place to look.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt Dockerfile config/settings.py insights/tests/test_docling_settings.py
git commit -m "feat: install Docling CPU-only with weights baked in"
```

---

### Task 2: Markdown-aware quote verification

**Files:**
- Modify: `insights/verify.py`
- Test: `insights/tests/test_verify.py` (existing file, add a class)

**Interfaces:**
- Consumes: nothing.
- Produces: `verify._fold_markup(text) -> str`. `verify.quote_is_verbatim(document_id, page, quote) -> bool` keeps its exact signature and return type. `verify.normalise` and `verify.quote_sha1` are **unchanged**.

- [ ] **Step 1: Write the failing test**

Append to `insights/tests/test_verify.py`:

```python
class MarkdownFoldingTests(TestCase):
    """A quote of the words matches a stored line that carries the markup.

    Docling's text is markdown. The model is asked for a verbatim quote and
    returns the sentence, not the asterisks around part of it - so the fold
    has to happen on both the needle and the haystack.
    """

    def setUp(self):
        self.document = Document.objects.create(
            file_name="r.pdf", rel_path="media/abc-r.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40)

    def page(self, text, page=1):
        DocumentText.objects.create(document=self.document, page=page, text=text)

    def test_quote_without_emphasis_matches_a_bolded_line(self):
        self.page("Families reported that **water points** were destroyed.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Families reported that water points were destroyed."))

    def test_quote_matches_across_a_table_pipe(self):
        self.page("| Kulbus | 12,400 displaced since June |")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Kulbus 12,400 displaced since June"))

    def test_quote_matches_a_heading(self):
        self.page("## Protection concerns in Zalingei\n\nThe clinic closed.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Protection concerns in Zalingei"))

    def test_quote_matches_a_list_item(self):
        self.page("- No water has reached the site since March.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "No water has reached the site since March."))

    def test_a_changed_word_still_fails(self):
        # The whole reason this gate exists. Folding markup must not fold meaning.
        self.page("Families reported that **water points** were destroyed.")
        self.assertFalse(quote_is_verbatim(
            self.document.id, 1, "Families reported that water points were rebuilt."))

    def test_hyphenated_place_names_survive_the_fold(self):
        # The trap: a position-independent "-" strip would eat this, and
        # normalise() has already folded en-dashes to the same character.
        self.page("Displacement from **Al-Fasher** rose between 12-14 June.")
        self.assertTrue(quote_is_verbatim(
            self.document.id, 1, "Displacement from Al-Fasher rose between 12-14 June."))

    def test_markup_alone_cannot_pass_the_length_guard(self):
        # The 3-word/12-character floor must measure the FOLDED needle, or
        # "** ** **" buys its way past a check meant to stop trivial matches.
        self.page("| ** | ** | ** | text here to match against |")
        self.assertFalse(quote_is_verbatim(self.document.id, 1, "** ** ** **"))


class NaturalKeyStabilityTests(TestCase):
    """quote_sha1 must be byte-identical to what it was before the fold existed.

    It is half of the (document, page, quote_sha1) unique constraint. If it
    moves, a re-extraction inserts duplicates beside published rows instead of
    matching them, and no error is raised anywhere.
    """

    FIXED = {
        "Families reported that water points were destroyed.":
            "f0a4d0b2e0a1e3b9c7a2d1e4f6b8c0a2d4e6f8b0",
        "**bold** text": "0" * 40,
    }

    def test_hashes_are_unchanged(self):
        # Fill FIXED with the values printed by, BEFORE touching verify.py:
        #   docker compose exec web python -c "from insights.verify import quote_sha1; \
        #     print(quote_sha1('Families reported that water points were destroyed.'))"
        for text, expected in self.FIXED.items():
            self.assertEqual(quote_sha1(text), expected, f"quote_sha1 moved for {text!r}")
```

Add to that file's imports: `from insights.verify import quote_is_verbatim, quote_sha1` and `from data_track.models import Document, DocumentText`, if not already present.

- [ ] **Step 2: Capture the real hashes before changing anything**

Run:
```bash
docker compose exec web python -c "from insights.verify import quote_sha1; \
print(quote_sha1('Families reported that water points were destroyed.')); \
print(quote_sha1('**bold** text'))"
```
Paste both values into `NaturalKeyStabilityTests.FIXED`, replacing the placeholders. This must happen **before** `verify.py` is edited — the point of the test is that these values do not move.

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_verify -v 2`
Expected: `MarkdownFoldingTests` FAIL (the emphasis, pipe, heading and list cases return `False`); `NaturalKeyStabilityTests` PASS already, and must keep passing.

- [ ] **Step 4: Implement the fold**

In `insights/verify.py`, add after the `_QUOTES` tables:

```python
# Docling's text is markdown, so the stored page carries markers the model does
# not quote back. These fold BOTH the needle and the haystack, so stripping
# aggressively is safe: a character removed from both sides cannot change
# whether they match, only whether a marker could hide a real difference - and
# none of these can, because none of them is a word.
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_MD_BULLET = re.compile(r"^[ \t]{0,3}(?:[-*+]|\d{1,3}[.)])[ \t]+", re.M)
_MD_RULE = re.compile(r"^[ \t]*\|?[\s:|-]*\|[\s:|-]*$", re.M)
_MD_EMPHASIS = re.compile(r"\*\*|__|[*_`]")


def _fold_markup(text):
    """Drop the markers Docling's markdown adds, keeping every word.

    ORDER MATTERS, AND IT IS THE OPPOSITE OF THE OBVIOUS ONE: this runs BEFORE
    normalise(), never after. normalise() does re.sub(r"\\s+", " ", ...), which
    destroys line boundaries - and after that there is no "start of a line" for
    a heading's "#" or a bullet's "- " to be anchored to. Stripping those
    characters position-independently instead would eat the hyphen in
    "Al-Fasher" and in "12-14 June", which normalise() has by then folded from
    an en-dash into exactly that character. So the line-shaped patterns are
    anchored and run on raw text; only emphasis, pipes and links are
    position-independent.
    """
    if not text:
        return ""
    folded = _MD_LINK.sub(r"\1", str(text))
    folded = _MD_RULE.sub(" ", folded)
    folded = _MD_HEADING.sub("", folded)
    folded = _MD_BULLET.sub("", folded)
    folded = _MD_EMPHASIS.sub("", folded)
    return folded.replace("|", " ")
```

Then change `quote_is_verbatim`'s two normalisation calls, and nothing else in the function:

```python
    needle = normalise(_fold_markup(quote))
```

```python
    return needle in normalise(_fold_markup(row.text))
```

Extend the existing docstring paragraph about the length guard with one sentence: *"The guard measures the folded needle, so markup cannot pad a degenerate fragment past it."*

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_verify insights.tests.test_contract insights.tests.test_loader -v 2`
Expected: PASS. `test_contract` and `test_loader` are included because `contract.py:86` and `:140` call `normalise` directly — they must be undisturbed.

- [ ] **Step 6: Commit**

```bash
git add insights/verify.py insights/tests/test_verify.py
git commit -m "feat: fold markdown markup when verifying a quote"
```

---

### Task 3: The `Conversion` record

**Files:**
- Modify: `insights/models.py` (after `ExtractionJob`, before `Insight`)
- Create: `insights/migrations/00NN_conversion.py` (generated)
- Test: `insights/tests/test_models_conversion.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `insights.models.Conversion` with fields `document` (OneToOne to `data_track.Document`, `related_name="conversion"`), `job` (FK to `ExtractionJob`, nullable, `related_name="conversions"`), `engine: str`, `ok: bool`, `pages: int`, `markdown_path: str|None`, `docling_version: str|None`, `message: str|None`, `converted_at: datetime`.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_models_conversion.py`:

```python
"""One document, one current state of having been read."""
from data_track.models import Document
from django.db import IntegrityError
from django.test import TestCase

from insights.models import Conversion, ExtractionJob


class ConversionTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(
            file_name="r.pdf", rel_path="media/abc-r.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40)

    def test_one_conversion_per_document(self):
        Conversion.objects.create(document=self.document, engine="docling", ok=True, pages=3)
        with self.assertRaises(IntegrityError):
            Conversion.objects.create(document=self.document, engine="pymupdf", ok=False)

    def test_deleting_the_job_keeps_the_record(self):
        # How a document was read is evidence about the text in the database.
        # Deleting the batch it arrived in must not erase it.
        job = ExtractionJob.objects.create(status="collected")
        Conversion.objects.create(document=self.document, job=job, engine="docling",
                                  ok=True, pages=3)
        job.delete()
        self.assertEqual(Conversion.objects.get(document=self.document).engine, "docling")

    def test_str_names_the_engine(self):
        row = Conversion.objects.create(document=self.document, engine="pymupdf",
                                        ok=False, pages=2)
        self.assertIn("pymupdf", str(row))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_models_conversion -v 2`
Expected: FAIL — `ImportError: cannot import name 'Conversion'`.

- [ ] **Step 3: Add the model**

In `insights/models.py`, after the `ExtractionJob` class:

```python
class Conversion(models.Model):
    """What happened when we tried to read one document, and with what.

    ONE ROW PER DOCUMENT, not per page: reading is a per-document act, and a
    re-read overwrites the record of the last one. It lives in `insights`
    rather than beside DocumentText in `data_track` for the same reason
    ExtractionJob.documents does - additive, and data_track stays a table the
    pipeline owns.

    `job` is SET_NULL because how a document was read is evidence about the
    text now sitting in the database. Deleting the batch it arrived in must
    not erase it.
    """

    document = models.OneToOneField("data_track.Document", on_delete=models.CASCADE,
                                    related_name="conversion")
    job = models.ForeignKey(ExtractionJob, null=True, blank=True,
                            on_delete=models.SET_NULL, related_name="conversions")
    engine = models.TextField(
        help_text="docling / pymupdf / skipped. 'pymupdf' means Docling was tried "
                  "and failed on this document, so the intake text was left in place.")
    ok = models.BooleanField(default=False)
    pages = models.IntegerField(default=0)
    markdown_path = models.TextField(null=True, blank=True)
    docling_version = models.TextField(
        null=True, blank=True,
        help_text="A later Docling reading the same PDF differently would move "
                  "quotes out from under their page numbers. This is what says why.")
    message = models.TextField(null=True, blank=True)
    converted_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "insight_conversions"
        ordering = ["-converted_at"]

    def __str__(self):
        return f"{self.document_id} read by {self.engine}"
```

- [ ] **Step 4: Make and apply the migration**

Run:
```bash
docker compose exec web python manage.py makemigrations insights
docker compose exec web python manage.py migrate
docker compose restart web
```

The restart is not optional — see Global Constraints. `makemigrations` will also pick up Task 7's `help_text` change if that is done first; it is not, so this migration should contain exactly one `CreateModel`.

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec web python manage.py test insights.tests.test_models_conversion -v 2`
Expected: PASS, three tests.

- [ ] **Step 6: Commit**

```bash
git add insights/models.py insights/migrations/ insights/tests/test_models_conversion.py
git commit -m "feat: record how each document was read"
```

---

### Task 4: `insights/docling_reader.py` — the only module that imports Docling

**Files:**
- Create: `insights/docling_reader.py`
- Test: `insights/tests/test_docling_reader.py`

**Interfaces:**
- Consumes: the `DOCLING_*` settings from Task 1.
- Produces:
  - `docling_reader.read(path: Path) -> tuple[list[tuple[int, str]], str]` — `([(page_number, markdown)], docling_version)`. Page numbers start at 1. Raises on any Docling failure; the caller decides what a failure means.
  - `docling_reader.DoclingDisabled` — raised when `settings.DOCLING_ENABLED` is false.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_docling_reader.py`:

```python
"""Turning a Docling result into numbered pages.

Docling itself is not exercised here - it is slow, it needs weights, and what
can actually go wrong in our code is the page splitting. The converter is
faked; test_convert.py's manual check covers the real thing.
"""
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from insights import docling_reader


class FakePage:
    pass


class FakeDocument:
    def __init__(self, pages):
        self.pages = {n: FakePage() for n in range(1, pages + 1)}


class FakeResult:
    def __init__(self, pages):
        self.document = FakeDocument(pages)


class ReadTests(TestCase):
    def test_pages_are_numbered_from_one(self):
        with mock.patch.object(docling_reader, "_convert",
                               return_value=(FakeResult(3), "2.54.0")), \
             mock.patch.object(docling_reader, "_serialise_page",
                               side_effect=lambda doc, n: f"body {n}"):
            pages, version = docling_reader.read(Path("/tmp/r.pdf"))
        self.assertEqual(pages, [(1, "body 1"), (2, "body 2"), (3, "body 3")])
        self.assertEqual(version, "2.54.0")

    def test_a_docx_is_one_page(self):
        # A DOCX has no page provenance, so the whole body is page 1 - the same
        # convention intake._pages_of has always used, for the same reason.
        with mock.patch.object(docling_reader, "_convert",
                               return_value=(FakeResult(0), "2.54.0")), \
             mock.patch.object(docling_reader, "_serialise_whole",
                               return_value="the whole body"):
            pages, _ = docling_reader.read(Path("/tmp/r.docx"))
        self.assertEqual(pages, [(1, "the whole body")])

    @override_settings(DOCLING_ENABLED=False)
    def test_disabled_raises_rather_than_returning_nothing(self):
        # Returning [] would delete every DocumentText row and replace it with
        # nothing. A refusal has to be loud.
        with self.assertRaises(docling_reader.DoclingDisabled):
            docling_reader.read(Path("/tmp/r.pdf"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_docling_reader -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'insights.docling_reader'`.

- [ ] **Step 3: Write the module**

Create `insights/docling_reader.py`:

```python
"""The one place that knows what Docling looks like.

Everything else in the insights app asks for [(page_number, markdown)] and a
version string. That boundary is what lets convert.py be tested without model
weights, and what makes a Docling upgrade one file's problem.

WHY THE OCR ENGINE IS NAMED EXPLICITLY. Docling's default is OcrAutoOptions,
which probes the machine and picks an engine at pipeline init - and its own
documentation says language settings then fall back to that engine's internal
defaults, so DOCLING_OCR_LANGS would be silently ignored. On a CPU-only
container the probe lands on RapidOCR, whose supported-language list has no
Arabic at all. For an archive of Sudan and Chad reports that is disqualifying.
EasyOcrOptions takes ISO 639-1 codes, including 'ar' and 'fr'.
"""
from pathlib import Path

from django.conf import settings


class DoclingDisabled(RuntimeError):
    """DOCLING_ENABLED is off. Raised, never returned as an empty result."""


def _build_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    artifacts = str(settings.DOCLING_ARTIFACTS_PATH)
    options = PdfPipelineOptions(artifacts_path=artifacts)
    options.do_ocr = True
    options.do_table_structure = True
    # download_enabled=False so a missing weight fails here, loudly, instead of
    # quietly reaching for the internet inside a detached subprocess nobody is
    # watching.
    options.ocr_options = EasyOcrOptions(
        lang=list(settings.DOCLING_OCR_LANGS),
        download_enabled=False,
        model_storage_directory=artifacts,
    )
    options.document_timeout = settings.DOCLING_TIMEOUT_SECONDS
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _convert(path):
    """(result, version). Split out so the tests can stand in for it."""
    import docling

    converter = _build_converter()
    result = converter.convert(
        str(path), page_range=(1, settings.DOCLING_MAX_PAGES))
    return result, getattr(docling, "__version__", "unknown")


def _serialise_page(document, page_number):
    """That page's items, in reading order, as markdown.

    An item spanning a page break is serialised into BOTH pages: docling-core's
    page filter yields an item when any of its provenances matches. That is
    harmless and mildly useful - a quote from a table running across pages 3
    and 4 verifies against whichever page the model cites.
    """
    from docling_core.transforms.serializer.markdown import (
        MarkdownDocSerializer, MarkdownParams)

    return MarkdownDocSerializer(
        doc=document, params=MarkdownParams(pages={page_number})).serialize().text


def _serialise_whole(document):
    return document.export_to_markdown()


def read(path):
    """([(page_number, markdown)], docling_version). Raises on any failure."""
    if not settings.DOCLING_ENABLED:
        raise DoclingDisabled("DOCLING_ENABLED is off")

    result, version = _convert(Path(path))
    document = result.document

    page_numbers = sorted(getattr(document, "pages", {}) or {})
    if not page_numbers:
        # A DOCX, or anything else with no page provenance. Same convention as
        # intake._pages_of: the whole body is page 1, because a DOCX has no
        # pages until it is rendered.
        return [(1, _serialise_whole(document))], version

    return [(number, _serialise_page(document, number)) for number in page_numbers], version
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web python manage.py test insights.tests.test_docling_reader -v 2`
Expected: PASS, three tests.

- [ ] **Step 5: Commit**

```bash
git add insights/docling_reader.py insights/tests/test_docling_reader.py
git commit -m "feat: read a document into per-page markdown with Docling"
```

---

### Task 5: `insights/convert.py` — the orchestration

**Files:**
- Create: `insights/convert.py`
- Modify: `insights/intake.py` (rename `_pdf_metadata` → `pdf_metadata`, update its one caller)
- Test: `insights/tests/test_convert.py`

**Interfaces:**
- Consumes: `docling_reader.read`, `docling_reader.DoclingDisabled` (Task 4); `insights.models.Conversion` (Task 3); `intake.pdf_metadata`.
- Produces:
  - `convert.convert_document(document, path, job=None, reload_only=False) -> Conversion`. Never raises for a bad document.
  - `convert.cache_paths(document) -> tuple[Path, Path]` — `(json_path, md_path)`.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_convert.py`:

```python
"""Replacing a document's text, and refusing to when something depends on it."""
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import fitz
from data_track.models import Document, DocumentText
from django.test import TestCase, override_settings

from insights import convert, docling_reader
from insights.models import Conversion, ExtractionJob, Insight


def write_pdf(path, pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


class ConvertDocumentTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

        self.path = Path(self.tmp.name) / "report.pdf"
        write_pdf(self.path, ["raw page one", "raw page two"])

        self.document = Document.objects.create(
            file_name="report.pdf", rel_path="media/abc-report.pdf",
            source_collection="insights", family="insight_source",
            sha1="a" * 40, pages=2, report_date=date(2026, 3, 1))
        for number, text in ((1, "raw page one"), (2, "raw page two")):
            DocumentText.objects.create(document=self.document, page=number, text=text)

    def settings_override(self):
        return override_settings(MCP_CACHE_DIR=Path(self.cache.name))

    def fake_read(self, pages=None, version="2.54.0"):
        pages = pages or [(1, "## One\n\nmarkdown page one"), (2, "markdown page two")]
        return mock.patch.object(docling_reader, "read", return_value=(pages, version))

    def test_rows_are_replaced_with_the_markdown(self):
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        stored = list(DocumentText.objects.filter(document=self.document)
                      .order_by("page").values_list("page", "text"))
        self.assertEqual(stored, [(1, "## One\n\nmarkdown page one"), (2, "markdown page two")])
        self.assertEqual((row.engine, row.ok, row.pages), ("docling", True, 2))
        self.assertEqual(row.docling_version, "2.54.0")

    def test_the_markdown_is_written_to_disk_before_it_is_loaded(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
        json_path, md_path = convert.cache_paths(self.document)
        self.assertTrue(md_path.exists())
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["pages"][0]["page"], 1)
        self.assertEqual(payload["engine"], "docling")

    def test_a_failure_leaves_the_pymupdf_rows_alone(self):
        with self.settings_override(), \
             mock.patch.object(docling_reader, "read", side_effect=RuntimeError("boom")):
            row = convert.convert_document(self.document, self.path)
        stored = list(DocumentText.objects.filter(document=self.document)
                      .order_by("page").values_list("page", "text"))
        self.assertEqual(stored, [(1, "raw page one"), (2, "raw page two")])
        self.assertEqual((row.engine, row.ok), ("pymupdf", False))
        self.assertIn("RuntimeError: boom", row.message)

    def test_a_document_with_a_pending_insight_is_refused(self):
        # Not just published: a pending row is one a reviewer is about to judge
        # against a quote, and moving the page text under it makes that
        # judgement meaningless.
        # stated_on and iso3 are NOT NULL with no default - omitting them fails
        # on an IntegrityError long before the assertion below is reached.
        Insight.objects.create(document=self.document, page=1, iso3="SDN",
                               stated_on=date(2026, 3, 1), status="pending",
                               quote="a quote that is long enough")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "skipped")
        self.assertEqual(DocumentText.objects.get(document=self.document, page=1).text,
                         "raw page one")

    def test_a_document_whose_insights_were_all_rejected_is_converted(self):
        Insight.objects.create(document=self.document, page=1, iso3="SDN",
                               stated_on=date(2026, 3, 1), status="rejected",
                               quote="a quote that is long enough")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "docling")

    def test_a_missing_date_is_inferred_from_the_converted_text(self):
        # The payoff for OCR: intake could not read a date out of an empty
        # string, and now there is text to read one out of.
        self.document.report_date = None
        self.document.save(update_fields=["report_date"])
        pages = [(1, "Situation report, 14 June 2026"), (2, "more")]
        with self.settings_override(), self.fake_read(pages=pages):
            convert.convert_document(self.document, self.path)
        self.document.refresh_from_db()
        self.assertEqual(self.document.report_date, date(2026, 6, 14))

    def test_an_existing_date_is_not_overwritten(self):
        pages = [(1, "Situation report, 14 June 2026"), (2, "more")]
        with self.settings_override(), self.fake_read(pages=pages):
            convert.convert_document(self.document, self.path)
        self.document.refresh_from_db()
        self.assertEqual(self.document.report_date, date(2026, 3, 1))

    def test_reload_only_does_not_call_docling(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
        DocumentText.objects.filter(document=self.document).delete()
        with self.settings_override(), \
             mock.patch.object(docling_reader, "read",
                               side_effect=AssertionError("Docling was called")) as spy:
            row = convert.convert_document(self.document, self.path, reload_only=True)
        spy.assert_not_called()
        self.assertEqual(row.ok, True)
        self.assertEqual(DocumentText.objects.filter(document=self.document).count(), 2)

    def test_reload_only_with_no_cache_is_a_failure_not_a_crash(self):
        with self.settings_override():
            row = convert.convert_document(self.document, self.path, reload_only=True)
        self.assertFalse(row.ok)
        self.assertEqual(row.engine, "pymupdf")

    @override_settings(DOCLING_ENABLED=False)
    def test_disabled_leaves_the_rows_and_says_so(self):
        with self.settings_override():
            row = convert.convert_document(self.document, self.path)
        self.assertEqual(row.engine, "pymupdf")
        self.assertIn("disabled", row.message.lower())
        self.assertEqual(DocumentText.objects.count(), 2)

    def test_the_job_is_recorded_on_the_conversion(self):
        job = ExtractionJob.objects.create(status="converting")
        with self.settings_override(), self.fake_read():
            row = convert.convert_document(self.document, self.path, job=job)
        self.assertEqual(row.job_id, job.id)

    def test_converting_twice_keeps_one_row(self):
        with self.settings_override(), self.fake_read():
            convert.convert_document(self.document, self.path)
            convert.convert_document(self.document, self.path)
        self.assertEqual(Conversion.objects.filter(document=self.document).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_convert -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'insights.convert'`.

- [ ] **Step 3: Make `pdf_metadata` importable**

In `insights/intake.py`, rename `_pdf_metadata` to `pdf_metadata` (the `def` on line 71 and its single call inside `catalogue_file`), and extend its docstring with one sentence: *"Public because convert.py re-runs date inference after a successful conversion and needs the same metadata."*

- [ ] **Step 4: Write the module**

Create `insights/convert.py`:

```python
"""Read a document properly, then put that text where the model will find it.

THE RULE THIS KEEPS. The text the model reads and the text
verify.quote_is_verbatim checks a returned quote against are the same
DocumentText rows. So Docling's output does not go somewhere new - it REPLACES
those rows. Any design where the model gets markdown while DocumentText keeps
PyMuPDF text would send insights_rejected_unverifiable to essentially 100%
with nothing anywhere saying why.

WHY INTAKE STILL RUNS PyMuPDF. Not a hedge - a hazard fix.
data_pipeline/steps/s02_extract_text.py selects
Document.objects.filter(texts__isnull=True), so a document left textless
between intake and conversion would be picked up by any pipeline run and fail
there on a media/ path it cannot resolve. Those rows are a placeholder, and
they are also what the fallback below falls back TO.
"""
import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from data_track.models import DocumentText
from insights import docling_reader, document_date
from insights.intake import pdf_metadata
from insights.models import Conversion, Insight


def cache_paths(document):
    """(json, markdown). Content-addressed, so the same file re-read is the same pair."""
    root = Path(settings.MCP_CACHE_DIR) / "insights" / "converted"
    return root / f"{document.sha1}.json", root / f"{document.sha1}.md"


def _record(document, job, engine, ok, pages, message="", version="", markdown_path=""):
    """Write (or overwrite) this document's one Conversion row."""
    row, _ = Conversion.objects.update_or_create(
        document=document,
        defaults={
            "job": job, "engine": engine, "ok": ok, "pages": pages,
            "message": message or "", "docling_version": version or None,
            "markdown_path": markdown_path or None,
        },
    )
    return row


def _save_artifacts(document, pages, version):
    """Write the converted text to disk BEFORE it is loaded.

    The rule CLAUDE.md states for external data - fetch, save, then load - for
    the same reason: a re-load must not have to pay for OCR twice. The .json is
    the re-loadable one; the .md is for a person to open.
    """
    json_path, md_path = cache_paths(document)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps({
        "engine": "docling",
        "docling_version": version,
        "converted_at": timezone.now().isoformat(timespec="seconds"),
        "rel_path": document.rel_path,
        "sha1": document.sha1,
        "pages": [{"page": number, "markdown": text} for number, text in pages],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(
        "\n\n".join(f"<!-- page {number} -->\n{text}" for number, text in pages),
        encoding="utf-8")
    return md_path


def _load_artifacts(document):
    """[(page, markdown)] and the version from the cache, or None if absent."""
    json_path, _ = cache_paths(document)
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pages = [(int(item["page"]), item["markdown"]) for item in payload.get("pages", [])]
    return (pages, payload.get("docling_version", "")) if pages else None


def _replace_text(document, pages, path):
    """Swap this document's page rows for the converted ones, atomically.

    Atomic because a crash between the delete and the create leaves the
    document textless - which is exactly the s02 hazard the module docstring
    exists to avoid, and it would be permanent: for a media/-rooted upload s02
    cannot resolve the path either, so nothing would ever backfill it.
    """
    date_fields = []
    # Nobody has a date for this document. There is text now that there was not
    # before - a scanned report that gave PyMuPDF an empty string can finally
    # say when it was written. A guess whose sources disagree is still NOT
    # written: a wrong date mis-places every insight on the timeline.
    if document.report_date is None:
        guess = document_date.infer(path, pages, pdf_metadata(Path(path)))
        if guess.date is not None and not guess.needs_person:
            document.report_date, document.date_source = guess.date, guess.source
            date_fields = ["report_date", "date_source"]

    with transaction.atomic():
        DocumentText.objects.filter(document=document).delete()
        DocumentText.objects.bulk_create(
            [DocumentText(document=document, page=number, text=text)
             for number, text in pages], batch_size=200)
        document.pages = len(pages)
        document.save(update_fields=["pages"] + date_fields)


def convert_document(document, path, job=None, reload_only=False):
    """Read one document with Docling and replace its text. Returns a Conversion.

    NEVER RAISES FOR A BAD DOCUMENT. An unreadable file is an expected input in
    a folder of two hundred, not an exceptional one - the same judgement
    verify.quote_is_verbatim makes when it returns False for a missing page. A
    failure is a Conversion row with ok=False, and the batch carries on.
    """
    path = Path(path)

    # The one refusal. Replacing page text under an existing insight would
    # invalidate the quote it was verified against, with nothing afterwards
    # able to tell. Per document, not per job: a Document can belong to several.
    if Insight.objects.filter(document=document).exclude(status="rejected").exists():
        return _record(
            document, job, engine="skipped", ok=False, pages=document.pages,
            message=("Not re-read: insights still depend on this document's text. "
                     "Reject them first if it must be read again."))

    try:
        if reload_only:
            cached = _load_artifacts(document)
            if cached is None:
                raise FileNotFoundError(f"no cached conversion for {document.sha1}")
            pages, version = cached
            markdown_path = str(cache_paths(document)[1])
        else:
            pages, version = docling_reader.read(path)
            if not pages:
                raise ValueError("Docling returned no pages")
            markdown_path = str(_save_artifacts(document, pages, version))

        _replace_text(document, pages, path)
    except docling_reader.DoclingDisabled as exc:
        return _record(document, job, engine="pymupdf", ok=False, pages=document.pages,
                       message=f"Docling is disabled ({exc}); intake text left in place.")
    except Exception as exc:  # noqa: BLE001 - reported per document, see the docstring
        # Type and message only, never the repr.
        return _record(document, job, engine="pymupdf", ok=False, pages=document.pages,
                       message=f"{type(exc).__name__}: {exc}")

    return _record(document, job, engine="docling", ok=True, pages=len(pages),
                   version=version, markdown_path=markdown_path)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_convert insights.tests.test_intake -v 2`
Expected: PASS. `test_intake` is included because `pdf_metadata` was renamed in step 3.

- [ ] **Step 6: Commit**

```bash
git add insights/convert.py insights/intake.py insights/tests/test_convert.py
git commit -m "feat: replace a document's text with its Docling conversion"
```

---

### Task 6: The `convert_documents` command

**Files:**
- Create: `insights/management/commands/convert_documents.py`
- Test: `insights/tests/test_convert_command.py`

**Interfaces:**
- Consumes: `convert.convert_document` (Task 5).
- Produces: `manage.py convert_documents --job N [--reload-from-cache]`. Leaves the job at `converted` on success, `convert_failed` on a run-level failure.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_convert_command.py`:

```python
"""One bad document must not cost the other 199."""
import tempfile
from pathlib import Path
from unittest import mock

import fitz
from data_track.models import Document, DocumentText
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from insights import convert
from insights.models import Conversion, ExtractionJob


def make_document(tmp, name, sha1):
    path = Path(tmp) / name
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "raw text")
    doc.save(str(path))
    doc.close()
    document = Document.objects.create(
        file_name=name, rel_path=f"media/{sha1[:12]}-{name}",
        source_collection="insights", family="insight_source", sha1=sha1, pages=1)
    DocumentText.objects.create(document=document, page=1, text="raw text")
    return document, path


class ConvertCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

        self.job = ExtractionJob.objects.create(status="collected")
        self.good, _ = make_document(self.tmp.name, "good.pdf", "a" * 40)
        self.bad, _ = make_document(self.tmp.name, "bad.pdf", "b" * 40)
        self.job.documents.add(self.good, self.bad)
        self.job.documents_total = 2
        self.job.save()

    def run_command(self, **kwargs):
        with override_settings(MCP_CACHE_DIR=Path(self.cache.name)):
            call_command("convert_documents", job=self.job.id, **kwargs)
        self.job.refresh_from_db()

    def test_one_failure_does_not_stop_the_batch(self):
        def one_bad(document, path, job=None, reload_only=False):
            engine = "pymupdf" if document.sha1.startswith("b") else "docling"
            return Conversion.objects.create(
                document=document, job=job, engine=engine, ok=engine == "docling",
                pages=1, message="" if engine == "docling" else "RuntimeError: boom")

        with mock.patch.object(convert, "convert_document", side_effect=one_bad):
            self.run_command()

        self.assertEqual(self.job.status, "converted")
        self.assertEqual(self.job.documents_done, 2)
        self.assertIn("boom", self.job.log)

    def test_counts_are_reset_between_runs(self):
        self.job.documents_done = 7
        self.job.save(update_fields=["documents_done"])
        with mock.patch.object(convert, "convert_document",
                               side_effect=lambda document, path, job=None, reload_only=False:
                               Conversion.objects.create(document=document, job=job,
                                                         engine="docling", ok=True, pages=1)):
            self.run_command()
        self.assertEqual(self.job.documents_done, 2)

    def test_a_run_level_failure_lands_on_convert_failed(self):
        with mock.patch.object(convert, "convert_document",
                               side_effect=OSError("disk went away")):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertEqual(self.job.status, "convert_failed")
        self.assertIn("OSError: disk went away", self.job.log)

    def test_reload_from_cache_is_passed_through(self):
        seen = {}

        def record(document, path, job=None, reload_only=False):
            seen["reload_only"] = reload_only
            return Conversion.objects.create(document=document, job=job,
                                             engine="docling", ok=True, pages=1)

        with mock.patch.object(convert, "convert_document", side_effect=record):
            self.run_command(reload_from_cache=True)
        self.assertTrue(seen["reload_only"])

    def test_an_unknown_job_is_a_command_error(self):
        with self.assertRaises(CommandError):
            call_command("convert_documents", job=99999)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_convert_command -v 2`
Expected: FAIL — `CommandError: Unknown command: 'convert_documents'`.

- [ ] **Step 3: Write the command**

Create `insights/management/commands/convert_documents.py`:

```python
"""Read a job's documents with Docling, in-container, and replace their text.

    manage.py convert_documents --job 4
    manage.py convert_documents --job 4 --reload-from-cache

Mirrors extract_insights.py deliberately: the same per-document loop, the same
log discipline, the same CommandError on a run-level failure so a direct
`docker compose exec web python manage.py convert_documents` exits non-zero
rather than a quiet 0.

A PER-DOCUMENT FAILURE IS NOT A RUN FAILURE. convert_document never raises for
a bad document - it returns a Conversion with ok=False and leaves the intake
text in place. An unreadable PDF in a folder of two hundred must not take the
other 199 down. What reaches the except branch below is a real run failure -
the database went away, the disk filled - and that leaves the job at
"convert_failed" rather than wedged at "converting", which nothing but the
admin's reset action could recover.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from insights import convert
from insights.models import ExtractionJob


class Command(BaseCommand):
    help = "Convert a job's documents to per-page markdown with Docling."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, required=True)
        parser.add_argument(
            "--reload-from-cache", action="store_true", dest="reload_from_cache",
            help="Load mcp_cache/insights/converted/<sha1>.json instead of calling Docling.")

    def _log(self, job, message):
        self.stdout.write(message)
        stamp = timezone.now().isoformat(timespec="seconds")
        line = f"[{stamp}] {message}"
        job.log = f"{job.log}\n{line}" if job.log else line
        job.save(update_fields=["log"])

    def handle(self, *args, **options):
        job = ExtractionJob.objects.filter(id=options["job"]).first()
        if job is None:
            raise CommandError(f"no ExtractionJob with id {options['job']}")

        documents = list(job.documents.order_by("id"))
        job.status = "converting"
        job.started_at = timezone.now()
        job.documents_total = len(documents)
        # Re-running the same job on purpose must not inherit the previous
        # run's count - documents_done is incremented below, never set.
        job.documents_done = 0
        job.save()

        try:
            for document in documents:
                path = Path(settings.SOURCE_ROOT) / document.rel_path
                if not path.exists():
                    path = Path(settings.BASE_DIR) / document.rel_path
                row = convert.convert_document(
                    document, path, job=job,
                    reload_only=options["reload_from_cache"])

                detail = f" - {row.message}" if row.message else ""
                self._log(job, f"{document.file_name}: {row.engine}, "
                               f"{row.pages} page(s){detail}")

                job.documents_done += 1
                job.save(update_fields=["documents_done"])
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.stderr.write(message)
            job.log = f"{job.log}\n{message}" if job.log else message
            job.status = "convert_failed"
            job.finished_at = timezone.now()
            job.save(update_fields=["log", "status", "finished_at"])
            raise CommandError(message) from exc
        else:
            # NOT "queued". The operator has not looked at the converted text
            # yet, and step 2's whole purpose is that they can. The Continue
            # button on that page is what moves this on.
            job.status = "converted"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec web python manage.py test insights.tests.test_convert_command -v 2`
Expected: PASS, five tests.

- [ ] **Step 5: Commit**

```bash
git add insights/management/commands/convert_documents.py insights/tests/test_convert_command.py
git commit -m "feat: add convert_documents, the detached per-job read"
```

---

### Task 7: The job's new states, and every caller that sets one

**Files:**
- Modify: `insights/models.py` (`ExtractionJob.status` help text)
- Modify: `insights/wizard.py` (`batch_ready`)
- Modify: `insights/intake.py` (`catalogue_folder`)
- Modify: `insights/admin.py:217`, `:268`, `reset_stuck_job` at `:306-333`
- Test: `insights/tests/test_job_states.py`; update `insights/tests/test_wizard_batch.py`, `insights/tests/test_intake.py`, `insights/tests/test_admin.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the vocabulary `collecting / collected / converting / converted / convert_failed / queued / running / failed / loaded`. `queued` now means **converted and ready to extract**.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_job_states.py`:

```python
"""Where a batch goes when its files are in, and how a stuck read is recovered."""
import tempfile
from pathlib import Path

import fitz
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights.models import ExtractionJob, InsightFolder


class BatchReadyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_closing_a_batch_leaves_it_ready_to_read_not_to_extract(self):
        job = ExtractionJob.objects.create(status="collecting")
        self.client.post(reverse("admin:insights_wizard_batch_ready", args=[job.id]))
        job.refresh_from_db()
        self.assertEqual(job.status, "collected")


class CatalogueFolderTests(TestCase):
    def test_a_registered_folder_opens_at_collected(self):
        from insights.intake import catalogue_folder

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "text")
        doc.save(str(Path(tmp.name) / "r.pdf"))
        doc.close()

        folder = InsightFolder.objects.create(label="f", path=tmp.name)
        job = catalogue_folder(folder)
        self.assertEqual(job.status, "collected")


class ResetStuckJobTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def reset(self, job):
        self.client.post(reverse("admin:insights_extractionjob_changelist"), {
            "action": "reset_stuck_job", "_selected_action": [job.id], "index": "0"})
        job.refresh_from_db()
        return job

    def test_a_stuck_extraction_goes_back_to_queued(self):
        job = ExtractionJob.objects.create(status="running")
        self.assertEqual(self.reset(job).status, "queued")

    def test_a_stuck_read_goes_back_to_collected(self):
        # Back to where the read is launched from, not to where extraction is:
        # a killed conversion has not converted anything.
        job = ExtractionJob.objects.create(status="converting")
        self.assertEqual(self.reset(job).status, "collected")

    def test_a_finished_job_is_left_alone(self):
        job = ExtractionJob.objects.create(status="loaded")
        self.assertEqual(self.reset(job).status, "loaded")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_job_states -v 2`
Expected: FAIL — `batch_ready` produces `queued`, `catalogue_folder` produces `queued`, and `reset_stuck_job` leaves `converting` untouched.

- [ ] **Step 3: Update the status vocabulary**

In `insights/models.py`, replace `ExtractionJob.status`'s `help_text` with:

```python
        help_text=(
            "collecting / collected / converting / converted / convert_failed / "
            "queued / running / loaded / failed. 'collecting' is a wizard batch "
            "whose files are still arriving; 'collected' is one whose files are in "
            "but not yet read; 'converted' is read and waiting for a person to look "
            "at the text before paying the model. 'queued' therefore means CONVERTED "
            "and ready to extract. A job stuck at 'running' or 'converting' because "
            "its process was killed rather than raising (e.g. docker compose restart "
            "web) can be recovered with the 'Reset stuck job to queued' action below."
        ),
```

- [ ] **Step 4: Update the three places that open a job**

`insights/wizard.py`, in `batch_ready`:

```python
    job.status = "collected"
```

`insights/intake.py`, in `catalogue_folder`:

```python
    job = ExtractionJob.objects.create(folder=folder, producer="external", status="collected")
```

`insights/admin.py:268`, in the single-upload action:

```python
            producer="external", status="collected", documents_total=1)
```

And at `insights/admin.py:217`, change the message's word "queued" to "ready to read":

```python
                f"{folder.label}: {job.documents_total} documents catalogued, job {job.id} "
                f"ready to read. "
```

- [ ] **Step 5: Teach `reset_stuck_job` about a stuck read**

In `insights/admin.py`, replace the body of `reset_stuck_job` from the `stuck = ...` line:

```python
        # Two stages can be killed mid-flight, and each goes back to the page it
        # is launched from. A killed conversion has converted nothing, so it
        # returns to "collected" - sending it to "queued" would march it past
        # the read step with intake's PyMuPDF text still in the database.
        stuck = queryset.filter(status="running")
        updated = stuck.count()
        stuck.update(status="queued")

        stuck_read = queryset.filter(status="converting")
        updated += stuck_read.count()
        stuck_read.update(status="collected")
```

Keep the existing `self.message_user(...)` call, adjusting its text to `f"{updated} job(s) reset."`.

- [ ] **Step 6: Update the tests this breaks**

In `insights/tests/test_wizard_batch.py`, `insights/tests/test_intake.py` and `insights/tests/test_admin.py`, change every assertion expecting `"queued"` immediately after a batch is closed, a folder is catalogued, or a single file is uploaded, to expect `"collected"`. Find them with:

```bash
docker compose exec web grep -rn '"queued"' insights/tests/
```

Leave assertions about `reset_stuck_job` on a `running` job alone — that path is unchanged.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: PASS everywhere except `test_wizard_steps` and `test_wizard_extract`, which Task 8 fixes. Note which of those fail; they should be only about step 2's URL and about reaching the extract page.

- [ ] **Step 8: Migrate, restart, commit**

```bash
docker compose exec web python manage.py makemigrations insights
docker compose exec web python manage.py migrate
docker compose restart web
git add insights/models.py insights/migrations/ insights/wizard.py insights/intake.py insights/admin.py insights/tests/
git commit -m "feat: add the read states between collecting and queued"
```

---

### Task 8: Step 2 becomes a page

**Files:**
- Modify: `insights/wizard.py` (`STEPS`, `step_links`, `job_step`, `log_path`, `progress`, new `read` and `read_done`)
- Modify: `insights/admin.py` (two `path(...)` entries in `DocumentsToInsightsAdmin.get_urls`)
- Create: `insights/templates/insights/wizard_read.html`
- Create: `insights/static/insights/wizard_read.js`
- Test: `insights/tests/test_wizard_read.py`; update `insights/tests/test_wizard_steps.py`

**Interfaces:**
- Consumes: the statuses from Task 7; `Conversion` from Task 3.
- Produces: `admin:insights_wizard_read` (POST, launches), `admin:insights_wizard_read_done` (POST, `converted` → `queued`). `wizard.log_path(job, stage="extract") -> Path`.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_wizard_read.py`:

```python
"""Step 2: the page that shows what the model will actually read."""
from unittest import mock

from data_track.models import Document, DocumentText
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights import wizard
from insights.models import Conversion, ExtractionJob


class WizardReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.job = ExtractionJob.objects.create(status="collected", documents_total=1)
        self.document = Document.objects.create(
            file_name="report.pdf", rel_path="media/abc-report.pdf",
            source_collection="insights", family="insight_source", sha1="a" * 40, pages=1)
        self.job.documents.add(self.document)

    def job_url(self):
        return reverse("admin:insights_wizard_job", args=[self.job.id])

    def test_a_collected_job_lands_on_the_read_page(self):
        response = self.client.get(self.job_url())
        self.assertTemplateUsed(response, "insights/wizard_read.html")

    def test_the_read_button_launches_the_command(self):
        with mock.patch("insights.wizard.subprocess.Popen") as popen:
            response = self.client.post(
                reverse("admin:insights_wizard_read", args=[self.job.id]))
        self.assertTrue(response.json()["started"])
        self.assertIn("convert_documents", popen.call_args.args[0])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "converting")

    def test_a_second_click_does_not_launch_a_second_read(self):
        self.job.status = "converting"
        self.job.save(update_fields=["status"])
        with mock.patch("insights.wizard.subprocess.Popen") as popen:
            response = self.client.post(
                reverse("admin:insights_wizard_read", args=[self.job.id]))
        self.assertFalse(response.json()["started"])
        popen.assert_not_called()

    def test_the_converted_page_shows_the_text_and_the_engine(self):
        DocumentText.objects.create(document=self.document, page=1,
                                    text="## Displacement\n\nthe converted text")
        Conversion.objects.create(document=self.document, job=self.job,
                                  engine="docling", ok=True, pages=1)
        self.job.status = "converted"
        self.job.save(update_fields=["status"])
        body = self.client.get(self.job_url()).content.decode()
        self.assertIn("the converted text", body)
        self.assertIn("Docling", body)

    def test_a_fallback_is_badged_with_its_reason(self):
        DocumentText.objects.create(document=self.document, page=1, text="raw text")
        Conversion.objects.create(document=self.document, job=self.job, engine="pymupdf",
                                  ok=False, pages=1, message="RuntimeError: boom")
        self.job.status = "converted"
        self.job.save(update_fields=["status"])
        body = self.client.get(self.job_url()).content.decode()
        self.assertIn("Docling failed", body)
        self.assertIn("RuntimeError: boom", body)

    def test_continue_moves_the_job_to_queued(self):
        self.job.status = "converted"
        self.job.save(update_fields=["status"])
        self.client.post(reverse("admin:insights_wizard_read_done", args=[self.job.id]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "queued")

    def test_continue_is_refused_from_any_other_state(self):
        self.client.post(reverse("admin:insights_wizard_read_done", args=[self.job.id]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "collected")

    def test_progress_reads_the_convert_log_while_converting(self):
        self.job.status = "converting"
        self.job.save(update_fields=["status"])
        path = wizard.log_path(self.job, "convert")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reading report.pdf", encoding="utf-8")
        self.addCleanup(path.unlink, True)
        payload = self.client.get(
            reverse("admin:insights_wizard_progress", args=[self.job.id])).json()
        self.assertIn("reading report.pdf", payload["log_tail"])


class WizardStepTwoLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_step_two_links_to_the_job_once_it_is_collected(self):
        job = ExtractionJob.objects.create(status="collected")
        links = wizard.step_links(job, current=2)
        self.assertIsNone(links[1]["url"])  # current step is never a link
        links = wizard.step_links(job, current=1)
        self.assertEqual(links[1]["url"],
                         reverse("admin:insights_wizard_job", args=[job.id]))

    def test_step_two_is_inert_once_the_batch_has_moved_on(self):
        job = ExtractionJob.objects.create(status="loaded")
        self.assertIsNone(wizard.step_links(job, current=4)[1]["url"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_wizard_read -v 2`
Expected: FAIL — `NoReverseMatch: 'insights_wizard_read' is not a registered namespace`.

- [ ] **Step 3: Rework `wizard.py`**

Change `STEPS`:

```python
STEPS = (
    (1, "Bring documents in"),
    (2, "Read these documents"),
    (3, "Extract"),
    (4, "Review and publish"),
)

READ_STATUSES = ("collected", "converting", "converted", "convert_failed")
```

Replace `step_links`'s `urls` dict and rewrite its docstring's last paragraph:

```python
    urls = {
        1: job_url if status == "collecting" else reverse("admin:insights_wizard_start"),
        2: job_url if status in READ_STATUSES else None,
        3: job_url if status in ("queued", "running", "failed") else None,
        4: job_url if status == "loaded" else None,
    }
```

The docstring paragraph beginning *"Step 2 never has one"* is now false. Replace it with:

```
    Step 2 is a page of its own now: Docling converts each document to
    per-page markdown there, and the text it produces is what the model reads
    and what verify.quote_is_verbatim checks a quote against. It leads
    somewhere only while the batch is still at that stage - once a batch is
    extracting, going "back" to the read step would offer to replace the text
    under insights that are already being written against it.
```

Rewrite `job_step`'s dispatch:

```python
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status == "collecting":
        return render(request, "insights/wizard_intake.html",
                      page(request, job=job, wizard_step=1))
    if job.status in READ_STATUSES:
        return render(request, "insights/wizard_read.html",
                      page(request, job=job, wizard_step=2,
                           documents=_job_documents(job)))
    if job.status in ("queued", "running", "failed"):
        return render(request, "insights/wizard_extract.html",
                      page(request, job=job, wizard_step=3))
    return render(request, "insights/wizard_review.html",
                  page(request, job=job, wizard_step=4, insights=_job_insights(job)))
```

Add beside `_job_insights`:

```python
def _job_documents(job):
    """This batch's documents with how each was read, and the text itself.

    The text is shown as it is stored, not rendered: the promise of this page
    is "what the model will read", and rendering the markdown would show
    something else.
    """
    documents = (job.documents.select_related("conversion")
                 .prefetch_related("texts").order_by("file_name"))
    return [{
        "document": document,
        "conversion": getattr(document, "conversion", None),
        "text": "\n\n".join(
            f"--- page {row.page} ---\n{row.text or ''}"
            for row in sorted(document.texts.all(), key=lambda r: r.page)),
    } for document in documents]
```

Replace `log_path` and the log lookup in `progress`:

```python
def log_path(job, stage="extract"):
    """Where a detached run writes its output. One file per stage.

    Separate files because the two stages have separate failure stories, and a
    reader of the extract log should not have to scroll past an OCR run to
    find where the model refused a chunk.
    """
    name = f"job-{job.id}.log" if stage == "extract" else f"job-{job.id}-{stage}.log"
    return Path(settings.MCP_CACHE_DIR) / "insights" / name


def _stage_of(job):
    return "convert" if job.status in READ_STATUSES else "extract"
```

In `progress`, change `path = log_path(job)` to `path = log_path(job, _stage_of(job))`.

Add the two views, after `batch_ready`:

```python
@require_POST
def read(request, job_id):
    """Launch the Docling conversion as a detached background process.

    Detached for the same two reasons extraction is: a gunicorn worker
    recycling mid-run must not kill it, and closing this tab must not either.
    With OCR on every page this is the longer of the two runs, not the shorter.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)

    if job.status == "converting":
        # A double click must not run two conversions of the same job: both
        # would delete and rebuild the same DocumentText rows, and the loser
        # could commit its delete after the winner's insert.
        return JsonResponse({"started": False, "message": "This batch is already being read."})

    path = log_path(job, "convert")
    path.parent.mkdir(parents=True, exist_ok=True)

    job.status = "converting"
    job.save(update_fields=["status"])

    with open(path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "manage.py", "convert_documents", "--job", str(job.id)],
            cwd=settings.BASE_DIR,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    return JsonResponse({"started": True, "message": "Reading started."})


@require_POST
def read_done(request, job_id):
    """The Continue button: the operator has looked at the text, so queue it.

    This, and not the end of the conversion, is what reaches "queued". If the
    command set it directly, reopening the batch would route straight past this
    page to the extract step, and step 2 would once again be a step nobody can
    stand on.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status != "converted":
        return JsonResponse({"moved": False, "message": "This batch has not been read yet."})
    job.status = "queued"
    job.save(update_fields=["status"])
    return JsonResponse({"moved": True})
```

- [ ] **Step 4: Register the URLs**

In `insights/admin.py`, inside `DocumentsToInsightsAdmin.get_urls()`, after the `batch_ready` entry:

```python
            path("job/<int:job_id>/read/", self.admin_site.admin_view(wizard.read),
                 name="insights_wizard_read"),
            path("job/<int:job_id>/read-done/", self.admin_site.admin_view(wizard.read_done),
                 name="insights_wizard_read_done"),
```

- [ ] **Step 5: Write the template**

Create `insights/templates/insights/wizard_read.html`:

```html
{% extends "insights/wizard_base.html" %}
{% load static %}
{% block wizard_body %}
<div id="wiz-read"
     data-progress-url="{% url 'admin:insights_wizard_progress' job.id %}"
     data-read-url="{% url 'admin:insights_wizard_read' job.id %}"
     data-done-url="{% url 'admin:insights_wizard_read_done' job.id %}"
     data-job-url="{% url 'admin:insights_wizard_job' job.id %}"
     data-status="{{ job.status }}">
  {% csrf_token %}

  <h2>{{ job.label|default:job }}</h2>
  <p>
    {{ job.documents_total }} document(s). Reading converts each one to text the
    model can follow &mdash; headings, lists and tables kept, and scanned pages
    read by OCR. This is the slow step; extraction is the one that costs money.
  </p>

  <p><button type="button" id="wiz-start" class="default">Read these documents</button></p>

  <div class="wiz-bar"><span id="wiz-bar-fill"></span></div>
  <p id="wiz-counters">Not started.</p>

  <div id="wiz-note" class="wiz-note" hidden></div>

  {% comment %}
  Same recovery path as the extract step: a detached child killed outright
  leaves the job at "converting" with no exception anywhere to catch. The
  changelist action is posted rather than reimplemented.
  {% endcomment %}
  <div id="wiz-stall" class="wiz-note is-warn" hidden>
    <p id="wiz-stall-text"></p>
    <form method="post" action="{% url 'admin:insights_extractionjob_changelist' %}">
      {% csrf_token %}
      <input type="hidden" name="action" value="reset_stuck_job">
      <input type="hidden" name="_selected_action" value="{{ job.id }}">
      <input type="hidden" name="index" value="0">
      <button type="submit">Reset this batch</button>
    </form>
  </div>

  {% if job.status == "converted" %}
  <h3>What the model will read</h3>
  {% for item in documents %}
    <div class="wiz-doc">
      <h4>{{ item.document.file_name }}</h4>
      {% if item.conversion and item.conversion.ok %}
        <p class="wiz-badge is-ok">Docling &middot; {{ item.conversion.pages }} page(s)</p>
      {% else %}
        <p class="wiz-badge is-warn">
          Raw text &mdash; Docling failed
          {% if item.conversion.message %}<br>{{ item.conversion.message }}{% endif %}
        </p>
      {% endif %}
      <pre class="wiz-doc-text">{{ item.text }}</pre>
    </div>
  {% endfor %}

  <p><button type="button" id="wiz-continue" class="default">Continue to extract</button></p>
  {% endif %}

  <h3>Log</h3>
  <pre class="wiz-log" id="wiz-log"></pre>

  <p>
    Closing this page does not stop the reading. Come back to this batch from
    <a href="{% url 'admin:insights_documentstoinsights_changelist' %}">Part 1</a>.
  </p>
</div>
<script src="{% static 'insights/wizard_read.js' %}" defer></script>
{% endblock %}
```

- [ ] **Step 6: Write the JavaScript**

Start from a copy: `cp insights/static/insights/wizard_extract.js insights/static/insights/wizard_read.js`. It is 131 lines and every other part of it — `STALL_MS`, `POLL_MS`, `csrf()`, `say()`, `stop()`, `poll()`, `watch()`, and the bar-drawing arithmetic in `draw()` — is wanted here unchanged. Then make exactly these five edits:

1. **Line 15**, the root lookup: `document.getElementById("wiz-extract")` → `document.getElementById("wiz-read")`.

2. **Line 111**, the launch fetch: `root.dataset.extractUrl` → `root.dataset.readUrl`.

3. **In `draw()`, replace the `body.status === "loaded"` branch** (line 59, which currently navigates to `root.dataset.reviewUrl`) with a reload. The preview is rendered by Django from `_job_documents`, not assembled in JS, so the page has to come back from the server to show it:

```javascript
    if (body.status === "converted") {
      stop();
      say("Reading finished. Showing what the model will read…", "ok");
      window.location.reload();
      return;
    }
```

4. **In `draw()`, change the two remaining status literals** to this step's vocabulary: `body.status === "failed"` (line 67) → `body.status === "convert_failed"`, and `body.status === "running"` (lines 77 and 129) → `body.status === "converting"`.

5. **Append the Continue handler** before the closing `})();`:

```javascript
  var continueButton = document.getElementById("wiz-continue");
  if (continueButton) {
    continueButton.addEventListener("click", function () {
      continueButton.disabled = true;
      fetch(root.dataset.doneUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf() },
      }).then(function (response) { return response.json(); })
        .then(function (body) {
          if (body.moved) {
            window.location = root.dataset.jobUrl;
          } else {
            continueButton.disabled = false;
            say(body.message, "warn");
          }
        });
    });
  }
```

- [ ] **Step 7: Update `test_wizard_steps.py`**

The assertion that step 2 is an always-disabled button is now false for a job that has been collected. Change `test_step_2_is_a_button_the_intake_page_switches_on` to keep asserting the inert-button shape **only on the intake page with no job** (which is still true — `step_links(None, 1)` gives step 2 no URL), and let `WizardStepTwoLinkTests` in `test_wizard_read.py` cover the linked case.

- [ ] **Step 8: Run the whole insights suite**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: PASS, everything.

- [ ] **Step 9: Restart and look at it**

```bash
docker compose restart web
```

Open Admin → Community insights → Part 1, start a batch, upload one real PDF from the archive, and press "Read these documents". Confirm: the progress bar moves, the log fills, the page reloads into the preview, the engine badge says Docling, and the text in the panel has headings and table rows rather than a column of loose numbers.

- [ ] **Step 10: Commit**

```bash
git add insights/wizard.py insights/admin.py insights/templates/insights/wizard_read.html insights/static/insights/wizard_read.js insights/tests/
git commit -m "feat: make step 2 the page where documents are read"
```

---

### Task 9: The prompt, the docs and the example env

**Files:**
- Modify: `insights/prompts/extract_insights.md`
- Modify: `env.example`
- Modify: `CLAUDE.md`
- Test: `insights/tests/test_extractors.py` (existing; add one assertion)

**Interfaces:**
- Consumes: everything above.
- Produces: no code interface.

- [ ] **Step 1: Write the failing test**

Append to `insights/tests/test_extractors.py`:

```python
class PromptMentionsMarkdownTests(TestCase):
    """The model is now reading markdown, and its quotes are matched against it.

    verify._fold_markup absorbs the markers on both sides, so a quote carrying
    them still matches - but a model told nothing may quote a whole table row
    with its pipes, and the fold cannot rescue a quote that spans a row break.
    """

    def test_the_prompt_says_the_text_is_markdown(self):
        from insights.extractors import prompt_text

        body = prompt_text().lower()
        self.assertIn("markdown", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_extractors -v 2`
Expected: FAIL — `AssertionError: 'markdown' not found`.

- [ ] **Step 3: Update the prompt**

In `insights/prompts/extract_insights.md`, in the section describing the page text the model is given, add:

```markdown
The page text is **markdown** produced from the original PDF or Word file:
headings carry `#`, emphasis carries `*`, and a table is a row of `|` cells.
Quote the document's **words**, not its markup — drop the `**` and the `|`
from anything you quote, and never quote across a table row break. A quote is
checked against the page it cites, and markup is folded on both sides before
that check, so the words are what has to match.
```

- [ ] **Step 4: Update `env.example`**

Add beside `IPC_API_KEY` and `HDX_API_TOKEN`:

```bash
# Reading documents for the insights wizard. Docling converts each PDF or Word
# file to per-page markdown before the model reads it; PyMuPDF is the per-
# document fallback when Docling fails. An empty value falls back to the
# default, so commenting a line out and blanking it do the same thing.
DOCLING_ENABLED=true
# ISO 639-1 codes for the OCR engine. Arabic and French are on by default
# because this archive is Sudan and Chad; each language costs image size and
# some speed per page.
DOCLING_OCR_LANGS=en,fr,ar
DOCLING_MAX_PAGES=40
DOCLING_TIMEOUT_SECONDS=900
DOCLING_ARTIFACTS_PATH=/opt/docling/models
```

- [ ] **Step 5: Update `CLAUDE.md`**

In §"2. Extract community insights from documents", replace the sentence describing the route in with one naming five steps, and add this paragraph after it:

```markdown
**Documents are read with Docling before the model sees them.** Step 2, "Read
these documents", converts each PDF or Word file to per-page markdown —
reading order, tables and headings kept, scanned pages OCR'd — and **replaces**
the PyMuPDF text intake wrote. That replacement is the point: `verify.py`
re-matches every quote against the same `DocumentText` rows the model read, so
the two must never diverge. A document Docling cannot convert keeps its intake
text and is badged on the preview; a re-read always tries Docling again first.
A document that already has a non-rejected insight is refused, because moving
the page text under a quote that was verified against it would invalidate that
check with nothing left to say so. Terminal equivalent:
`docker compose exec web python manage.py convert_documents --job N`.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: PASS, the whole app.

- [ ] **Step 7: Run the whole suite**

Run: `docker compose exec web python manage.py test -v 2`
Expected: PASS. `data_pipeline` and `data_track` were not modified; a failure there means something in this plan reached further than it should have.

- [ ] **Step 8: Commit**

```bash
git add insights/prompts/extract_insights.md env.example CLAUDE.md insights/tests/test_extractors.py
git commit -m "docs: describe the read step and its settings"
```

---

## Final verification

These are the checks no unit test stands in for. Run them on real documents from the archive before calling the feature done.

- [ ] **A two-column report.** Read one, open the preview, and confirm the columns are no longer interleaved. This is the failure that was silently producing quotes for sentences that never existed.
- [ ] **A report with a displacement table.** Confirm the table appears as rows with their labels attached, not as a column of loose numbers.
- [ ] **A scanned report.** Confirm it produces text at all. Before this change it produced an empty string, was sent to the model anyway, and returned nothing with no indication why. Then extract it and confirm at least one insight survives `quote_is_verbatim` — that is the end-to-end proof that OCR text and the verification gate agree.
- [ ] **A deliberately corrupt PDF** (truncate one with `head -c 2000`). Confirm the batch finishes, that document is badged "Docling failed" with its reason, and its intake text is still in the database.
- [ ] **Measure and record the real conversion time** for a 40-page report: `time docker compose exec web python manage.py convert_documents --job N`. The spec asserts minutes rather than seconds but does not claim a number. Put the measured figure in the spec's §11 as a replacement for the estimate.
- [ ] **Confirm the image size** with `docker images | grep web`, against Task 1 step 7's note.
