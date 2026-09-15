# Insights Intake Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the six-screen insights admin with one guided wizard — native file/folder pickers → preview → watchable extraction → inline review and publish — and remove every hardcoded `/work` path from the codebase.

**Architecture:** A proxy model over `ExtractionJob` puts the wizard on the admin index; its four steps are admin-mounted views hanging off `get_urls()`. Files arrive one HTTP request per file from a native OS picker; extraction stays a detached child process whose progress is polled from the database and the job's log file; review reuses `InsightPlaceForm` itself, fetched per row, so place resolution stays derived rather than typed.

**Tech Stack:** Django 5.0.6, PostgreSQL/PostGIS, PyMuPDF, python-docx, gunicorn (gthread, 2×4), vanilla JavaScript (no build step, no framework), WhiteNoise for static files.

**Spec:** `docs/superpowers/specs/2026-09-15-insights-intake-wizard-design.md`

## Global Constraints

- **Everything runs in Docker. There is no Django environment on the host.** Every command in this plan is `docker compose exec web python manage.py <command>`, run from the repository root (the folder holding `docker-compose.yml`).
- **Run the tests as** `docker compose exec web python manage.py test insights -v 2`.
- **`/work` is mounted read-only.** Anything written goes under `/app`.
- **No user-facing string may contain `/work`** or any other deployment-specific path. Messages name the configured roots at runtime.
- **Settings use `os.environ.get(X, default)` by default**; use `get(X) or default` (or `env_path()`) only when an empty `.env` value must fall back to the default instead of being treated as empty. Every new setting in this plan is the second kind.
- **Nothing here writes to `population_figures`, `movement_flows`, `narrative_tags` or `events`** — `s03_parse` and `s04_events` delete and rebuild those on every run.
- **The `insights` app is never written to by any pipeline step.** That stays true.
- **Only an exception's type and message are ever recorded** — never its repr, and never the request/response object an SDK exception may carry, which can carry the `Authorization` header, which carries `LLM_API_KEY`.
- **Python style:** match the surrounding files — module docstrings that explain *why*, comments that record the trap being avoided, British spelling in prose (`catalogue`), 4-space indent, ~90 column lines.
- **Commit messages:** `insights: <what changed>`, imperative, ending with the two attribution lines used on this branch:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP
  ```

---

## File Structure

**New files:**

| File | Responsibility |
|---|---|
| `insights/document_roots.py` | The one place that answers "which folders may documents be read from" and phrases the sentence that says so. Imported by `models.py`, `intake.py` and `admin_views.py`. |
| `insights/review.py` | `publish(queryset, user)` / `reject(queryset, user)` — one implementation, used by both the changelist actions and the wizard. |
| `insights/wizard.py` | The wizard's views: the four steps, the batch endpoints, the progress endpoint, the inline edit panel. |
| `insights/templates/insights/wizard_base.html` | Shared chrome: the four-step header, extending `admin/base_site.html`. |
| `insights/templates/insights/wizard_intake.html` | Step 1 + 2: the two pickers and the preview list. |
| `insights/templates/insights/wizard_extract.html` | Step 3: the progress bar, counters and log tail. |
| `insights/templates/insights/wizard_review.html` | Step 4: the read-only results list. |
| `insights/templates/insights/_edit_panel.html` | One insight's edit form, fetched per row. |
| `insights/templates/insights/_review_row.html` | One insight in read mode. Rendered by the review page and returned after a successful inline save. |
| `insights/static/insights/wizard_intake.js` | Native pickers, client-side filtering, sequential upload. |
| `insights/static/insights/wizard_extract.js` | Polling, progress bar, stall detection. |
| `insights/static/insights/wizard_review.js` | Edit-panel fetch, formset row adding, selection. |
| `insights/migrations/0004_wizard_models.py` | `collecting` status, `label`, the proxy model, the two `verbose_name_plural` changes. |

**Modified files:**

| File | Change |
|---|---|
| `config/settings.py:50` | Add `env_paths()` and `INSIGHT_DOCUMENT_ROOTS`. |
| `insights/models.py` | `ExtractionJob.label`, status help text, `DocumentsToInsights` proxy, `Insight.Meta.verbose_name_plural`, `InsightFolder.clean` message. |
| `insights/intake.py` | `catalogue_folder`'s message. |
| `insights/admin_views.py` | `_roots()` delegates to `document_roots`; `folder_browse`'s message. |
| `insights/admin.py` | `get_model_perms` on three admins; actions call `insights/review.py`; register `DocumentsToInsightsAdmin`. |
| `insights/forms.py` | `data-place-role` attributes; `InsightInlineEditForm`. |
| `insights/static/insights/place_picker.js` | Bind to a container by data attribute, not to hardcoded ids. |
| `docker-compose.yml:141` | `${SOURCE_HOST_DIR:-..}`. |
| `env.example` | `SOURCE_HOST_DIR`, `INSIGHT_DOCUMENT_ROOTS`. |
| `.gitignore` | `media/`. |
| `CLAUDE.md` | The wizard is the documented route in. |

---

### Task 0: Establish the baseline

The working tree carries unfinished work from an earlier session, and every later task builds directly on it. Nothing new is written until it is either committed or consciously discarded.

**Files:**
- Inspect: `insights/admin.py` (81 uncommitted lines), `insights/admin_views.py`, `insights/forms.py`, `insights/static/insights/`, `insights/tests/test_admin_pickers.py` (all untracked)

**Interfaces:**
- Consumes: nothing
- Produces: a green `insights` test suite on a clean working tree. Every later task assumes `InsightPlaceForm`, `InsightFolderForm`, `InsightUploadForm`, `admin_views.place_options`, `admin_views.folder_browse`, `place_picker.js` and `folder_picker.js` exist and pass their tests.

- [ ] **Step 1: See exactly what is uncommitted**

```bash
git status --short "Community Centered Humanitarian Analysis Platform/insights/"
git diff "Community Centered Humanitarian Analysis Platform/insights/admin.py"
```

Expected: `admin.py` modified; `admin_views.py`, `forms.py`, `static/`, `tests/test_admin_pickers.py` untracked. The diff adds `form = InsightPlaceForm`, a `resolved_to` readonly display, `get_urls()` on two admins, and rewrites the "Where" fieldset into country/state/district.

- [ ] **Step 2: Run the whole insights suite against it**

```bash
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS. If anything fails, **stop and report** — do not start Task 1. A failure here is pre-existing, and diagnosing it while also building a wizard is how a half-finished picker gets mistaken for a new bug.

- [ ] **Step 3: Commit the WIP as its own change**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/admin.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin_views.py" \
        "Community Centered Humanitarian Analysis Platform/insights/forms.py" \
        "Community Centered Humanitarian Analysis Platform/insights/static/" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_admin_pickers.py"
git commit -m "insights: pick a place and browse a folder instead of typing either

The Where fieldset was five text boxes holding values a person does not
have - a p-code typed by hand is how an insight lands on the wrong polygon.
It is now country/state/district dropdowns, with the five machine columns
derived from the pick and shown read-only beside them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

- [ ] **Step 4: Confirm the tree is clean apart from the dashboard data files**

```bash
git status --short
```

Expected: only `dashboard/data/*.json` and `data_pipeline/mcp_cache/insights/` remain — pipeline output and cache, not code.

---

### Task 1: One configurable list of document roots

Kills the `/work` peg. Five places hardcode it; after this task none do.

**Files:**
- Create: `Community Centered Humanitarian Analysis Platform/insights/document_roots.py`
- Modify: `config/settings.py` (after `MCP_CACHE_DIR`, ~line 50)
- Modify: `insights/admin_views.py` (`_roots`, `folder_browse`)
- Modify: `insights/intake.py` (`catalogue_folder`)
- Modify: `insights/models.py` (`InsightFolder.clean`)
- Modify: `docker-compose.yml:141`, `env.example`, `.gitignore`
- Test: `insights/tests/test_document_roots.py`

**Interfaces:**
- Consumes: Task 0's baseline.
- Produces:
  - `settings.INSIGHT_DOCUMENT_ROOTS: list[Path]`
  - `insights.document_roots.roots() -> list[tuple[str, Path]]` — `(label, resolved path)`, existing directories only
  - `insights.document_roots.contains(path: Path) -> bool` — True if `path` is a root or inside one
  - `insights.document_roots.sentence() -> str` — the one sentence naming the roots, for every error message

- [ ] **Step 1: Write the failing tests**

Create `Community Centered Humanitarian Analysis Platform/insights/tests/test_document_roots.py`:

```python
"""The folders a document may be read from are configuration, not a literal.

The whole point of this module is that no message anywhere tells a reader
about "/work" - a path that is true of exactly one deployment.
"""
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from insights import document_roots
from insights.models import InsightFolder


class DocumentRootTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "reports").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_roots_come_from_the_setting(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertEqual([path for _, path in document_roots.roots()], [self.root])

    def test_a_root_that_does_not_exist_is_not_offered(self):
        missing = self.root / "gone"
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root, missing]):
            self.assertEqual([path for _, path in document_roots.roots()], [self.root])

    def test_a_folder_inside_a_root_is_contained(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertTrue(document_roots.contains(self.root / "reports"))
            self.assertTrue(document_roots.contains(self.root))

    def test_a_traversal_out_of_a_root_is_not_contained(self):
        # Resolved before it is compared, so this is tested as its parent,
        # not as a string that merely starts with the root.
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            self.assertFalse(document_roots.contains(self.root / ".." / "elsewhere"))

    def test_the_sentence_names_the_configured_roots_and_never_work(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            sentence = document_roots.sentence()
        self.assertIn(str(self.root), sentence)
        self.assertNotIn("/work", sentence)

    def test_the_folder_form_error_names_the_configured_roots(self):
        with override_settings(INSIGHT_DOCUMENT_ROOTS=[self.root]):
            folder = InsightFolder(label="nowhere", path=str(self.root / "missing"))
            with self.assertRaises(ValidationError) as caught:
                folder.clean()
        message = str(caught.exception)
        self.assertIn(str(self.root), message)
        self.assertNotIn("/work", message)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
docker compose exec web python manage.py test insights.tests.test_document_roots -v 2
```

Expected: FAIL — `ModuleNotFoundError: No module named 'insights.document_roots'`.

- [ ] **Step 3: Add the setting**

In `config/settings.py`, immediately after the `MCP_CACHE_DIR` block:

```python
def env_paths(name: str, default: list[Path]) -> list[Path]:
    """A path-separator list from the environment, falling back when empty.

    `or default` rather than a default argument, for the same reason env_path
    uses it: an empty value in .env must fall back, not be read as "no folders
    at all", which would leave the folder browser with nothing to offer and no
    way to tell a misconfiguration from a deliberate empty list.
    """
    raw = os.environ.get(name) or ""
    chosen = [Path(part) for part in raw.split(os.pathsep) if part.strip()]
    return chosen or default


# Which folders the insights folder browser may offer, and the only folders an
# InsightFolder may point at. Configuration, not a literal: this platform is
# deployed against different folders in different places, and no message shown
# to a user may name one deployment's own paths. The wizard's native upload
# route needs none of this - it has no container path at all.
INSIGHT_DOCUMENT_ROOTS = env_paths("INSIGHT_DOCUMENT_ROOTS", [SOURCE_ROOT, MEDIA_ROOT])
```

- [ ] **Step 4: Write the module**

Create `Community Centered Humanitarian Analysis Platform/insights/document_roots.py`:

```python
"""Which folders a source document may be read from, and how to say so.

THE ONE PLACE THAT ANSWERS THIS. It used to be answered in four: a tuple in
admin_views._roots, and the same sentence about "/work" written out by hand in
InsightFolder.clean, catalogue_folder and folder_browse. A sentence written
four times is a sentence that goes stale three times, and every copy of it
named a path that only exists in one deployment.

WHY THERE IS A ROOT LIST AT ALL. folder_browse lists directories inside the
container and hands them to a form that will read every PDF in one. Without a
boundary that is a filesystem browser for anyone with a staff account. The
roots are the boundary; they are configured per deployment and nothing outside
them is listed or accepted.
"""
from pathlib import Path

from django.conf import settings


def roots():
    """[(label, resolved path)] for every configured root that exists.

    A root that has moved or is not mounted is dropped rather than offered and
    then failed on - the same behaviour the two hardcoded roots had.

    The label is the directory's own name. Deliberately not a literal written
    here: "Source documents (/work)" was true of one deployment and a lie in
    every other.
    """
    found = []
    for candidate in settings.INSIGHT_DOCUMENT_ROOTS:
        path = Path(candidate).resolve()
        if path.is_dir():
            found.append((path.name or str(path), path))
    return found


def contains(path):
    """True if `path` is a root or sits inside one.

    Resolve first, compare second. That ordering is the guard: a path holding
    `..` is collapsed before it is checked, so `<root>/../etc` is tested as
    `/etc` and refused, rather than passing a comparison that only looked at
    the start of a string.
    """
    path = Path(path).resolve()
    for _, root in roots():
        if path == root or root in path.parents:
            return True
    return False


def sentence():
    """One sentence naming the folders, for an error a person has to act on."""
    configured = [str(path) for _, path in roots()]
    if not configured:
        return (
            "No document folders are reachable on this deployment. Set "
            "INSIGHT_DOCUMENT_ROOTS and make sure the folders it names are mounted."
        )
    return "Folders must live under one of: " + ", ".join(configured) + "."
```

- [ ] **Step 5: Point the four callers at it**

In `insights/models.py`, replace the body of `InsightFolder.clean` after the `is_dir()` test:

```python
    def clean(self):
        """Reject an unreachable path at save time rather than inside a job.

        Admin calls this, so a mistyped path is a field error on the form. The
        `reachable` column in the changelist stays, for a folder that was valid
        when registered and has since moved.
        """
        from django.core.exceptions import ValidationError

        from insights import document_roots

        if self.path and not Path(self.path).is_dir():
            raise ValidationError({"path": (
                f"{self.path} is not a directory inside this container. "
                f"{document_roots.sentence()}"
            )})
```

Delete the now-duplicated `from pathlib import Path` inside the method — the module already imports it at the top.

In `insights/intake.py`, in `catalogue_folder`:

```python
    if not root.is_dir():
        from insights import document_roots
        raise FileNotFoundError(
            f"{folder.path} is not a directory inside this container. "
            f"{document_roots.sentence()}"
        )
```

In `insights/admin_views.py`, replace `_roots` and `_within_a_root` entirely with imports, and update `folder_browse`:

```python
from insights import document_roots
```

```python
def folder_browse(request):
    """One directory's subdirectories, or the list of roots when none is asked for."""
    roots = document_roots.roots()
    body = {"roots": [{"label": label, "path": str(path)} for label, path in roots]}

    raw = request.GET.get("path") or ""
    if not raw:
        return JsonResponse(body)

    try:
        path = Path(raw).resolve()
    except (OSError, ValueError):
        return JsonResponse({"error": "That path cannot be read."}, status=400)

    if not document_roots.contains(path):
        return JsonResponse({"error": document_roots.sentence()}, status=400)
```

and further down, the parent link:

```python
        "parent": (str(path.parent)
                   if document_roots.contains(path.parent) and path.parent != path
                   else None),
```

Update the module docstring's `folder-browse/` line to read "the directories under a configured document root".

- [ ] **Step 6: Run the tests**

```bash
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS, including the existing `test_admin_pickers` tests — `folder_browse`'s behaviour is unchanged, only where its roots come from.

- [ ] **Step 7: Un-peg the host side of the mount, and stop uploads landing in the repo**

In `docker-compose.yml`, line 141:

```yaml
      # 1. The folder holding the source documents, READ-ONLY. The host side is
      #    a variable because this platform is deployed against different
      #    folders in different places; the container path stays /work so
      #    nothing else has to change.
      - "${SOURCE_HOST_DIR:-..}:/work:ro"
```

In `env.example`, beside the existing path settings:

```bash
# The host folder mounted read-only at /work. Defaults to the parent of this
# repository, which is the "SUDAN Ops" folder in the original deployment.
# SOURCE_HOST_DIR=..

# Which folders the insights folder browser may offer, separated by the
# platform's path separator (";" on Windows, ":" elsewhere). Defaults to
# SOURCE_ROOT and MEDIA_ROOT. The wizard's own upload route needs none of this.
# INSIGHT_DOCUMENT_ROOTS=/work:/app/media
```

In `.gitignore`, under the `# Django` heading:

```
# Documents uploaded through Admin. /app is bind-mounted to this folder, so
# without this every uploaded PDF lands in the working tree waiting to be
# committed by accident.
Community Centered Humanitarian Analysis Platform/media/
```

- [ ] **Step 8: Prove no `/work` literal survives in the app**

```bash
docker compose exec web grep -rn "/work" insights/ || echo "clean"
```

Expected: `clean`. (`docker-compose.yml` and `env.example` still mention it — that is where a container path belongs.)

- [ ] **Step 9: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/document_roots.py" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_document_roots.py" \
        "Community Centered Humanitarian Analysis Platform/insights/models.py" \
        "Community Centered Humanitarian Analysis Platform/insights/intake.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin_views.py" \
        "Community Centered Humanitarian Analysis Platform/config/settings.py" \
        docker-compose.yml env.example .gitignore
git commit -m "insights: document roots are configuration, not a literal

Four places told the reader that /work covers the whole SUDAN Ops folder,
which is true of exactly one deployment, and the host side of the mount was
hardcoded to the parent directory. Both are now settings, and the sentence
naming the folders is written once.

Also: media/ was not ignored, so every file uploaded through Admin landed in
the working tree - /app is bind-mounted to it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 2: The model changes the wizard needs

**Files:**
- Modify: `insights/models.py`
- Create: `insights/migrations/0004_wizard_models.py` (generated)
- Test: `insights/tests/test_models.py` (append)

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `ExtractionJob.label: TextField(null=True, blank=True)`
  - `ExtractionJob.status` accepting `"collecting"`
  - `insights.models.DocumentsToInsights` — a proxy over `ExtractionJob`, `verbose_name_plural = "Part 1 — Documents → insights"`
  - `Insight.Meta.verbose_name_plural = "Part 2 — Insights"`

- [ ] **Step 1: Write the failing test**

Append to `insights/tests/test_models.py`:

```python
class WizardModelTests(TestCase):
    def test_a_batch_records_what_it_was(self):
        job = ExtractionJob.objects.create(
            status="collecting", label="folder: DTM Round 12")
        self.assertEqual(job.label, "folder: DTM Round 12")
        self.assertEqual(job.status, "collecting")

    def test_the_proxy_shares_the_jobs_table(self):
        from insights.models import DocumentsToInsights

        job = ExtractionJob.objects.create(status="collecting")
        self.assertTrue(DocumentsToInsights.objects.filter(id=job.id).exists())
        self.assertEqual(DocumentsToInsights._meta.db_table, ExtractionJob._meta.db_table)
```

Add `from insights.models import ExtractionJob` to that file's imports if it is not already there.

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec web python manage.py test insights.tests.test_models -v 2
```

Expected: FAIL — `TypeError: ExtractionJob() got unexpected keyword arguments: 'label'`.

- [ ] **Step 3: Change the models**

In `insights/models.py`, on `ExtractionJob`, add `label` directly above `producer` and extend the status help text:

```python
    label = models.TextField(
        null=True, blank=True,
        help_text="What this batch was: 'folder: DTM Round 12', '4 files'. Kept "
                  "because a folder chosen in a browser is not a path the server "
                  "can recover any other way.",
    )
    producer = models.TextField(default="external", help_text="external / anthropic / openai_compatible")
    model_used = models.TextField(null=True, blank=True)
    status = models.TextField(
        default="queued",
        help_text=(
            "collecting / queued / running / loaded / failed. 'collecting' is a "
            "wizard batch whose files are still arriving. A job stuck at 'running' "
            "because its process was killed rather than raising (e.g. docker "
            "compose restart web) can be recovered with the 'Reset stuck job to "
            "queued' action below."
        ),
    )
```

On `Insight.Meta`, add the index-label line beside the existing options:

```python
    class Meta:
        db_table = "insights"
        ordering = ["-stated_on", "id"]
        # How this table is named on the admin index. "Part 2" because the
        # wizard is Part 1 and the two are read in that order; the admin sorts
        # the index by name, so the numbers do the ordering.
        verbose_name_plural = "Part 2 — Insights"
```

At the end of the file, add the proxy:

```python
class DocumentsToInsights(ExtractionJob):
    """The wizard's front door on the admin index.

    A proxy, because Django's admin index lists registered MODELS and the
    wizard is a sequence of pages. Proxying ExtractionJob rather than inventing
    a model is honest about what the wizard drives: a batch IS a job, and the
    steps are that job's states. No table is created.
    """

    class Meta:
        proxy = True
        verbose_name = "Documents → insights"
        verbose_name_plural = "Part 1 — Documents → insights"
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
docker compose exec web python manage.py makemigrations insights --name wizard_models
docker compose exec web cat insights/migrations/0004_wizard_models.py
```

Expected: `AddField` for `label`, `AlterField` for `status`, `AlterModelOptions` for `insight`, and `CreateModel` for `DocumentsToInsights` with `'proxy': True` and `bases=('insights.extractionjob',)`. **No `CreateModel` with fields** — a proxy creates no table. If one appears, `proxy = True` is missing.

- [ ] **Step 5: Apply it and run the tests**

```bash
docker compose exec web python manage.py migrate insights
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/models.py" \
        "Community Centered Humanitarian Analysis Platform/insights/migrations/0004_wizard_models.py" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_models.py"
git commit -m "insights: a job can be a collecting batch, and can say what it was

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 3: Publishing, written once

Extracted before the wizard needs it, so there is never a second implementation to drift.

**Files:**
- Create: `insights/review.py`
- Modify: `insights/admin.py` (`publish_selected`, `reject_selected`)
- Test: `insights/tests/test_review.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `insights.review.publish(queryset, user) -> int`
  - `insights.review.reject(queryset, user) -> int`

  Both stamp `reviewed_by` and `reviewed_at` and return the number of rows changed.

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_review.py`:

```python
"""Publishing is a decision, and it is recorded as one."""
from django.contrib.auth.models import User
from django.test import TestCase

from insights import review
from insights.models import Insight
from insights.verify import quote_sha1

QUOTE = "The borehole has been dry since the rains failed."


class ReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="manual", stated_on="2026-05-01", iso3="TCD", status="pending",
        )

    def test_publishing_records_who_and_when(self):
        changed = review.publish(Insight.objects.filter(id=self.insight.id), self.user)
        self.insight.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertIsNotNone(self.insight.reviewed_at)

    def test_rejecting_records_who_and_when(self):
        changed = review.reject(Insight.objects.filter(id=self.insight.id), self.user)
        self.insight.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(self.insight.status, "rejected")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)

    def test_only_the_selected_rows_move(self):
        other = Insight.objects.create(
            quote="A second statement.", quote_sha1=quote_sha1("A second statement."),
            voice_type="community", channel="manual", stated_on="2026-05-02",
            iso3="TCD", status="pending",
        )
        review.publish(Insight.objects.filter(id=self.insight.id), self.user)
        other.refresh_from_db()
        self.assertEqual(other.status, "pending")
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec web python manage.py test insights.tests.test_review -v 2
```

Expected: FAIL — `ImportError: cannot import name 'review'`.

- [ ] **Step 3: Write the module**

Create `insights/review.py`:

```python
"""Moving an insight from pending to published, or to rejected.

Written here rather than inside the changelist actions because there are now
two callers - the actions and the wizard's review step - and a review decision
recorded two slightly different ways is a review decision nobody can audit.

A rejected extraction is evidence about the model, not rubbish: `status` is set
but `rejection_reason` is deliberately left alone for a person to fill in.
"""
from django.utils import timezone


def publish(queryset, user):
    """Publish every insight in `queryset`. Returns how many moved."""
    return queryset.update(
        status="published", reviewed_by=user, reviewed_at=timezone.now())


def reject(queryset, user):
    """Reject every insight in `queryset`. Returns how many moved."""
    return queryset.update(
        status="rejected", reviewed_by=user, reviewed_at=timezone.now())
```

- [ ] **Step 4: Point the changelist actions at it**

In `insights/admin.py`, add `from insights import review` to the imports, drop the now-unused `from django.utils import timezone` **only if nothing else in the file uses it** (check with `grep -n timezone insights/admin.py`), and replace the two action bodies:

```python
    @admin.action(description="Publish selected insights")
    def publish_selected(self, request, queryset):
        updated = review.publish(queryset, request.user)
        self.message_user(request, f"{updated} published.", messages.SUCCESS)

    @admin.action(description="Reject selected insights")
    def reject_selected(self, request, queryset):
        updated = review.reject(queryset, request.user)
        self.message_user(
            request,
            f"{updated} rejected. Add a reason on each one - a rejected extraction is "
            f"evidence about the model, not rubbish.",
            messages.WARNING,
        )
```

- [ ] **Step 5: Run the tests**

```bash
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS, including `test_admin.AdminReviewTests.test_publishing_records_who_and_when`, which exercises the action through the changelist and so proves the extraction changed nothing.

- [ ] **Step 6: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/review.py" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_review.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin.py"
git commit -m "insights: publish and reject are written once

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 4: Two front doors on the index

**Files:**
- Create: `insights/wizard.py` (job list only; the steps arrive in Tasks 5–9)
- Create: `insights/templates/insights/wizard_base.html`
- Create: `insights/templates/insights/wizard_jobs.html`
- Modify: `insights/admin.py`
- Test: `insights/tests/test_wizard_index.py`

**Interfaces:**
- Consumes: Task 2's `DocumentsToInsights`.
- Produces:
  - `insights.wizard.job_list(request) -> HttpResponse` — recent batches
  - admin URL name `admin:insights_documentstoinsights_changelist` → the wizard's job list
  - `wizard_base.html` block names: `{% block wizard_step %}` (the step number, 1–4) and `{% block wizard_body %}`

- [ ] **Step 1: Write the failing test**

Create `insights/tests/test_wizard_index.py`:

```python
"""The section shows two front doors, and the machinery stays reachable."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from insights.models import ExtractionJob


class WizardIndexTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)

    def test_the_index_offers_part_1_and_part_2(self):
        response = self.client.get(reverse("admin:app_list", args=["insights"]))
        body = response.content.decode()
        self.assertIn("Part 1 — Documents → insights", body)
        self.assertIn("Part 2 — Insights", body)

    def test_the_machinery_is_off_the_index(self):
        body = self.client.get(reverse("admin:app_list", args=["insights"])).content.decode()
        self.assertNotIn("Extraction jobs", body)
        self.assertNotIn("Insight folders", body)
        self.assertNotIn("Insight uploads", body)

    def test_the_machinery_is_still_reachable_by_url(self):
        # Hidden from the index is not the same as gone: "Reset stuck job to
        # queued" is the only way out of a job whose process was killed.
        for url_name in ("admin:insights_extractionjob_changelist",
                         "admin:insights_insightfolder_changelist",
                         "admin:insights_insightupload_changelist"):
            self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_the_wizard_lists_recent_batches(self):
        ExtractionJob.objects.create(status="loaded", label="4 files")
        response = self.client.get(
            reverse("admin:insights_documentstoinsights_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("4 files", response.content.decode())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_index -v 2
```

Expected: FAIL — `NoReverseMatch: 'insights_documentstoinsights_changelist' is not a registered namespace`.

- [ ] **Step 3: Write the shared template**

Create `insights/templates/insights/wizard_base.html`:

```html
{% extends "admin/base_site.html" %}
{% comment %}
The wizard's chrome: the four steps, with the current one marked. Extending
admin/base_site.html is what gives these pages the admin's own header, login
redirect and stylesheet, so they do not read as a bolted-on second site.
{% endcomment %}
{% block extrastyle %}{{ block.super }}
<style>
  .wiz-steps { display: flex; gap: .5rem; list-style: none; padding: 0; margin: 0 0 1.5rem; }
  .wiz-steps li { padding: .4rem .9rem; border-radius: 999px; background: #f0f0f0; color: #555; font-size: .85rem; }
  .wiz-steps li.is-current { background: #417690; color: #fff; font-weight: 600; }
  .wiz-steps li.is-done { background: #dfeeda; color: #2b5c1e; }
  .wiz-files { width: 100%; border-collapse: collapse; }
  .wiz-files td, .wiz-files th { padding: .4rem .6rem; border-bottom: 1px solid #eee; text-align: left; }
  .wiz-files tr.is-skipped { color: #999; }
  .wiz-files tr.is-failed td { color: #a41515; }
  .wiz-bar { height: 1.25rem; background: #f0f0f0; border-radius: 999px; overflow: hidden; }
  .wiz-bar span { display: block; height: 100%; background: #417690; width: 0; transition: width .3s; }
  .wiz-log { background: #1f1f1f; color: #ddd; padding: .75rem; height: 16rem; overflow-y: auto;
             white-space: pre-wrap; font-family: monospace; font-size: .8rem; }
  .wiz-note { padding: .75rem 1rem; border-left: 4px solid #999; background: #fafafa; margin: 1rem 0; }
  .wiz-note.is-bad { border-color: #a41515; background: #fdf0f0; }
  .wiz-note.is-warn { border-color: #c79100; background: #fdf8e8; }
</style>
{% endblock %}
{% block content %}
<ol class="wiz-steps">
  <li class="{% if wizard_step == 1 %}is-current{% elif wizard_step > 1 %}is-done{% endif %}">1. Bring documents in</li>
  <li class="{% if wizard_step == 2 %}is-current{% elif wizard_step > 2 %}is-done{% endif %}">2. Check what will be read</li>
  <li class="{% if wizard_step == 3 %}is-current{% elif wizard_step > 3 %}is-done{% endif %}">3. Extract</li>
  <li class="{% if wizard_step == 4 %}is-current{% endif %}">4. Review and publish</li>
</ol>
{% block wizard_body %}{% endblock %}
{% endblock %}
```

- [ ] **Step 4: Write the job list template**

Create `insights/templates/insights/wizard_jobs.html`:

```html
{% extends "insights/wizard_base.html" %}
{% block wizard_body %}
<p><a class="button" href="{% url 'admin:insights_wizard_start' %}">Start a new batch</a></p>

<h2>Recent batches</h2>
{% if jobs %}
<table class="wiz-files">
  <tr><th>Batch</th><th>State</th><th>Documents</th><th>Statements</th><th></th></tr>
  {% for job in jobs %}
  <tr>
    <td>{{ job.label|default:job }}</td>
    <td>{{ job.status }}</td>
    <td>{{ job.documents_done }} of {{ job.documents_total }}</td>
    <td>{{ job.insights_proposed }}</td>
    <td><a href="{% url 'admin:insights_wizard_job' job.id %}">Open</a></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No batches yet. "Start a new batch" opens a window on your own computer to pick
   the PDFs or Word documents to read.</p>
{% endif %}

<p class="wiz-note">
  Working from an archive already on this server rather than your own machine?
  Register it as a folder under
  <a href="{% url 'admin:insights_insightfolder_changelist' %}">source folders</a>
  — nothing is copied that way.
</p>
{% endblock %}
```

- [ ] **Step 5: Write the view**

Create `insights/wizard.py`:

```python
"""The guided route from documents to published insights.

FOUR STEPS, ONE JOB. Every step reads its state off one ExtractionJob row:
"collecting" is a batch whose files are still arriving, "queued" is ready to
extract, "running" is extracting, "loaded" is ready to review. Nothing is kept
in the session, so closing the tab loses nothing and reopening the wizard
rejoins the batch wherever it got to.

WHY THESE ARE NOT IN insights/urls.py. That file is the public read API. These
are mounted inside the admin site (DocumentsToInsightsAdmin.get_urls) and
wrapped in admin_view(), so they carry the same staff-only check and login
redirect as every other admin page - exactly as place_options and
folder_browse already are.
"""
from django.contrib import admin as django_admin
from django.shortcuts import render

from insights.models import ExtractionJob

RECENT_JOBS = 20


def page(request, **extra):
    """The context every wizard page needs.

    each_context() is what supplies the admin's header, breadcrumbs, site title
    and the user menu. admin_view() does NOT add it - it wraps a view in the
    permission check and the login redirect and nothing else - so a page that
    forgets this renders as an unstyled orphan with no way back to the admin.
    """
    return {**django_admin.site.each_context(request), **extra}


def job_list(request):
    """Recent batches and how far each one got."""
    return render(request, "insights/wizard_jobs.html", page(
        request,
        wizard_step=0,
        jobs=ExtractionJob.objects.order_by("-id")[:RECENT_JOBS],
    ))
```

- [ ] **Step 6: Register the proxy admin and hide the three machinery models**

In `insights/admin.py`, add to the imports:

```python
from insights import admin_views, review, wizard
from insights.models import (
    DocumentsToInsights, ExtractionJob, Insight, InsightCoding, InsightFolder,
    InsightUpload,
)
```

Add this identical method to `InsightFolderAdmin`, `InsightUploadAdmin` and `ExtractionJobAdmin` (repeat it — it is three lines, and a shared mixin for three lines would hide it):

```python
    def get_model_perms(self, request):
        """Off the index, but every URL still works.

        Returning no perms is the documented way to drop a model from the app
        list without touching access: the wizard is the front door now, and
        these three are its machinery. Deliberately NOT has_module_permission,
        which also blocks the app index page.

        They must stay reachable: "Reset stuck job to queued" is the only way
        out of a job whose process was killed rather than raised.
        """
        return {}
```

At the end of the file, register the wizard:

```python
@admin.register(DocumentsToInsights)
class DocumentsToInsightsAdmin(admin.ModelAdmin):
    """Part 1 on the index. Every page it serves lives in insights/wizard.py.

    The changelist is replaced outright rather than configured: what a person
    needs here is "start a batch" and "open the one I was in the middle of",
    not a filterable table of a database row's columns.
    """

    def get_urls(self):
        # Before super(), so these are matched ahead of the admin's own
        # <path:object_id> catch-all - which would otherwise swallow every one
        # of them as an attempt to open a job with that id.
        return [
            path("start/", self.admin_site.admin_view(wizard.start),
                 name="insights_wizard_start"),
            path("job/<int:job_id>/", self.admin_site.admin_view(wizard.job_step),
                 name="insights_wizard_job"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        return wizard.job_list(request)

    def has_add_permission(self, request):
        # "Add extraction job" would create an empty batch with no documents
        # and no way to add any. Batches are started by the wizard.
        return False
```

Task 5 adds `wizard.start` and `wizard.job_step`; until then, add these two stubs to `insights/wizard.py` so the URLs resolve:

```python
def start(request):
    """Step 1. Filled in by Task 5."""
    raise NotImplementedError


def job_step(request, job_id):
    """Steps 2-4, chosen by the job's status. Filled in by Task 5."""
    raise NotImplementedError
```

- [ ] **Step 7: Run the tests**

```bash
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS. If `test_the_index_offers_part_1_and_part_2` fails on the em dash, check the file was written as UTF-8 — the labels contain `—` and `→`.

- [ ] **Step 8: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/wizard.py" \
        "Community Centered Humanitarian Analysis Platform/insights/templates/" \
        "Community Centered Humanitarian Analysis Platform/insights/admin.py" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_wizard_index.py"
git commit -m "insights: two front doors instead of five screens

Part 1 is the wizard, Part 2 is the statement table. Jobs, folders and uploads
come off the index but keep every URL - reset-stuck-job is the only way out of
a killed extraction.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 5: The batch endpoints

The server half of steps 1 and 2: open a batch, take one file, close it.

**Files:**
- Modify: `insights/wizard.py`
- Modify: `insights/admin.py` (three more URLs)
- Test: `insights/tests/test_wizard_batch.py`

**Interfaces:**
- Consumes: Task 4's `job_list`, `start`, `job_step`.
- Produces:
  - `POST admin:insights_wizard_batch` → `{"job_id": int}`
  - `POST admin:insights_wizard_batch_file` `(job_id)` with `file` and `relative_path` → `{"name", "outcome", "message", "pages", "document_id"}` where `outcome` is `catalogued` | `duplicate` | `skipped` | `failed`
  - `POST admin:insights_wizard_batch_ready` `(job_id)` → `{"documents_total": int}`

- [ ] **Step 1: Write the failing tests**

Create `insights/tests/test_wizard_batch.py`:

```python
"""Files arrive one request at a time, and one bad file does not stop a batch."""
import tempfile
from pathlib import Path

import fitz
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob


def a_pdf(text="The market has been closed for three weeks."):
    """A real one-page PDF, because catalogue_file actually opens it."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


class BatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def open_batch(self, label="3 files"):
        response = self.client.post(
            reverse("admin:insights_wizard_batch"), {"label": label})
        return response.json()["job_id"]

    def send(self, job_id, name, payload, relative_path=""):
        return self.client.post(
            reverse("admin:insights_wizard_batch_file", args=[job_id]),
            {"file": SimpleUploadedFile(name, payload, content_type="application/pdf"),
             "relative_path": relative_path},
        )

    def test_opening_a_batch_creates_a_collecting_job(self):
        job = ExtractionJob.objects.get(id=self.open_batch("folder: DTM Round 12"))
        self.assertEqual(job.status, "collecting")
        self.assertEqual(job.label, "folder: DTM Round 12")

    def test_a_pdf_is_catalogued_and_attached(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            body = self.send(job_id, "report.pdf", a_pdf()).json()
        self.assertEqual(body["outcome"], "catalogued")
        self.assertEqual(body["pages"], 1)
        job = ExtractionJob.objects.get(id=job_id)
        self.assertEqual(job.documents.count(), 1)

    def test_the_same_content_under_another_name_is_a_duplicate(self):
        # catalogue_file de-duplicates on the content's sha1, so this must
        # attach the existing Document rather than make a second one.
        payload = a_pdf()
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", payload)
            body = self.send(job_id, "report-copy.pdf", payload).json()
        self.assertEqual(body["outcome"], "duplicate")
        self.assertEqual(Document.objects.filter(source_collection="insights").count(), 1)

    def test_a_file_that_is_not_a_document_is_skipped(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            body = self.send(job_id, "notes.txt", b"hello").json()
        self.assertEqual(body["outcome"], "skipped")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 0)

    def test_a_corrupt_pdf_fails_its_own_row_and_the_batch_continues(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            bad = self.send(job_id, "broken.pdf", b"%PDF-1.4 not really")
            good = self.send(job_id, "fine.pdf", a_pdf())
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(bad.json()["outcome"], "failed")
        self.assertEqual(good.json()["outcome"], "catalogued")
        self.assertEqual(ExtractionJob.objects.get(id=job_id).documents.count(), 1)

    def test_the_relative_path_is_kept_as_a_label_only(self):
        # It is client-controlled. It must never reach a filesystem path.
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", a_pdf(),
                      relative_path="../../etc/DTM Round 12/report.pdf")
        from insights.models import InsightUpload
        upload = InsightUpload.objects.get()
        self.assertIn("DTM Round 12", upload.label)
        self.assertTrue(Path(upload.file.path).resolve().is_relative_to(
            Path(self.media.name).resolve()))

    def test_ready_queues_the_batch(self):
        with override_settings(MEDIA_ROOT=self.media.name):
            job_id = self.open_batch()
            self.send(job_id, "report.pdf", a_pdf())
            body = self.client.post(
                reverse("admin:insights_wizard_batch_ready", args=[job_id])).json()
        job = ExtractionJob.objects.get(id=job_id)
        self.assertEqual(body["documents_total"], 1)
        self.assertEqual(job.documents_total, 1)
        self.assertEqual(job.status, "queued")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_batch -v 2
```

Expected: FAIL — `NoReverseMatch: Reverse for 'insights_wizard_batch' not found`.

- [ ] **Step 3: Write the endpoints**

Add to `insights/wizard.py` — imports first:

```python
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from data_track.models import Document
from insights.intake import SUFFIXES, catalogue_file, relative_path, sha1_of
from insights.models import ExtractionJob, InsightUpload
```

then:

```python
@require_POST
def batch_open(request):
    """Start a batch. One job for the whole drop, not one per file."""
    job = ExtractionJob.objects.create(
        status="collecting", producer="external",
        label=(request.POST.get("label") or "").strip() or None,
    )
    return JsonResponse({"job_id": job.id})


@require_POST
def batch_file(request, job_id):
    """Take exactly one file, catalogue it, attach it, and say what happened.

    ONE FILE PER REQUEST, deliberately. Django 5.0's
    DATA_UPLOAD_MAX_NUMBER_FILES defaults to 100, so a folder of 300 reports
    posted in one go is rejected outright - and a single failure inside a
    300-file request loses the other 299 results. This way a corrupt PDF is one
    row with a reason on it.
    """
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"error": "No file was sent."}, status=400)

    # Client-controlled, and it stays a label: joined onto a directory, a value
    # of "../../etc/passwd" is a traversal. Nothing needs it on disk, because
    # catalogue_file de-duplicates on the content's sha1.
    label = (request.POST.get("relative_path") or "").strip() or upload.name

    suffix = Path(upload.name).suffix.lower()
    if suffix not in SUFFIXES:
        return JsonResponse({
            "name": label, "outcome": "skipped",
            "message": f"{suffix or 'no extension'} is not a PDF or Word document.",
        })

    row = InsightUpload.objects.create(file=upload, label=label)
    stored = Path(row.file.path)

    # Asked before cataloguing, because catalogue_file returns the existing
    # Document either way and there is no other way to tell the two apart.
    rel = relative_path(stored, sha1_of(stored))
    already = Document.objects.filter(rel_path=rel).exists()

    try:
        document = catalogue_file(stored)
    except Exception as exc:                      # noqa: BLE001 - reported per file
        # An unreadable file is an expected input here, not an exceptional one:
        # a password-protected or truncated PDF in a folder of 200 must not take
        # the other 199 down. Type and message only, never the repr.
        row.delete()
        stored.unlink(missing_ok=True)
        return JsonResponse({
            "name": label, "outcome": "failed",
            "message": f"{type(exc).__name__}: {exc}",
        })

    row.document = document
    row.save(update_fields=["document"])
    job.documents.add(document)

    return JsonResponse({
        "name": label,
        "outcome": "duplicate" if already else "catalogued",
        "pages": document.pages,
        "document_id": document.id,
        "message": ("Already catalogued - the same file is in the database."
                    if already else ""),
    })


@require_POST
def batch_ready(request, job_id):
    """Close the batch and queue it for extraction."""
    job = get_object_or_404(ExtractionJob, id=job_id, status="collecting")
    job.documents_total = job.documents.count()
    job.status = "queued"
    job.save(update_fields=["documents_total", "status"])
    return JsonResponse({"documents_total": job.documents_total})
```

Replace the `start` and `job_step` stubs:

```python
def start(request):
    """Step 1: the two pickers. No job exists until a file is actually sent."""
    return render(request, "insights/wizard_intake.html", page(request, wizard_step=1))


def job_step(request, job_id):
    """Whichever step this job's status puts it at.

    Read off the job rather than kept in the session, so closing the tab loses
    nothing: the same URL reopens the batch where it actually is.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    if job.status == "collecting":
        return render(request, "insights/wizard_intake.html",
                      page(request, job=job, wizard_step=1))
    if job.status in ("queued", "running", "failed"):
        return render(request, "insights/wizard_extract.html",
                      page(request, job=job, wizard_step=3))
    return render(request, "insights/wizard_review.html",
                  page(request, job=job, wizard_step=4))
```

- [ ] **Step 4: Mount the three URLs**

In `DocumentsToInsightsAdmin.get_urls`, before `super()`:

```python
            path("batch/", self.admin_site.admin_view(wizard.batch_open),
                 name="insights_wizard_batch"),
            path("batch/<int:job_id>/file/",
                 self.admin_site.admin_view(wizard.batch_file),
                 name="insights_wizard_batch_file"),
            path("batch/<int:job_id>/ready/",
                 self.admin_site.admin_view(wizard.batch_ready),
                 name="insights_wizard_batch_ready"),
```

`start` and `job_step` render templates that Task 6 creates. Until then these three tests are what runs; `test_wizard_batch` does not open those pages.

- [ ] **Step 5: Run the tests**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_batch -v 2
```

Expected: PASS, all seven.

- [ ] **Step 6: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/wizard.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin.py" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_wizard_batch.py"
git commit -m "insights: a batch takes one file per request

One request per file because DATA_UPLOAD_MAX_NUMBER_FILES is 100 and a folder
of reports is bigger than that - and because a corrupt PDF should cost one row,
not the other 199. The browser's relative path is kept as a label and never
reaches a filesystem path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 6: The native pickers and the preview

**Files:**
- Create: `insights/templates/insights/wizard_intake.html`
- Create: `insights/static/insights/wizard_intake.js`
- Test: manual browser walkthrough (Step 4) — the pickers are browser behaviour; their server side is already covered by Task 5

**Interfaces:**
- Consumes: Task 5's three endpoints.
- Produces: a page that ends by navigating to `admin:insights_wizard_job` for the batch it created.

- [ ] **Step 1: Write the template**

Create `insights/templates/insights/wizard_intake.html`:

```html
{% extends "insights/wizard_base.html" %}
{% load static %}
{% block wizard_body %}
<div id="wiz-intake"
     data-batch-url="{% url 'admin:insights_wizard_batch' %}"
     data-batch-file-url="{% url 'admin:insights_wizard_batch_file' 0 %}"
     data-batch-ready-url="{% url 'admin:insights_wizard_batch_ready' 0 %}"
     data-job-url="{% url 'admin:insights_wizard_job' 0 %}">
  {% csrf_token %}

  <p>Pick the reports to read. Both buttons open a window on your own computer.
     Only PDF and Word (.docx) files are sent; anything else in a folder is left
     where it is.</p>

  <p>
    <label class="button" for="wiz-files">Choose files</label>
    <input id="wiz-files" type="file" multiple accept=".pdf,.docx" hidden>

    <label class="button" for="wiz-folder">Choose a folder</label>
    <input id="wiz-folder" type="file" webkitdirectory hidden>
  </p>

  <div id="wiz-preview" hidden>
    <h2>What will be read <small id="wiz-count"></small></h2>
    <table class="wiz-files"><tbody id="wiz-rows"></tbody></table>
    <p>
      <button type="button" id="wiz-send" class="default">Read these documents</button>
      <button type="button" id="wiz-clear">Start again</button>
    </p>
  </div>

  <div id="wiz-progress" hidden>
    <div class="wiz-bar"><span id="wiz-bar-fill"></span></div>
    <p id="wiz-progress-text"></p>
  </div>
</div>
<script src="{% static 'insights/wizard_intake.js' %}" defer></script>
{% endblock %}
```

- [ ] **Step 2: Write the JavaScript**

Create `insights/static/insights/wizard_intake.js`:

```js
/* Step 1 and 2: pick documents on your own machine, see what will be read,
 * then send them one at a time.
 *
 * WHY THE FILTER RUNS BEFORE ANYTHING IS SENT. `webkitdirectory` hands over
 * EVERY file in the chosen folder, recursively - .DS_Store, photographs,
 * spreadsheets, all of it. Sending those to be rejected server-side would
 * upload gigabytes to throw away. They are listed as skipped instead, so the
 * filter is visible rather than silent.
 *
 * WHY ONE REQUEST PER FILE. Django's DATA_UPLOAD_MAX_NUMBER_FILES is 100, so a
 * folder of reports cannot go in one POST at all - and sequential requests give
 * an honest progress bar and a per-file error instead of one opaque failure.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-intake");
  if (!root) { return; }

  var KEEP = /\.(pdf|docx)$/i;
  var chosen = [];

  var preview = document.getElementById("wiz-preview");
  var rows = document.getElementById("wiz-rows");
  var count = document.getElementById("wiz-count");
  var progress = document.getElementById("wiz-progress");
  var fill = document.getElementById("wiz-bar-fill");
  var progressText = document.getElementById("wiz-progress-text");
  var sendButton = document.getElementById("wiz-send");

  function csrf() {
    var field = root.querySelector("[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  /* Every URL is reversed by Django with a placeholder id of 0 and the real id
   * put in here. Deliberately not assembled from path fragments: the admin owns
   * these URLs, and a path written twice is a path that goes stale once. */
  function withId(template, id) {
    return template.replace("/0/", "/" + id + "/");
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() },
      body: body
    }).then(function (response) {
      if (!response.ok) { throw new Error(response.status); }
      return response.json();
    });
  }

  function human(bytes) {
    if (bytes < 1024) { return bytes + " B"; }
    if (bytes < 1048576) { return Math.round(bytes / 1024) + " KB"; }
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  /* Stage 1 of the preview: what the browser handed over, before a byte is
   * sent. The operator can still walk away at no cost. */
  function show(fileList, label) {
    chosen = [];
    rows.replaceChildren();
    var skipped = 0;

    Array.prototype.forEach.call(fileList, function (file) {
      var relative = file.webkitRelativePath || file.name;
      var row = document.createElement("tr");
      var keep = KEEP.test(file.name);

      if (keep) {
        chosen.push({ file: file, relative: relative, row: row });
      } else {
        skipped += 1;
        row.className = "is-skipped";
      }

      row.innerHTML =
        "<td>" + relative.replace(/</g, "&lt;") + "</td>" +
        "<td>" + human(file.size) + "</td>" +
        "<td class='wiz-outcome'>" + (keep ? "will be read" : "not a PDF or Word file") + "</td>";
      rows.appendChild(row);
    });

    count.textContent = chosen.length + " document(s)" +
      (skipped ? ", " + skipped + " other file(s) skipped" : "");
    sendButton.disabled = chosen.length === 0;
    root.dataset.batchLabel = label;
    preview.hidden = false;
    progress.hidden = true;
  }

  /* Stage 2: send them one at a time, filling each row in as it lands. */
  function send() {
    sendButton.disabled = true;
    progress.hidden = false;

    post(root.dataset.batchUrl, new URLSearchParams({
      label: root.dataset.batchLabel
    })).then(function (opened) {
      var jobId = opened.job_id;
      var done = 0;

      function next(index) {
        if (index >= chosen.length) {
          return post(withId(root.dataset.batchReadyUrl, jobId),
                      new URLSearchParams());
        }
        var item = chosen[index];
        var body = new FormData();
        body.append("file", item.file);
        body.append("relative_path", item.relative);

        return post(withId(root.dataset.batchFileUrl, jobId), body)
          .then(function (result) {
          var cell = item.row.querySelector(".wiz-outcome");
          if (result.outcome === "catalogued") {
            cell.textContent = result.pages + " page(s)";
          } else if (result.outcome === "duplicate") {
            cell.textContent = "already catalogued (identical file)";
          } else {
            item.row.className = "is-failed";
            cell.textContent = result.message;
          }
          done += 1;
          fill.style.width = Math.round(done * 100 / chosen.length) + "%";
          progressText.textContent = "Read " + done + " of " + chosen.length;
          return next(index + 1);
        });
      }

      return next(0).then(function () {
        window.location = withId(root.dataset.jobUrl, jobId);
      });
    }).catch(function (error) {
      progressText.textContent = "Could not finish: " + error.message;
      sendButton.disabled = false;
    });
  }

  document.getElementById("wiz-files").addEventListener("change", function (event) {
    show(event.target.files, event.target.files.length + " files");
  });

  document.getElementById("wiz-folder").addEventListener("change", function (event) {
    var first = event.target.files[0];
    var folder = first && first.webkitRelativePath
      ? first.webkitRelativePath.split("/")[0] : "a folder";
    show(event.target.files, "folder: " + folder);
  });

  document.getElementById("wiz-clear").addEventListener("click", function () {
    chosen = [];
    rows.replaceChildren();
    preview.hidden = true;
    progress.hidden = true;
  });

  sendButton.addEventListener("click", send);
}());
```

- [ ] **Step 3: Check the page renders**

```bash
docker compose exec web python manage.py test insights -v 2
docker compose restart web
```

Then open `http://localhost:2026/admin/insights/documentstoinsights/start/` and confirm the two buttons appear. Restarting `web` is required for template changes to be picked up.

- [ ] **Step 4: Walk it in a real browser**

Pick two PDFs with "Choose files": the preview lists both, "Read these documents" fills in page counts, and the page lands on the extract step. Then pick a folder containing PDFs *and* a few non-documents: the non-documents appear greyed out as "not a PDF or Word file" and are never uploaded (confirm in the network tab — one request per PDF, none for the others).

- [ ] **Step 5: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/templates/insights/wizard_intake.html" \
        "Community Centered Humanitarian Analysis Platform/insights/static/insights/wizard_intake.js"
git commit -m "insights: pick documents from a native window on your own machine

A web page cannot read a folder by path, but webkitdirectory opens a real OS
folder window and hands over what is inside. Filtered to PDF and DOCX before
anything is sent, so a folder of photographs beside the reports costs nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 7: Watching the extraction

**Files:**
- Modify: `insights/wizard.py`
- Modify: `insights/admin.py` (two more URLs)
- Create: `insights/templates/insights/wizard_extract.html`
- Create: `insights/static/insights/wizard_extract.js`
- Test: `insights/tests/test_wizard_extract.py`

**Interfaces:**
- Consumes: Task 5's `job_step`.
- Produces:
  - `POST admin:insights_wizard_extract` `(job_id)` → `{"started": bool, "message": str}`
  - `GET admin:insights_wizard_progress` `(job_id)` → `{"status", "done", "total", "proposed", "unverifiable", "skipped_reviewed", "log_tail", "last_change"}`
  - `insights.wizard.log_path(job) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `insights/tests/test_wizard_extract.py`:

```python
"""Progress is read off the job and its log file, and a failure says so."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from insights.models import ExtractionJob


class ExtractProgressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        self.job = ExtractionJob.objects.create(
            status="running", documents_total=4, documents_done=1,
            insights_proposed=7, insights_rejected_unverifiable=2)

    def progress(self):
        with override_settings(MCP_CACHE_DIR=self.cache.name):
            return self.client.get(
                reverse("admin:insights_wizard_progress", args=[self.job.id])).json()

    def test_the_counters_come_from_the_job(self):
        body = self.progress()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["done"], 1)
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["proposed"], 7)
        self.assertEqual(body["unverifiable"], 2)

    def test_a_missing_log_is_not_an_error(self):
        body = self.progress()
        self.assertEqual(body["log_tail"], "")
        self.assertIsNone(body["last_change"])

    def test_the_log_is_tailed_from_the_end(self):
        folder = Path(self.cache.name) / "insights"
        folder.mkdir(parents=True)
        (folder / f"job-{self.job.id}.log").write_text(
            "x" * 9000 + "\nthe last line\n", encoding="utf-8")
        body = self.progress()
        self.assertIn("the last line", body["log_tail"])
        self.assertLess(len(body["log_tail"]), 9000)
        self.assertIsNotNone(body["last_change"])

    def test_launching_refuses_a_job_that_is_already_running(self):
        # A double click must not run two extractions of one job: the second
        # pass would double every insight the first one wrote.
        with patch("insights.wizard.subprocess.Popen") as popen:
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.assertFalse(body["started"])
        popen.assert_not_called()

    def test_launching_says_so_when_no_extractor_is_configured(self):
        # The normal state for the route CLAUDE.md documents first: extraction
        # run by an agent on the host, loaded from mcp_cache/insights/.
        self.job.status = "queued"
        self.job.save(update_fields=["status"])
        with patch("insights.wizard.get_extractor",
                   side_effect=ValueError("LLM_PROVIDER is not set")):
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.assertFalse(body["started"])
        self.assertIn("LLM_PROVIDER is not set", body["message"])

    def test_launching_marks_the_job_running_before_it_returns(self):
        self.job.status = "queued"
        self.job.save(update_fields=["status"])
        with override_settings(MCP_CACHE_DIR=self.cache.name), \
             patch("insights.wizard.get_extractor"), \
             patch("insights.wizard.subprocess.Popen") as popen:
            body = self.client.post(
                reverse("admin:insights_wizard_extract", args=[self.job.id])).json()
        self.job.refresh_from_db()
        self.assertTrue(body["started"])
        self.assertEqual(self.job.status, "running")
        # Detached, so a gunicorn worker recycling does not kill it.
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
```

- [ ] **Step 2: Run them to verify they fail**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_extract -v 2
```

Expected: FAIL — `NoReverseMatch: Reverse for 'insights_wizard_progress' not found`.

- [ ] **Step 3: Write the views**

Add to `insights/wizard.py` — imports:

```python
import subprocess
import sys
from datetime import datetime, timezone as dt_timezone

from django.conf import settings

from insights.extractors import get_extractor
```

then:

```python
LOG_TAIL_BYTES = 4096


def log_path(job):
    """Where the detached extraction writes its output."""
    return Path(settings.MCP_CACHE_DIR) / "insights" / f"job-{job.id}.log"


def _tail(path):
    """The last few KB of a file, or "" if there is no file yet.

    Seeked, not read: a long run's log grows without bound and this endpoint is
    polled every two seconds. The first line of the block is dropped when the
    file is longer than the window, because it is half a line.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            block = handle.read()
    except OSError:
        return ""
    text = block.decode("utf-8", errors="replace")
    return text if size <= LOG_TAIL_BYTES else text.split("\n", 1)[-1]


def _last_change(path):
    """When the extraction last wrote anything, as an ISO timestamp.

    THE LOG FILE'S MTIME, not a column on the job. ExtractionJob has no
    updated_at, and adding one with auto_now=True would not work: the command
    saves with update_fields=["documents_done"] and update_fields=["log"], and
    an auto_now field is only touched when it is among the fields listed. The
    child writes to this file as each document finishes, which is exactly the
    signal the stall warning needs, and it costs no model change.
    """
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=dt_timezone.utc).isoformat()


def progress(request, job_id):
    """Everything the extract step redraws itself from."""
    job = get_object_or_404(ExtractionJob, id=job_id)
    path = log_path(job)
    return JsonResponse({
        "status": job.status,
        "done": job.documents_done,
        "total": job.documents_total,
        "proposed": job.insights_proposed,
        "unverifiable": job.insights_rejected_unverifiable,
        "skipped_reviewed": job.insights_skipped_reviewed,
        "log_tail": _tail(path),
        "last_change": _last_change(path),
    })


@require_POST
def extract(request, job_id):
    """Launch the extraction as a detached background process.

    Detached (start_new_session=True) so a gunicorn worker recycling mid-run
    does not kill a paid-for extraction, and so closing this tab does not
    either. docker-compose.yml's web service sets init: true for the other half
    of that: an orphaned child exiting 3 or 4 reparents to gunicorn's own
    Arbiter.reap_workers() and can halt the whole web server.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)

    if job.status == "running":
        # A double click must not run two extractions of the same job - the
        # second pass would double every insight the first one wrote, since the
        # loader's conflict gate only protects rows a reviewer has touched.
        return JsonResponse({
            "started": False,
            "message": "This batch is already extracting.",
        })

    try:
        get_extractor()
    except ValueError as exc:
        # The normal state for the route CLAUDE.md documents first: extraction
        # run by an agent on the host, writing payloads into mcp_cache/insights/
        # for "Load payloads" to pick up. Not an error, so it is not reported
        # as one.
        return JsonResponse({
            "started": False,
            "message": (
                f"No in-container model is configured ({exc}). Run the extraction "
                f"with an agent on the host, then use “Load payloads written by "
                f"the agent” on this job."
            ),
        })

    path = log_path(job)
    # Only exists once something has written a payload into it, so on a fresh
    # setup the very first click here would otherwise fail opening the log.
    path.parent.mkdir(parents=True, exist_ok=True)

    # Set to running and saved BEFORE launching: this request returns at once,
    # and the child is what moves the job on to "loaded" - or leaves it at
    # "running" if it dies, which is visible either way.
    job.status = "running"
    job.save(update_fields=["status"])

    with open(path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "manage.py", "extract_insights", "--job", str(job.id)],
            cwd=settings.BASE_DIR,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    return JsonResponse({"started": True, "message": "Extraction started."})
```

- [ ] **Step 4: Mount the two URLs**

In `DocumentsToInsightsAdmin.get_urls`, before `super()`:

```python
            path("job/<int:job_id>/extract/",
                 self.admin_site.admin_view(wizard.extract),
                 name="insights_wizard_extract"),
            path("job/<int:job_id>/progress/",
                 self.admin_site.admin_view(wizard.progress),
                 name="insights_wizard_progress"),
```

- [ ] **Step 5: Run the tests**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_extract -v 2
```

Expected: PASS, all six.

- [ ] **Step 6: Write the template**

Create `insights/templates/insights/wizard_extract.html`:

```html
{% extends "insights/wizard_base.html" %}
{% load static %}
{% block wizard_body %}
<div id="wiz-extract"
     data-progress-url="{% url 'admin:insights_wizard_progress' job.id %}"
     data-extract-url="{% url 'admin:insights_wizard_extract' job.id %}"
     data-review-url="{% url 'admin:insights_wizard_job' job.id %}"
     data-job-url="{% url 'admin:insights_extractionjob_change' job.id %}">
  {% csrf_token %}

  <h2>{{ job.label|default:job }}</h2>
  <p>{{ job.documents_total }} document(s) ready to read.</p>

  <p><button type="button" id="wiz-start" class="default">Start extraction</button></p>

  <div class="wiz-bar"><span id="wiz-bar-fill"></span></div>
  <p id="wiz-counters">Not started.</p>

  <div id="wiz-note" class="wiz-note" hidden></div>

  <h3>Log</h3>
  <pre class="wiz-log" id="wiz-log"></pre>

  <p>
    Closing this page does not stop the extraction. Come back to this batch from
    <a href="{% url 'admin:insights_documentstoinsights_changelist' %}">Part 1</a>.
    The job itself, with its full log and the reset action, is on
    <a href="{% url 'admin:insights_extractionjob_change' job.id %}">job {{ job.id }}</a>.
  </p>
</div>
<script src="{% static 'insights/wizard_extract.js' %}" defer></script>
{% endblock %}
```

- [ ] **Step 7: Write the JavaScript**

Create `insights/static/insights/wizard_extract.js`:

```js
/* Step 3: start the extraction, then watch it.
 *
 * POLLED, NOT STREAMED. An SSE connection would hold one of only eight
 * gunicorn threads (2 workers x 4) for the whole length of an LLM run over
 * every document in the batch. A 2-second poll costs nothing, survives a
 * slept laptop and a proxy timeout, and picks the run back up when the page
 * is reopened.
 *
 * The process itself is detached, so nothing here can kill it - including
 * closing the tab.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-extract");
  if (!root) { return; }

  var STALL_MS = 10 * 60 * 1000;
  var POLL_MS = 2000;

  var fill = document.getElementById("wiz-bar-fill");
  var counters = document.getElementById("wiz-counters");
  var note = document.getElementById("wiz-note");
  var log = document.getElementById("wiz-log");
  var startButton = document.getElementById("wiz-start");
  var timer = null;

  function csrf() {
    var field = root.querySelector("[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function say(text, kind) {
    note.textContent = text;
    note.className = "wiz-note" + (kind ? " is-" + kind : "");
    note.hidden = false;
  }

  function draw(body) {
    var pct = body.total ? Math.round(body.done * 100 / body.total) : 0;
    fill.style.width = pct + "%";
    counters.textContent =
      body.done + " of " + body.total + " documents · " +
      body.proposed + " statements proposed · " +
      body.unverifiable + " rejected as unverifiable · " +
      body.skipped_reviewed + " already reviewed";

    if (body.log_tail && body.log_tail !== log.textContent) {
      log.textContent = body.log_tail;
      log.scrollTop = log.scrollHeight;
    }

    if (body.status === "loaded") {
      stop();
      say("Extraction finished. Opening the review step…", null);
      window.location = root.dataset.reviewUrl;
      return;
    }

    if (body.status === "failed") {
      stop();
      startButton.disabled = false;
      startButton.textContent = "Try again";
      say("This run failed. The reason is at the end of the log above; the full " +
          "log is on the job itself.", "bad");
      return;
    }

    if (body.status === "running") {
      startButton.disabled = true;
      var since = body.last_change ? Date.now() - Date.parse(body.last_change) : 0;
      if (since > STALL_MS) {
        say("No progress since " + new Date(body.last_change).toLocaleTimeString() +
            ". If the container was restarted the run is gone and the job needs " +
            "resetting to queued — use “Reset stuck job to queued” on the job page. " +
            "Nothing here can tell a killed process from a slow one, so nothing " +
            "resets it automatically.", "warn");
      } else {
        note.hidden = true;
      }
    }
  }

  function poll() {
    fetch(root.dataset.progressUrl, { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(draw)
      .catch(function () { /* a dropped poll is not a failed run; try again */ });
  }

  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
  }

  function watch() {
    if (!timer) { timer = window.setInterval(poll, POLL_MS); }
    poll();
  }

  startButton.addEventListener("click", function () {
    startButton.disabled = true;
    fetch(root.dataset.extractUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() }
    }).then(function (response) { return response.json(); })
      .then(function (body) {
        if (body.started) { watch(); return; }
        startButton.disabled = false;
        say(body.message, "warn");
      });
  });

  poll();
  /* Already under way when the page opened - rejoin it. */
  fetch(root.dataset.progressUrl, { credentials: "same-origin" })
    .then(function (response) { return response.json(); })
    .then(function (body) { if (body.status === "running") { watch(); } });
}());
```

- [ ] **Step 8: Run the full suite and commit**

```bash
docker compose exec web python manage.py test insights -v 2
git add "Community Centered Humanitarian Analysis Platform/insights/wizard.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin.py" \
        "Community Centered Humanitarian Analysis Platform/insights/templates/insights/wizard_extract.html" \
        "Community Centered Humanitarian Analysis Platform/insights/static/insights/wizard_extract.js" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_wizard_extract.py"
git commit -m "insights: watch an extraction instead of refreshing a changelist

Polled rather than streamed - an SSE connection would hold one of eight
gunicorn threads for the length of an LLM run. The stall warning reads the log
file's mtime, because the job has no timestamp an auto_now field could fill:
the command saves with update_fields, which auto_now does not see.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 8: The review page, in read mode

**Files:**
- Modify: `insights/wizard.py`
- Modify: `insights/admin.py` (one more URL)
- Create: `insights/templates/insights/wizard_review.html`
- Create: `insights/templates/insights/_review_row.html`
- Test: `insights/tests/test_wizard_review.py`

**Interfaces:**
- Consumes: Task 3's `review.publish` / `review.reject`, Task 5's `job_step`.
- Produces:
  - `POST admin:insights_wizard_decide` `(job_id)` with `decision` (`publish`|`reject`) and `selected` (repeated insight ids) → redirect back to the review step
  - `_review_row.html` rendering one insight from context `{"insight": Insight}`

- [ ] **Step 1: Write the failing tests**

Create `insights/tests/test_wizard_review.py`:

```python
"""The review step shows one job's results and publishes what is chosen."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from data_track.models import Document
from insights.models import ExtractionJob, Insight, InsightCoding
from insights.verify import quote_sha1

QUOTE = "We walk four hours for water and the queue is longer every week."
OTHER = "The clinic closed when the staff left in March."


class ReviewStepTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.job = ExtractionJob.objects.create(status="loaded", label="2 files")
        self.doc = Document.objects.create(file_name="dtm.pdf", rel_path="insights/dtm.pdf")
        self.job.documents.add(self.doc)
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), document=self.doc, page=3,
            voice_type="community", channel="document_ai", stated_on="2026-04-02",
            iso3="TCD", status="pending", job=self.job, confidence="high")
        InsightCoding.objects.create(insight=self.insight, dimension="need", tag="water")
        self.other = Insight.objects.create(
            quote=OTHER, quote_sha1=quote_sha1(OTHER), document=self.doc, page=5,
            voice_type="community", channel="document_ai", stated_on="2026-04-02",
            iso3="TCD", status="pending", job=self.job)

    def url(self):
        return reverse("admin:insights_wizard_job", args=[self.job.id])

    def test_the_review_step_shows_the_quote_and_its_themes(self):
        body = self.client.get(self.url()).content.decode()
        self.assertIn(QUOTE, body)
        self.assertIn("need:water", body)
        self.assertIn("dtm.pdf", body)

    def test_it_shows_only_this_jobs_insights(self):
        stray = ExtractionJob.objects.create(status="loaded")
        Insight.objects.create(
            quote="Another batch entirely.", quote_sha1=quote_sha1("Another batch entirely."),
            voice_type="community", channel="document_ai", stated_on="2026-04-03",
            iso3="SDN", status="pending", job=stray)
        body = self.client.get(self.url()).content.decode()
        self.assertNotIn("Another batch entirely.", body)

    def test_publishing_the_selected_rows_only(self):
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "publish", "selected": [str(self.insight.id)]}, follow=True)
        self.insight.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.insight.status, "published")
        self.assertEqual(self.insight.reviewed_by_id, self.user.id)
        self.assertEqual(self.other.status, "pending")

    def test_rejecting_records_the_reviewer(self):
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "reject", "selected": [str(self.other.id)]}, follow=True)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, "rejected")
        self.assertEqual(self.other.reviewed_by_id, self.user.id)

    def test_a_decision_cannot_reach_another_jobs_insights(self):
        stray_job = ExtractionJob.objects.create(status="loaded")
        stray = Insight.objects.create(
            quote="Not this batch.", quote_sha1=quote_sha1("Not this batch."),
            voice_type="community", channel="document_ai", stated_on="2026-04-03",
            iso3="SDN", status="pending", job=stray_job)
        self.client.post(
            reverse("admin:insights_wizard_decide", args=[self.job.id]),
            {"decision": "publish", "selected": [str(stray.id)]}, follow=True)
        stray.refresh_from_db()
        self.assertEqual(stray.status, "pending")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_review -v 2
```

Expected: FAIL — `NoReverseMatch: Reverse for 'insights_wizard_decide' not found`.

- [ ] **Step 3: Write the view**

Add to `insights/wizard.py`:

```python
from django.contrib import messages
from django.urls import reverse

from insights import review
from insights.models import Insight
```

```python
def _job_insights(job):
    """This job's statements, grouped the way they are read: by document, by page."""
    return (Insight.objects.filter(job=job)
            .select_related("document")
            .prefetch_related("codings")
            .order_by("document__file_name", "page", "id"))


@require_POST
def decide(request, job_id):
    """Publish or reject the selected statements.

    SCOPED TO THIS JOB. The ids come from a form, so they are the client's to
    choose; filtering on the job as well means a tampered form cannot publish
    somebody else's pending review queue.
    """
    job = get_object_or_404(ExtractionJob, id=job_id)
    chosen = Insight.objects.filter(job=job, id__in=request.POST.getlist("selected"))

    if request.POST.get("decision") == "publish":
        moved = review.publish(chosen, request.user)
        messages.success(request, f"{moved} published.")
    else:
        moved = review.reject(chosen, request.user)
        messages.warning(
            request,
            f"{moved} rejected. Add a reason on each one - a rejected extraction "
            f"is evidence about the model, not rubbish.")

    return redirect(reverse("admin:insights_wizard_job", args=[job.id]))
```

and extend `job_step`'s final branch to pass the rows:

```python
    return render(request, "insights/wizard_review.html",
                  page(request, job=job, wizard_step=4, insights=_job_insights(job)))
```

- [ ] **Step 4: Mount the URL**

In `DocumentsToInsightsAdmin.get_urls`, before `super()`:

```python
            path("job/<int:job_id>/decide/",
                 self.admin_site.admin_view(wizard.decide),
                 name="insights_wizard_decide"),
```

- [ ] **Step 5: Write the row partial**

Create `insights/templates/insights/_review_row.html`:

```html
{% comment %}
One statement in read mode. A partial because the inline editor returns this
same markup after a successful save - the row redraws itself rather than the
page reloading and losing the reviewer's place in a long queue.
{% endcomment %}
<tr class="wiz-review-row" data-insight="{{ insight.id }}">
  <td><input type="checkbox" name="selected" value="{{ insight.id }}"
             form="wiz-decide" {% if insight.status != "pending" %}disabled{% endif %}></td>
  <td>
    <blockquote>{{ insight.quote }}</blockquote>
    <small>
      {% for coding in insight.codings.all %}{{ coding.dimension }}:{{ coding.tag }}{% if not forloop.last %}, {% endif %}{% empty %}no themes{% endfor %}
      · {{ insight.iso3 }}{% if insight.place_name_as_written %} — {{ insight.place_name_as_written }}{% endif %}
      {% if insight.admin_pcode %}({{ insight.admin_pcode }}, {{ insight.match_method }}){% else %}(country only, nothing drawn on the map){% endif %}
      · page {{ insight.page|default:"?" }}
      · {{ insight.confidence|default:"confidence not stated" }}
      · <b>{{ insight.status }}</b>
    </small>
  </td>
  <td><button type="button" class="wiz-edit" data-insight="{{ insight.id }}">Edit</button></td>
</tr>
```

- [ ] **Step 6: Write the review template**

Create `insights/templates/insights/wizard_review.html`:

```html
{% extends "insights/wizard_base.html" %}
{% load static %}
{% block wizard_body %}
<h2>{{ job.label|default:job }}</h2>
<p>{{ insights|length }} statement(s) from {{ job.documents_total }} document(s).
   Read them, correct anything the model got wrong, then publish the ones that
   should reach the dashboard. Nothing publishes itself.</p>

<form id="wiz-decide" method="post"
      action="{% url 'admin:insights_wizard_decide' job.id %}">{% csrf_token %}
</form>

<div id="wiz-review"
     data-edit-url="{% url 'admin:insights_wizard_edit' 0 %}">
  <table class="wiz-files">
    <tbody>
      {% for insight in insights %}
        {% include "insights/_review_row.html" %}
      {% empty %}
        <tr><td>Nothing was extracted from this batch. The log on
            <a href="{% url 'admin:insights_extractionjob_change' job.id %}">job {{ job.id }}</a>
            says why.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>

{% if insights %}
<p>
  <button type="submit" form="wiz-decide" name="decision" value="publish" class="default">Publish selected</button>
  <button type="submit" form="wiz-decide" name="decision" value="reject">Reject selected</button>
</p>
{% endif %}
<script src="{% static 'insights/wizard_review.js' %}" defer></script>
{% endblock %}
```

`insights_wizard_edit` arrives in Task 9. Add its stub to `insights/wizard.py` now so this page can be reversed:

```python
def edit(request, insight_id):
    """One insight's inline editor. Filled in by Task 9."""
    raise NotImplementedError
```

and its URL, before `super()`:

```python
            path("insight/<int:insight_id>/edit/",
                 self.admin_site.admin_view(wizard.edit),
                 name="insights_wizard_edit"),
```

Create `insights/static/insights/wizard_review.js` as an empty placeholder with the file's docstring comment; Task 9 fills it in:

```js
/* Step 4: fetch an edit panel into a row, and put the row back after a save.
 * Filled in by Task 9. */
```

- [ ] **Step 7: Run the tests**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_review -v 2
```

Expected: PASS, all five.

- [ ] **Step 8: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/wizard.py" \
        "Community Centered Humanitarian Analysis Platform/insights/admin.py" \
        "Community Centered Humanitarian Analysis Platform/insights/templates/insights/wizard_review.html" \
        "Community Centered Humanitarian Analysis Platform/insights/templates/insights/_review_row.html" \
        "Community Centered Humanitarian Analysis Platform/insights/static/insights/wizard_review.js" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_wizard_review.py"
git commit -m "insights: read a batch's results and publish what is chosen

Scoped to the job on the server as well as in the form - the ids are the
client's to choose, and a tampered form must not reach another batch's queue.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 9: Correcting a statement without leaving the page

**Files:**
- Modify: `insights/forms.py` (`data-place-role` attributes, `InsightInlineEditForm`)
- Modify: `insights/static/insights/place_picker.js` (bind to a container)
- Modify: `insights/wizard.py` (`edit`)
- Create: `insights/templates/insights/_edit_panel.html`
- Modify: `insights/static/insights/wizard_review.js`
- Test: `insights/tests/test_wizard_edit.py`

**Interfaces:**
- Consumes: Task 8's `_review_row.html` and `edit` stub.
- Produces:
  - `insights.forms.InsightInlineEditForm` — `InsightPlaceForm` narrowed to the fields a reviewer corrects
  - `GET admin:insights_wizard_edit` `(insight_id)` → the rendered panel
  - `POST` same URL → `{"saved": true, "row": "<tr>…</tr>"}` or `{"saved": false, "panel": "<form>…</form>"}`
  - `window.insightsPlacePicker.bind(root)` — binds the three dropdowns inside `root`

- [ ] **Step 1: Write the failing tests**

Create `insights/tests/test_wizard_edit.py`:

```python
"""Correcting a statement in the review page is the same form, not a copy of it.

The two rules that matter are InsightPlaceForm's, and they are tested here
because this is a second caller of it: a changed pick re-derives the five
machine columns, and an untouched one leaves them exactly as the extractor
wrote them - including a row below ADM2, which the three dropdowns cannot
express at all.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from boundaries.models import AdminArea
from insights.models import ExtractionJob, Insight
from insights.verify import quote_sha1

QUOTE = "The pump broke before the rains and no one has come."


class InlineEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        self.country = AdminArea.objects.create(
            kind=AdminArea.KIND_ADMIN, level=0, pcode="TD", iso3="TCD",
            country_name="Chad", name="Chad")
        self.state = AdminArea.objects.create(
            kind=AdminArea.KIND_ADMIN, level=1, pcode="TD01", iso3="TCD",
            country_name="Chad", name="Ouaddai", parent_pcode="TD",
            center_lat=13.8, center_lon=20.8)
        self.job = ExtractionJob.objects.create(status="loaded")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="document_ai", stated_on="2026-04-02", iso3="TCD",
            status="pending", job=self.job, match_method="unmatched")

    def url(self):
        return reverse("admin:insights_wizard_edit", args=[self.insight.id])

    def post_data(self, **overrides):
        prefix = f"insight-{self.insight.id}"
        data = {
            f"{prefix}-quote": QUOTE,
            f"{prefix}-quote_language": "en",
            f"{prefix}-voice_type": "community",
            f"{prefix}-channel": "document_ai",
            f"{prefix}-stated_on": "2026-04-02",
            f"{prefix}-country": "TCD",
            f"{prefix}-state": "",
            f"{prefix}-district": "",
            f"{prefix}-method": "llm",
            f"{prefix}-status": "pending",
            f"{prefix}-codings-TOTAL_FORMS": "0",
            f"{prefix}-codings-INITIAL_FORMS": "0",
            f"{prefix}-codings-MIN_NUM_FORMS": "0",
            f"{prefix}-codings-MAX_NUM_FORMS": "1000",
        }
        data.update({f"{prefix}-{key}": value for key, value in overrides.items()})
        return data

    def test_the_panel_renders_the_three_dropdowns(self):
        body = self.client.get(self.url()).content.decode()
        self.assertIn(f"insight-{self.insight.id}-country", body)
        self.assertIn(f"insight-{self.insight.id}-state", body)
        self.assertIn(f"insight-{self.insight.id}-district", body)

    def test_picking_a_state_derives_the_machine_columns(self):
        response = self.client.post(self.url(), self.post_data(state="TD01"))
        self.insight.refresh_from_db()
        self.assertTrue(response.json()["saved"])
        self.assertEqual(self.insight.admin_pcode, "TD01")
        self.assertEqual(self.insight.admin_level, 1)
        self.assertEqual(self.insight.match_method, "pcode")
        self.assertAlmostEqual(self.insight.lat, 13.8)

    def test_an_untouched_place_is_left_exactly_as_it_was(self):
        # A row the matcher reached by NAME, below the level the dropdowns can
        # express. Saving a change to something else must not move it.
        self.insight.admin_pcode = "TD0103"
        self.insight.admin_level = 3
        self.insight.match_method = "name"
        self.insight.save()
        self.client.post(self.url(), self.post_data(
            state="TD01", rejection_reason="checked against the source"))
        self.insight.refresh_from_db()
        self.assertEqual(self.insight.admin_pcode, "TD0103")
        self.assertEqual(self.insight.admin_level, 3)
        self.assertEqual(self.insight.match_method, "name")

    def test_a_state_from_the_wrong_country_is_refused(self):
        other = AdminArea.objects.create(
            kind=AdminArea.KIND_ADMIN, level=1, pcode="SD01", iso3="SDN",
            country_name="Sudan", name="Kassala", parent_pcode="SD")
        response = self.client.post(self.url(), self.post_data(state=other.pcode))
        self.insight.refresh_from_db()
        self.assertFalse(response.json()["saved"])
        self.assertIsNone(self.insight.admin_pcode)

    def test_a_successful_save_returns_the_row_in_read_mode(self):
        body = self.client.post(self.url(), self.post_data(state="TD01")).json()
        self.assertIn("wiz-review-row", body["row"])
        self.assertIn(QUOTE, body["row"])
```

Check `boundaries/models.py` for `AdminArea`'s exact required fields before running — if `KIND_ADMIN` or a field name differs, match the fixtures already used in `insights/tests/test_places.py` rather than inventing them.

- [ ] **Step 2: Run them to verify they fail**

```bash
docker compose exec web python manage.py test insights.tests.test_wizard_edit -v 2
```

Expected: FAIL — `NotImplementedError` from the Task 8 stub.

- [ ] **Step 3: Tag the three dropdowns so they can be found without ids**

In `insights/forms.py`, in `InsightPlaceForm.__init__`, after the `data-place-options-url` line:

```python
        # Found by role, not by id. The review page renders one of these forms
        # per row with a prefix, so "id_country" is neither unique nor present.
        for name, role in (("country", "country"), ("state", "state"),
                           ("district", "district")):
            self.fields[name].widget.attrs["data-place-role"] = role
```

- [ ] **Step 4: Add the narrowed form**

In `insights/forms.py`, after `InsightPlaceForm`:

```python
class InsightInlineEditForm(InsightPlaceForm):
    """InsightPlaceForm, narrowed to what a reviewer corrects in the review page.

    A subclass rather than a second form: every rule that makes the place safe
    - the server-side choice rebuild, clean()'s country check, save()'s "only
    re-derive when the pick actually changed" - is inherited, not re-stated.

    The field list exists because InsightPlaceForm uses Meta.exclude, so outside
    the admin's own fieldsets it would render `document` and `job` as selects
    over every document and every job in the database.
    """

    class Meta(InsightPlaceForm.Meta):
        fields = ("quote", "quote_language", "quote_translated", "voice_type",
                  "channel", "stated_on", "place_name_as_written",
                  "people_affected", "severity", "confidence", "method",
                  "status", "rejection_reason")
        exclude = None
```

- [ ] **Step 5: Make the place picker bind to a container**

Rewrite `insights/static/insights/place_picker.js`'s `ready` block so the body becomes a reusable `bind(root)`. Keep everything inside `fill` and `load` exactly as it is; change only how the three elements are found and how binding is triggered:

```js
  function bind(root) {
    var country = root.querySelector("[data-place-role=country]");
    var state = root.querySelector("[data-place-role=state]");
    var district = root.querySelector("[data-place-role=district]");
    if (!country || !state || !district) { return; }
    if (country.dataset.placeBound) { return; }
    country.dataset.placeBound = "1";

    var endpoint = country.dataset.placeOptionsUrl;
    if (!endpoint) { return; }

    /* ... fill() and load() unchanged ... */

    country.addEventListener("change", function () {
      fill(district, [], "");
      load(state, country.value, 1, "");
    });

    state.addEventListener("change", function () {
      load(district, state.value, 2, "");
    });
  }

  /* The admin change form has exactly one of these and it is in the page at
   * load. The review page has one per row and injects them later, so it calls
   * bind() itself - hence the guard above, which keeps a second call on an
   * already-bound panel from stacking a duplicate listener. */
  window.insightsPlacePicker = { bind: bind };
  ready(function () { bind(document); });
```

- [ ] **Step 6: Write the panel template**

Create `insights/templates/insights/_edit_panel.html`:

```html
{% comment %}
One insight's editor, fetched into its row on demand. Lazy, because rendering
a form for every statement up front would make a 200-row review page heavy in
read mode, which is the mode it is mostly in.
{% endcomment %}
<form class="wiz-edit-panel" method="post"
      action="{% url 'admin:insights_wizard_edit' insight.id %}">
  {% csrf_token %}
  {{ form.as_p }}
  <h4>Themes</h4>
  {{ formset.management_form }}
  <table class="wiz-files"><tbody class="wiz-coding-rows">
    {% for coding in formset %}
      <tr class="wiz-coding-row">{{ coding.id }}<td>{{ coding.dimension }}</td>
          <td>{{ coding.tag }}</td><td>{{ coding.DELETE }} remove</td></tr>
    {% endfor %}
  </tbody></table>
  <template class="wiz-coding-template">
    <tr class="wiz-coding-row">{{ formset.empty_form.id }}<td>{{ formset.empty_form.dimension }}</td>
        <td>{{ formset.empty_form.tag }}</td><td>{{ formset.empty_form.DELETE }} remove</td></tr>
  </template>
  <p>
    <button type="button" class="wiz-add-coding">Add a theme</button>
    <button type="submit" class="default">Save</button>
    <button type="button" class="wiz-cancel">Cancel</button>
  </p>
</form>
```

- [ ] **Step 7: Write the view**

Replace the `edit` stub in `insights/wizard.py`:

```python
from django.forms import inlineformset_factory
from django.template.loader import render_to_string

from insights.forms import InsightInlineEditForm
from insights.models import InsightCoding

CodingFormSet = inlineformset_factory(
    Insight, InsightCoding, fields=("dimension", "tag"), extra=1, can_delete=True)


def edit(request, insight_id):
    """One statement's editor, and the save behind it.

    An inlineformset_factory rather than the admin's TabularInline: that class
    only exists inside an admin change view and leans on admin's own inlines.js.
    Outside it, empty_form plus a few lines of JavaScript is the whole feature.
    """
    insight = get_object_or_404(Insight, id=insight_id)
    prefix = f"insight-{insight.id}"
    coding_prefix = f"{prefix}-codings"

    if request.method == "POST":
        form = InsightInlineEditForm(request.POST, instance=insight, prefix=prefix)
        formset = CodingFormSet(request.POST, instance=insight, prefix=coding_prefix)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            insight.refresh_from_db()
            return JsonResponse({
                "saved": True,
                "row": render_to_string(
                    "insights/_review_row.html", {"insight": insight}, request=request),
            })
        return JsonResponse({
            "saved": False,
            "panel": render_to_string(
                "insights/_edit_panel.html",
                {"insight": insight, "form": form, "formset": formset}, request=request),
        })

    return render(request, "insights/_edit_panel.html", {
        "insight": insight,
        "form": InsightInlineEditForm(instance=insight, prefix=prefix),
        "formset": CodingFormSet(instance=insight, prefix=coding_prefix),
    })
```

- [ ] **Step 8: Write the review page's JavaScript**

Replace `insights/static/insights/wizard_review.js`:

```js
/* Step 4: fetch an edit panel into a row, and put the row back after a save.
 *
 * The panel is the same InsightPlaceForm the Insights screen uses, rendered
 * server-side with a per-row prefix. Nothing about place resolution is decided
 * here - this file moves markup around and nothing else.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-review");
  if (!root) { return; }

  function panelUrl(id) {
    return root.dataset.editUrl.replace("/0/", "/" + id + "/");
  }

  function closePanel(row) {
    var open = row.nextElementSibling;
    if (open && open.classList.contains("wiz-edit-holder")) { open.remove(); }
  }

  function wire(holder, row, id) {
    var form = holder.querySelector("form");
    if (window.insightsPlacePicker) { window.insightsPlacePicker.bind(form); }

    form.querySelector(".wiz-cancel").addEventListener("click", function () {
      closePanel(row);
    });

    /* A formset grows by cloning its own empty_form and renumbering it - the
     * __prefix__ placeholder is what Django puts there for exactly this. */
    form.querySelector(".wiz-add-coding").addEventListener("click", function () {
      var total = form.querySelector("[name$='-TOTAL_FORMS']");
      var body = form.querySelector(".wiz-coding-rows");
      var template = form.querySelector(".wiz-coding-template").innerHTML;
      body.insertAdjacentHTML(
        "beforeend", template.replace(/__prefix__/g, total.value));
      total.value = String(Number(total.value) + 1);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      fetch(panelUrl(id), {
        method: "POST",
        credentials: "same-origin",
        body: new FormData(form)
      }).then(function (response) { return response.json(); })
        .then(function (body) {
          if (body.saved) {
            row.outerHTML = body.row;
            /* row is detached now; find the replacement to close under it. */
            var fresh = root.querySelector("[data-insight='" + id + "']");
            closePanel(fresh);
            return;
          }
          holder.querySelector("td").innerHTML = body.panel;
          wire(holder, row, id);
        });
    });
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest(".wiz-edit");
    if (!button) { return; }

    var id = button.dataset.insight;
    var row = button.closest("tr");
    if (row.nextElementSibling &&
        row.nextElementSibling.classList.contains("wiz-edit-holder")) {
      closePanel(row);
      return;
    }

    fetch(panelUrl(id), { credentials: "same-origin" })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var holder = document.createElement("tr");
        holder.className = "wiz-edit-holder";
        holder.innerHTML = "<td colspan='3'>" + html + "</td>";
        row.insertAdjacentElement("afterend", holder);
        wire(holder, row, id);
      });
  });
}());
```

- [ ] **Step 9: Run the tests**

```bash
docker compose exec web python manage.py test insights -v 2
```

Expected: PASS. In particular `test_an_untouched_place_is_left_exactly_as_it_was` must pass — it is the proof that the inherited `save()` still behaves, and it is the single most likely thing to break.

- [ ] **Step 10: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/insights/forms.py" \
        "Community Centered Humanitarian Analysis Platform/insights/wizard.py" \
        "Community Centered Humanitarian Analysis Platform/insights/static/insights/place_picker.js" \
        "Community Centered Humanitarian Analysis Platform/insights/static/insights/wizard_review.js" \
        "Community Centered Humanitarian Analysis Platform/insights/templates/insights/_edit_panel.html" \
        "Community Centered Humanitarian Analysis Platform/insights/tests/test_wizard_edit.py"
git commit -m "insights: correct a statement without leaving the review page

The panel is InsightPlaceForm itself, fetched per row with a prefix, so the
rules that keep a place derived rather than typed are inherited rather than
restated. place_picker.js now binds to a container instead of hardcoded ids,
because a review page has one set of dropdowns per row and injects them late.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

### Task 10: Document the route, and walk it

**Files:**
- Modify: `CLAUDE.md`
- Modify: `Community Centered Humanitarian Analysis Platform/insights/apps.py`
- Test: a full browser walkthrough

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: nothing code depends on.

- [ ] **Step 1: Name the section for what it now holds**

In `insights/apps.py`:

```python
    verbose_name = "Community insights (documents in, statements out)"
```

- [ ] **Step 2: Document the wizard in CLAUDE.md**

Under "### 2. Extract community insights from documents", after the existing paragraph:

```markdown
The route in is **Admin → Community insights → Part 1 — Documents → insights**:
pick files or a folder from a native window on your own machine, check the
preview, extract (watchable, and it survives the tab closing), then review and
publish. `insights/prompts/extract_insights.md` remains the single source of
truth for the extraction itself.

An archive already sitting on a mounted share should be registered as an
`InsightFolder` instead — nothing is copied that way. Which folders may be
browsed is `INSIGHT_DOCUMENT_ROOTS`; there is no hardcoded `/work` any more.
```

- [ ] **Step 3: Run everything**

```bash
docker compose exec web python manage.py test -v 2
```

Expected: PASS across every app, not just `insights` — Task 1 touched `config/settings.py`, which every app reads.

- [ ] **Step 4: Walk the whole wizard in a browser**

```bash
docker compose restart web
```

Open `http://localhost:2026/admin/`, and confirm end to end:

1. The Community insights section shows **two** entries, not five.
2. "Start a new batch" → "Choose a folder" → pick a folder holding two or three PDFs plus a non-document. The preview lists all of them; the non-document is greyed out.
3. "Read these documents" fills in page counts and lands on the extract step.
4. With no `LLM_PROVIDER` set, "Start extraction" explains that and points at "Load payloads". With one set, the bar moves and the log fills.
5. Closing the tab mid-run and reopening Part 1 → "Open" rejoins the running batch.
6. On review: Edit expands a row, the country dropdown fills the state dropdown, Save collapses the row and redraws it.
7. Select two rows → "Publish selected" → both show `published`, and they appear at `/api/insights/`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md "Community Centered Humanitarian Analysis Platform/insights/apps.py"
git commit -m "insights: document the wizard as the route in

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WSbgpy6yMZPWn7axNKbrGP"
```

---

## Notes for the executor

- **`wizard.page(request, ...)` is how every wizard page gets its context.** `admin_view()` adds the permission check and the login redirect and nothing else, so a page rendered without `page()` comes out as an unstyled orphan with no admin header and no way back. If that is what you are looking at, that call is what is missing.
- **Template changes need `docker compose restart web`** to be picked up; Python changes are reloaded by gunicorn on their own only if the container is restarted too, so restart after any task that changes a `.py` file before walking a page by hand.
- **Never pull two IPC countries in parallel** — unrelated to this plan, but it is in CLAUDE.md and a session that wanders into external data should know it.
- If a task's test fails for a reason the plan did not anticipate, **stop and report** rather than adjusting the test to pass. The tests here encode rules from the spec; a test that needs changing means the spec needs changing.
