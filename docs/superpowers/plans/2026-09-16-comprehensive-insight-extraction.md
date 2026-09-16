# Comprehensive Insight Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the insights extraction from community voice alone to the full situational read of a document — movement corridors and their numbers, the reasons behind them, hazards, who is vulnerable and why, coping and needs — each anchored to a verbatim quote and geocoded where the text supports it.

**Architecture:** Three additions, all hanging off the existing `Insight` row, which itself gains no columns: a `role` column on `InsightCoding` records cause as a link between two codings rather than as prose; a new `InsightFigure` child table stores a share as a share; a new `InsightMovement` child table holds one complete corridor per row with both ends resolved independently through the existing `places.resolve()`. Every number carries the span as printed so it can be checked against the quote, and a bad figure costs its own row rather than the document.

**Tech Stack:** Django 5 + PostGIS, PyMuPDF for page text, Anthropic and OpenAI-compatible LLM adapters, Django admin + a server-rendered wizard. Everything runs in Docker; there is no Django environment on the host.

**Spec:** `docs/superpowers/specs/2026-09-16-comprehensive-insight-extraction-design.md` — read it alongside this plan. Each task below cites the spec section it implements.

## Global Constraints

- **Everything runs in Docker.** Every command in this plan is `docker compose exec web python manage.py …`. There is no Django environment on the host; do not try to run `manage.py` directly.
- On Windows/Git Bash, if a `docker compose exec` command containing an absolute path mangles the path, prefix it with `MSYS_NO_PATHCONV=1`. Commands in this plan have no absolute paths and do not need it.
- **Run one app's tests:** `docker compose exec web python manage.py test insights -v 2`
- **Run one test:** `docker compose exec web python manage.py test insights.tests.test_contract.ParseTests.test_name -v 2`
- **Exactly one migration** is added by this plan, in Task 2. It is additive, with no backfill. Do not create a second one; if a later task needs a model change, amend Task 2's migration and re-run it.
- **Everything new is optional in the payload.** `codings[].role`, `figures[]` and `movements[]` all default to absent. A payload written before today must still validate and still produce rows identical in every pre-existing column. Task 1 pins this and it must stay green through every later task.
- **`Insight` gains no columns.** All three additions are a column on an existing child table and two new child tables. If a task seems to need a column on `Insight`, stop and re-read spec §4.5.
- **Closed vocabularies, copied verbatim from spec §5 and §6.3:**
  - `CODING_ROLES` = `subject`, `driver`, `barrier` (default `subject`)
  - `FIGURE_UNITS` = `people`, `percent`, `households`
  - `MOVEMENT_UNITS` = `people`, `households` (a corridor is never a share)
  - `FLOW_TYPES` = `cross_border`, `internal`, `return`, `transit`
- **A bad vocabulary word drops its own row, never the payload** (spec §6.3). `ContractError` on the whole payload is reserved for a malformed *shape*: `figures` not a list, a figure that is not an object, a missing required key.
- **Follow the repo's test naming.** Tests read as sentences: `test_a_verifiable_insight_is_written_as_pending`, not `test_loader_1`.
- **Commit after every task.** Co-author trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `insights/tests/fixtures/payload_legacy.json` | Frozen copy of today's payload shape — the backwards-compatibility anchor | 1 |
| `insights/tests/test_backwards_compat.py` | Pins that a pre-widening payload still loads unchanged | 1 |
| `insights/models.py` | `CODING_ROLES`/`FIGURE_UNITS`/`MOVEMENT_UNITS`/`FLOW_TYPES`, `InsightCoding.role`, `InsightFigure`, `InsightMovement`, two `ExtractionJob` counters | 2 |
| `insights/migrations/0005_comprehensive_extraction.py` | The one additive migration | 2 |
| `insights/contract.py` | Parses and row-level-validates `role`, `figures[]`, `movements[]`; checks each number's span against the quote | 3 |
| `insights/tests/fixtures/payload_comprehensive.json` | A payload exercising figures, movements and roles | 3 |
| `insights/loader.py` | Writes the children, resolves both corridor ends, replaces children wholesale, counts drops | 4 |
| `insights/prompts/extract_insights.md` | The widened prompt — single source of truth for the extraction | 5 |
| `insights/extractors/anthropic_api.py` | `SCHEMA` — the third half of the contract; `additionalProperties: False` makes this load-bearing | 5 |
| `insights/views.py` | Serialises `figures`, `movements`, `role`; `?role=` and `?flow_type=` filters | 6 |
| `insights/admin.py` | `InsightFigureInline`, `InsightMovementInline`, `role` on the coding inline | 7 |
| `insights/templates/insights/_review_row.html` | Read-only display of figures and corridors under the quote | 7 |
| `insights/wizard.py:233-234` | Prefetch the new children so the review list does not N+1 | 7 |

---

### Task 1: Pin today's behaviour before anything changes

Spec §6.1, §10.1. This task adds no feature. It freezes what a pre-widening payload does, so that every later task has a tripwire. Write it first, while the new fields do not exist — that is what makes it honest.

**Files:**
- Create: `insights/tests/fixtures/payload_legacy.json`
- Create: `insights/tests/test_backwards_compat.py`

**Interfaces:**
- Consumes: `insights.loader.load(payload, document)` → `LoadReport(written, rejected_unverifiable, skipped_reviewed)`, as it exists today.
- Produces: `payload_legacy.json`, referenced by Task 3 and Task 4 tests. Do not edit it after this task — its whole value is being frozen.

- [ ] **Step 1: Create the frozen fixture**

Create `insights/tests/fixtures/payload_legacy.json`. This is a byte-for-byte copy of `payload_ok.json` under a name that says why it exists:

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

- [ ] **Step 2: Write the characterisation test**

Create `insights/tests/test_backwards_compat.py`:

```python
"""A payload written before the extraction was widened must keep working.

This file is a tripwire, not a feature test. Everything the comprehensive
extraction adds - codings[].role, figures[], movements[] - is optional, and the
day one of them stops being optional is the day every payload already sitting in
data_pipeline/mcp_cache/insights/ becomes unloadable. That failure would be
silent: a re-run would simply write fewer rows.

payload_legacy.json is frozen on purpose. Do not add new fields to it.
"""
import json
from pathlib import Path

from django.test import TestCase

from data_track.models import Document, DocumentText
from insights.loader import load
from insights.models import Insight

FIXTURES = Path(__file__).parent / "fixtures"
QUOTE = ("When it rains we get flash floods, and with the fighting around us the "
         "hospitals are gone — we have cholera now and nowhere to take the sick.")


class LegacyPayloadTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="x.pdf", rel_path="insights/x.pdf", report_date="2026-03-14")
        DocumentText.objects.create(
            document=self.doc, page=7, text=f"Participants said: “{QUOTE}”")
        self.payload = json.loads(
            (FIXTURES / "payload_legacy.json").read_text(encoding="utf-8"))

    def test_a_payload_with_no_new_blocks_still_loads(self):
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(report.rejected_unverifiable, 0)

    def test_every_pre_existing_column_is_unchanged(self):
        load(self.payload, self.doc)
        row = Insight.objects.get()
        self.assertEqual(row.quote, QUOTE)
        self.assertEqual(row.quote_language, "en")
        self.assertEqual(row.voice_type, "community")
        self.assertEqual(row.channel, "document_ai")
        self.assertEqual(row.page, 7)
        self.assertEqual(row.iso3, "ETH")
        self.assertEqual(row.place_name_as_written, "Afar")
        self.assertEqual(row.severity, 4)
        self.assertEqual(row.confidence, "high")
        self.assertIsNone(row.people_affected)
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.stated_on.isoformat(), "2026-03-14")

    def test_the_codings_are_unchanged(self):
        load(self.payload, self.doc)
        codings = set(Insight.objects.get().codings.values_list("dimension", "tag"))
        self.assertEqual(
            codings,
            {("hazard", "flooding"), ("hazard", "disease_outbreak"),
             ("need", "health"), ("need", "other")},
        )
```

- [ ] **Step 3: Run it and watch it pass**

Run: `docker compose exec web python manage.py test insights.tests.test_backwards_compat -v 2`
Expected: **PASS**, 3 tests. This is the one test in the plan that passes the moment it is written — it describes behaviour that already exists. If it fails now, stop: the working tree is not clean and nothing below can be trusted.

- [ ] **Step 4: Commit**

```bash
git add insights/tests/fixtures/payload_legacy.json insights/tests/test_backwards_compat.py
git commit -m "test: pin pre-widening payload behaviour

A tripwire for the comprehensive extraction: everything it adds is
optional, and the day one of them stops being optional every payload
already in mcp_cache/insights/ becomes unloadable - silently, as a
re-run that simply writes fewer rows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The data model and the one migration

Spec §5.1, §5.2, §5.3, §6.3 (the counters).

**Files:**
- Modify: `insights/models.py` — add four vocabulary constants, `InsightCoding.role`, two new models, two `ExtractionJob` counters
- Create: `insights/migrations/0005_comprehensive_extraction.py` (generated, then checked)
- Create: `insights/tests/test_models_children.py`

**Interfaces:**
- Produces, and every later task imports these by exact name:
  - `insights.models.CODING_ROLES` — list of `(value, label)` pairs; `insights.models.ROLE_VALUES` — a `set` of the values, for the contract
  - `insights.models.FIGURE_UNITS` / `FIGURE_UNIT_VALUES`
  - `insights.models.MOVEMENT_UNITS` / `MOVEMENT_UNIT_VALUES`
  - `insights.models.FLOW_TYPES` / `FLOW_TYPE_VALUES`
  - `insights.models.InsightFigure` with `insight, figure_as_written, value, unit, measures, applies_to`; related name `figures`
  - `insights.models.InsightMovement` with the origin/dest blocks below; related name `movements`
  - `insights.models.InsightCoding.role`
  - `ExtractionJob.figures_rejected`, `ExtractionJob.movements_rejected`

- [ ] **Step 1: Write the failing model tests**

Create `insights/tests/test_models_children.py`:

```python
"""The two child tables, and the constraint that had to widen to admit a role."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from insights.models import (
    Insight, InsightCoding, InsightFigure, InsightMovement,
)


def an_insight(**kwargs):
    fields = dict(quote="Nearly 58 percent face moderate to severe food insecurity.",
                  iso3="EGY", stated_on="2026-03-01")
    fields.update(kwargs)
    return Insight.objects.create(**fields)


class CodingRoleTests(TestCase):
    def test_a_coding_defaults_to_subject(self):
        """Every row written before this column existed means 'subject'."""
        coding = InsightCoding.objects.create(
            insight=an_insight(), dimension="hazard", tag="flooding")
        self.assertEqual(coding.role, "subject")

    def test_the_same_tag_may_appear_in_two_roles(self):
        """'return_movement' as the thing happening, and as what drives a need."""
        insight = an_insight()
        InsightCoding.objects.create(
            insight=insight, dimension="movement_pattern", tag="return_movement",
            role="subject")
        InsightCoding.objects.create(
            insight=insight, dimension="movement_pattern", tag="return_movement",
            role="driver")
        self.assertEqual(insight.codings.count(), 2)

    def test_a_true_duplicate_is_still_rejected(self):
        insight = an_insight()
        InsightCoding.objects.create(
            insight=insight, dimension="hazard", tag="flooding", role="driver")
        with self.assertRaises(IntegrityError), transaction.atomic():
            InsightCoding.objects.create(
                insight=insight, dimension="hazard", tag="flooding", role="driver")


class FigureTests(TestCase):
    def test_a_share_is_stored_as_a_share(self):
        """people_affected is a BigIntegerField and cannot hold 58 percent."""
        figure = InsightFigure.objects.create(
            insight=an_insight(),
            figure_as_written="Nearly 58 percent",
            value=58.0,
            unit="percent",
            measures="face moderate to severe food insecurity",
        )
        self.assertEqual(figure.value, 58.0)
        self.assertIsNone(figure.applies_to)

    def test_one_quote_carries_several_figures_with_their_subgroups(self):
        """EVAR p.22 states three in one passage; flattening would keep one."""
        insight = an_insight()
        for written, value, applies_to in (
            ("44 percent", 44.0, None),
            ("36 percent", 36.0, "non-Arabic speaking households"),
            ("26 percent", 26.0, "other regions"),
        ):
            InsightFigure.objects.create(
                insight=insight, figure_as_written=written, value=value,
                unit="percent", measures="report having access to informal credit",
                applies_to=applies_to)
        self.assertEqual(insight.figures.count(), 3)


class MovementTests(TestCase):
    def test_a_corridor_holds_two_independently_resolved_ends(self):
        movement = InsightMovement.objects.create(
            insight=an_insight(),
            origin_name_as_written="Sudan", origin_iso3="SDN",
            dest_name_as_written="Egypt", dest_iso3="EGY",
            flow_type="cross_border",
            value_as_written="0.7 million", value=700000, unit="people",
        )
        self.assertEqual(movement.origin_iso3, "SDN")
        self.assertEqual(movement.dest_iso3, "EGY")
        self.assertEqual(movement.origin_match_method, "unmatched")
        self.assertEqual(movement.dest_match_method, "unmatched")

    def test_a_corridor_with_no_number_is_still_a_corridor(self):
        movement = InsightMovement.objects.create(
            insight=an_insight(),
            origin_name_as_written="Sudan", origin_iso3="SDN",
            flow_type="cross_border")
        self.assertIsNone(movement.value)
        self.assertIsNone(movement.value_as_written)
        self.assertIsNone(movement.unit)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_models_children -v 2`
Expected: **FAIL** with `ImportError: cannot import name 'InsightFigure' from 'insights.models'`

- [ ] **Step 3: Add the vocabularies to `insights/models.py`**

Beneath the existing `DIMENSIONS` list near the top of the file:

```python
# The coding's part in the statement. 'subject' is what every row written before
# this column existed means, which is why it is the default and why the migration
# needs no backfill. 'driver' is what makes "why are they returning" a query
# rather than a reading exercise: return_movement as subject, armed_conflict as
# driver, on one quote. 'barrier' is what blocks access to a need.
CODING_ROLES = [("subject", "Subject"), ("driver", "Driver"), ("barrier", "Barrier")]

# A figure may be a share. A corridor may not: its value is a BigIntegerField and
# there is no honest way to put "65 percent" in one. A percentage about a moving
# population is a figure on the same quote, not a corridor.
FIGURE_UNITS = [("people", "People"), ("percent", "Percent"), ("households", "Households")]
MOVEMENT_UNITS = [("people", "People"), ("households", "Households")]

# The corridor's direction class - what decides how an arrow is drawn, and the
# same vocabulary data_track.MovementFlow.flow_type already uses. NOT the same
# thing as the movement_pattern coding, which is the richer taxonomy label;
# neither is derivable from the other.
FLOW_TYPES = [("cross_border", "Cross-border"), ("internal", "Internal"),
              ("return", "Return"), ("transit", "Transit")]

ROLE_VALUES = {value for value, _ in CODING_ROLES}
FIGURE_UNIT_VALUES = {value for value, _ in FIGURE_UNITS}
MOVEMENT_UNIT_VALUES = {value for value, _ in MOVEMENT_UNITS}
FLOW_TYPE_VALUES = {value for value, _ in FLOW_TYPES}
```

- [ ] **Step 4: Add `role` to `InsightCoding` and widen its constraint**

In `insights/models.py`, inside `class InsightCoding`, after the `tag_raw` field:

```python
    role = models.TextField(
        choices=CODING_ROLES, default="subject",
        help_text="What part this theme plays in the statement. 'driver' is the "
                  "cause; 'barrier' is what blocks access to a need.")
```

And in its `Meta.constraints`, replace the existing constraint with:

```python
        constraints = [
            # role joins the key because one statement can legitimately carry the
            # same tag twice in two parts: displacement as the thing happening,
            # and displacement as what drives a further need.
            models.UniqueConstraint(
                fields=["insight", "dimension", "tag", "role"], name="uniq_insight_coding"),
        ]
```

- [ ] **Step 5: Add the two child models**

At the end of `insights/models.py`, before `class DocumentsToInsights`:

```python
class InsightFigure(models.Model):
    """One number read out of one statement.

    WHY THIS IS NOT Insight.people_affected. That column is a BigIntegerField
    holding a headline people-count, and it stays. But an assessment report
    states most of what it knows as a share - the Egypt EVAR states 253 figures
    as percentages - and there is no honest way to put "65 percent" in a whole
    number of people.

    WHY figure_as_written EXISTS. verify.py checks the QUOTE against the page; it
    says nothing about a number typed beside it. A model could quote "About 65
    percent of refugees are highly or extremely vulnerable" perfectly and write
    value 56, and every gate would pass. So the span as printed is stored and
    checked against the quote, and value/unit are the parsed reading of it. This
    is place_name_as_written / admin_pcode one level down: what the document said,
    and what we made of it, kept side by side so the reading stays auditable.
    """

    insight = models.ForeignKey(Insight, on_delete=models.CASCADE, related_name="figures")
    figure_as_written = models.TextField(
        help_text="The span exactly as printed: '65 percent', '0.7 million'. Must "
                  "occur in the quote.")
    value = models.FloatField(help_text="The parsed reading. A float because a share is not an integer.")
    unit = models.TextField(choices=FIGURE_UNITS)
    measures = models.TextField(help_text="What it counts: 'highly or extremely vulnerable'")
    applies_to = models.TextField(
        null=True, blank=True,
        help_text="The subgroup, when the figure is disaggregated: 'non-Arabic "
                  "speaking households'. Null means the whole population the "
                  "statement is about.")

    class Meta:
        db_table = "insight_figures"
        ordering = ["id"]

    def __str__(self):
        return f"{self.figure_as_written} ({self.measures})"


class InsightMovement(models.Model):
    """One corridor read out of one statement - a complete arrow.

    WHY A ROW IS A CORRIDOR AND NOT A PAIR OF COLUMNS ON Insight. EVAR p.10 names
    eight origin countries in a single sentence, and the (document, page,
    quote_sha1) unique constraint means one quote cannot be split into eight rows
    to hold them. Eight child rows are eight unambiguous arrows on one quote.

    WHY EACH SIDE CARRIES ITS OWN iso3. places.resolve() needs a country per side,
    and on the corridor this table exists for - Sudan to Egypt - neither side
    equals the parent insight's iso3 in both positions. Inheriting it would invent
    a placement, and would do so precisely on cross-border movement.

    origin_lat/lon and dest_lat/lon are LABEL POSITIONS copied from
    AdminArea.center_lat/center_lon, not addresses - the same caveat the subject
    place carries, and the dashboard popup must repeat it.
    """

    insight = models.ForeignKey(Insight, on_delete=models.CASCADE, related_name="movements")

    origin_name_as_written = models.TextField(null=True, blank=True)
    origin_iso3 = models.CharField(max_length=3, null=True, blank=True)
    origin_pcode = models.TextField(null=True, blank=True)
    origin_admin_level = models.IntegerField(null=True, blank=True)
    origin_match_method = models.TextField(default="unmatched", help_text="pcode / name / unmatched")
    origin_lat = models.FloatField(null=True, blank=True)
    origin_lon = models.FloatField(null=True, blank=True)

    dest_name_as_written = models.TextField(null=True, blank=True)
    dest_iso3 = models.CharField(max_length=3, null=True, blank=True)
    dest_pcode = models.TextField(null=True, blank=True)
    dest_admin_level = models.IntegerField(null=True, blank=True)
    dest_match_method = models.TextField(default="unmatched", help_text="pcode / name / unmatched")
    dest_lat = models.FloatField(null=True, blank=True)
    dest_lon = models.FloatField(null=True, blank=True)

    flow_type = models.TextField(choices=FLOW_TYPES)
    value_as_written = models.TextField(
        null=True, blank=True, help_text="The span exactly as printed: '0.7 million'. "
                                         "Must occur in the quote when present.")
    value = models.BigIntegerField(null=True, blank=True)
    unit = models.TextField(choices=MOVEMENT_UNITS, null=True, blank=True)

    class Meta:
        db_table = "insight_movements"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["origin_iso3", "dest_iso3"], name="idx_movement_corridor"),
        ]

    def __str__(self):
        return f"{self.origin_name_as_written or '?'} → {self.dest_name_as_written or '?'}"
```

- [ ] **Step 6: Add the two drop counters to `ExtractionJob`**

In `class ExtractionJob`, after `insights_skipped_reviewed`:

```python
    # A bad vocabulary word costs its own figure or corridor, not the document
    # (spec 6.3) - but a drop must never be silent, so it is counted here and
    # named in `log`. These are deliberately NOT folded into
    # insights_rejected_unverifiable: that number means "whole insights that
    # failed the quote gate" and a reviewer already watches it, so it must not
    # quietly change definition.
    figures_rejected = models.IntegerField(default=0)
    movements_rejected = models.IntegerField(default=0)
```

- [ ] **Step 7: Generate the migration**

Run:
```bash
docker compose exec web python manage.py makemigrations insights --name comprehensive_extraction
```
Expected: creates `insights/migrations/0005_comprehensive_extraction.py`.

- [ ] **Step 8: Read the migration before applying it**

Run: `docker compose exec web cat insights/migrations/0005_comprehensive_extraction.py`

Check all four, and do not continue until each holds:
1. It **creates** `InsightFigure` and `InsightMovement`.
2. It **adds** `role` with `default="subject"` — and contains **no** `RunPython` backfill. The default does the work.
3. It removes and re-adds the constraint named `uniq_insight_coding` (Django emits `RemoveConstraint` then `AddConstraint`).
4. It touches **no** field on `Insight`. If it does, spec §4.5 has been broken — stop and fix the model.

- [ ] **Step 9: Apply it**

Run: `docker compose exec web python manage.py migrate insights`
Expected: `Applying insights.0005_comprehensive_extraction... OK`

- [ ] **Step 10: Run the new tests to verify they pass**

Run: `docker compose exec web python manage.py test insights.tests.test_models_children -v 2`
Expected: **PASS**, 7 tests.

- [ ] **Step 11: Run the tripwire and the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**, including all 3 of Task 1's tests. A failure in `test_backwards_compat` here means `role`'s default did not apply — go back to Step 4.

- [ ] **Step 12: Commit**

```bash
git add insights/models.py insights/migrations/0005_comprehensive_extraction.py insights/tests/test_models_children.py
git commit -m "feat: add InsightFigure, InsightMovement and InsightCoding.role

Three additions that hang off Insight without adding a column to it, so
every published row, the API and the map layer are untouched.

role makes cause a link rather than prose: return_movement as subject
and armed_conflict as driver, on one quote, is 'why are they returning'
as a query. The coding constraint widens to admit the same tag in two
roles.

A figure keeps the span as printed alongside the parsed value, because
verify.py checks the quote and not a number typed beside it.

A movement row is one complete corridor, because EVAR p.10 names eight
origins in a sentence and one quote cannot be split into eight rows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The contract

Spec §6.1–§6.4, §4.2. The payload half of the widening: parse the new blocks, check each number's span against its quote, and drop a bad row without losing the document.

**Files:**
- Modify: `insights/contract.py`
- Create: `insights/tests/fixtures/payload_comprehensive.json`
- Modify: `insights/tests/test_contract.py` (append two test classes)

**Interfaces:**
- Consumes: `insights.models.ROLE_VALUES`, `FIGURE_UNIT_VALUES`, `MOVEMENT_UNIT_VALUES`, `FLOW_TYPE_VALUES` (Task 2); `insights.verify.normalise` (existing, pure, no DB).
- Produces: `parse(payload)` keeps its signature — a list of row dicts — and each row gains three keys:
  - `row["figures"]` — list of `{figure_as_written, value, unit, measures, applies_to}`
  - `row["movements"]` — list of `{origin_name_as_written, origin_iso3, dest_name_as_written, dest_iso3, flow_type, value_as_written, value, unit}`
  - `row["drops"]` — list of human-readable strings, one per dropped figure or corridor, for `ExtractionJob.log`
  - `row["codings"][n]["role"]`

  Keeping the signature matters: `loader.load` and every existing contract test call `parse` positionally.

- [ ] **Step 1: Write the failing contract tests**

Append to `insights/tests/test_contract.py`:

```python
class RoleTests(SimpleTestCase):
    def test_a_coding_with_no_role_is_a_subject(self):
        """Every payload written before roles existed means 'subject'."""
        codings = parse(load("payload_ok.json"))[0]["codings"]
        self.assertTrue(all(c["role"] == "subject" for c in codings))

    def test_a_stated_role_is_kept(self):
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"][0]["role"] = "driver"
        codings = parse(payload)[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding",
                       "tag_raw": None, "role": "driver"}, codings)

    def test_an_unknown_role_degrades_to_subject(self):
        """A role is an interpretation. A wrong one costs a query, not a fact."""
        payload = load("payload_ok.json")
        payload["insights"][0]["codings"][0]["role"] = "consequence"
        codings = parse(payload)[0]["codings"]
        self.assertIn({"dimension": "hazard", "tag": "flooding",
                       "tag_raw": None, "role": "subject"}, codings)


class FigureContractTests(SimpleTestCase):
    def test_figures_are_parsed(self):
        row = parse(load("payload_comprehensive.json"))[0]
        self.assertEqual(len(row["figures"]), 2)
        first = row["figures"][0]
        self.assertEqual(first["figure_as_written"], "0.7 million")
        self.assertEqual(first["value"], 700000.0)
        self.assertEqual(first["unit"], "people")

    def test_a_subgroup_is_kept(self):
        figures = parse(load("payload_comprehensive.json"))[0]["figures"]
        self.assertEqual(figures[1]["applies_to"], "Sudanese refugees")

    def test_a_figure_whose_span_is_not_in_the_quote_is_dropped(self):
        """verify.py checks the quote; this is what checks the number."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"][0]["figure_as_written"] = "1.4 million"
        row = parse(payload)[0]
        self.assertEqual(len(row["figures"]), 1)
        self.assertEqual(len(row["drops"]), 1)
        self.assertIn("1.4 million", row["drops"][0])

    def test_an_unknown_unit_drops_the_figure_not_the_payload(self):
        """EVAR states currency amounts too. One EGP must not zero a 43-page run."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"][0]["unit"] = "EGP"
        row = parse(payload)[0]
        self.assertEqual(len(row["figures"]), 1)
        self.assertEqual(len(row["drops"]), 1)
        self.assertEqual(row["quote"][:20], "Since the escalation"[:20])

    def test_a_figure_that_is_not_an_object_is_a_payload_error(self):
        """A broken shape is a broken producer, not a wrong reading."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"] = ["65 percent"]
        with self.assertRaises(ContractError):
            parse(payload)

    def test_figures_not_a_list_is_a_payload_error(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["figures"] = {"value": 1}
        with self.assertRaises(ContractError):
            parse(payload)


class MovementContractTests(SimpleTestCase):
    def test_a_corridor_is_parsed_with_both_ends(self):
        movement = parse(load("payload_comprehensive.json"))[0]["movements"][0]
        self.assertEqual(movement["origin_name_as_written"], "Sudan")
        self.assertEqual(movement["origin_iso3"], "SDN")
        self.assertEqual(movement["dest_name_as_written"], "Egypt")
        self.assertEqual(movement["dest_iso3"], "EGY")
        self.assertEqual(movement["flow_type"], "cross_border")
        self.assertEqual(movement["value"], 700000)

    def test_a_corridor_with_one_end_is_allowed(self):
        """'arrivals from Sudan' with no stated destination is a real finding."""
        payload = load("payload_comprehensive.json")
        del payload["insights"][0]["movements"][0]["dest_name_as_written"]
        del payload["insights"][0]["movements"][0]["dest_iso3"]
        row = parse(payload)
        self.assertEqual(len(row[0]["movements"]), 1)
        self.assertIsNone(row[0]["movements"][0]["dest_name_as_written"])
        self.assertEqual(row[0]["drops"], [])

    def test_a_corridor_with_neither_end_is_dropped(self):
        payload = load("payload_comprehensive.json")
        movement = payload["insights"][0]["movements"][0]
        movement.pop("origin_name_as_written")
        movement.pop("dest_name_as_written")
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_an_unknown_flow_type_drops_the_corridor(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["flow_type"] = "circular"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_corridor_may_not_be_measured_as_a_share(self):
        """value is a BigIntegerField. 'percent' has no honest reading in it."""
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["unit"] = "percent"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_corridor_number_must_also_appear_in_the_quote(self):
        payload = load("payload_comprehensive.json")
        payload["insights"][0]["movements"][0]["value_as_written"] = "2.3 million"
        row = parse(payload)[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(len(row["drops"]), 1)

    def test_a_payload_with_no_movements_block_is_fine(self):
        row = parse(load("payload_ok.json"))[0]
        self.assertEqual(row["movements"], [])
        self.assertEqual(row["figures"], [])
        self.assertEqual(row["drops"], [])
```

- [ ] **Step 2: Create the comprehensive fixture**

Create `insights/tests/fixtures/payload_comprehensive.json`. The quote is real EVAR p.6 text, and every span in `figure_as_written` / `value_as_written` occurs inside it — which is what the span tests turn on:

```json
{
  "source": {"rel_path": "insights/evar.pdf", "sha1": "def", "report_date": "2026-03-01"},
  "producer": {"agent": "claude-code", "model": "claude-opus-5"},
  "insights": [
    {
      "quote": "Since the escalation of conflict in Sudan in April 2023, 0.7 million Sudanese refugees have been registered in Egypt - over a tenfold increase compared with pre-crisis levels.",
      "quote_language": "en",
      "page": 6,
      "voice_type": "secondary_analysis",
      "place_name_as_written": "Egypt",
      "iso3": "EGY",
      "codings": [
        {"dimension": "movement_pattern", "tag": "cross_border_arrival", "role": "subject"},
        {"dimension": "hazard", "tag": "armed_conflict", "role": "driver"}
      ],
      "figures": [
        {
          "figure_as_written": "0.7 million",
          "value": 700000,
          "unit": "people",
          "measures": "Sudanese refugees registered in Egypt"
        },
        {
          "figure_as_written": "over a tenfold increase",
          "value": 10,
          "unit": "percent",
          "measures": "increase compared with pre-crisis levels",
          "applies_to": "Sudanese refugees"
        }
      ],
      "movements": [
        {
          "origin_name_as_written": "Sudan",
          "origin_iso3": "SDN",
          "dest_name_as_written": "Egypt",
          "dest_iso3": "EGY",
          "flow_type": "cross_border",
          "value_as_written": "0.7 million",
          "value": 700000,
          "unit": "people"
        }
      ],
      "people_affected": 700000,
      "severity": 4,
      "confidence": "high"
    }
  ]
}
```

- [ ] **Step 3: Run to verify the tests fail**

Run: `docker compose exec web python manage.py test insights.tests.test_contract -v 2`
Expected: **FAIL** — `KeyError: 'figures'` and `KeyError: 'role'`.

- [ ] **Step 4: Widen `insights/contract.py`**

Replace the module docstring's second paragraph and add the imports at the top:

```python
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES, ROLE_VALUES,
)
from insights.taxonomy import normalise_coding
from insights.verify import normalise
```

Then add these two helpers above `parse`:

```python
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
        raise ContractError(f"insights[{index}]: 'figures' must be a list, got {type(raw).__name__}")

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
        raise ContractError(f"insights[{index}]: 'movements' must be a list, got {type(raw).__name__}")

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
```

- [ ] **Step 5: Wire the helpers into `parse`**

In `parse`, inside the coding loop, replace the `normalised = normalise_coding(...)` line and the append that follows with:

```python
            try:
                # An unknown dimension raises; an unknown tag degrades. See taxonomy.py.
                normalised = normalise_coding(coding.get("dimension"), coding.get("tag"))
            except ValueError as exc:
                raise ContractError(f"insights[{index}]: {exc}") from exc
            # A role is an interpretation, so an unknown one degrades to 'subject'
            # the same way an unknown tag degrades to 'other'.
            role = coding.get("role")
            normalised["role"] = role if role in ROLE_VALUES else "subject"
            if normalised not in codings:
                codings.append(normalised)
```

Then, still in `parse` and just before `rows.append({...}`:

```python
        figures, figure_drops = _figures(item, index, quote)
        movements, movement_drops = _movements(item, index, quote)
```

And add three keys to the appended dict:

```python
            "figures": figures,
            "movements": movements,
            "drops": figure_drops + movement_drops,
```

- [ ] **Step 6: Run the contract tests**

Run: `docker compose exec web python manage.py test insights.tests.test_contract -v 2`
Expected: **PASS**, all tests including the pre-existing ones.

- [ ] **Step 7: Run the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**. `test_backwards_compat` must still be green.

- [ ] **Step 8: Commit**

```bash
git add insights/contract.py insights/tests/test_contract.py insights/tests/fixtures/payload_comprehensive.json
git commit -m "feat: parse figures, movements and coding roles

Every number carries the span as printed and it must occur in the quote,
folded through verify.normalise so a PDF line wrap does not cause a
false drop while a changed digit does. That is what stops a perfectly
quoted sentence carrying an invented value.

A wrong vocabulary word or an unquoted span drops its own row and is
reported in row['drops']; ContractError stays reserved for a malformed
shape. EVAR states currency amounts beside its percentages and one of
them must not zero a 43-page run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The loader

Spec §8. Write the children, resolve both corridor ends independently, replace children wholesale on a pending re-load, and surface every drop.

**Files:**
- Modify: `insights/loader.py`
- Modify: `insights/tests/test_loader.py` (append two test classes)

**Interfaces:**
- Consumes: `row["figures"]`, `row["movements"]`, `row["drops"]`, `row["codings"][n]["role"]` from Task 3; `insights.places.resolve(iso3, place_name)` → `{admin_pcode, admin_level, match_method, lat, lon}` (existing, unchanged).
- Produces: `LoadReport` gains `figures_rejected: int`, `movements_rejected: int`. `load()` keeps its signature.

- [ ] **Step 1: Write the failing loader tests**

Append to `insights/tests/test_loader.py`. Note the new imports needed at the top of that file: `from insights.models import InsightFigure, InsightMovement` (add to the existing `insights.models` import) and `from boundaries.models import AdminArea, BoundarySource`.

```python
EVAR_QUOTE = ("Since the escalation of conflict in Sudan in April 2023, 0.7 million "
              "Sudanese refugees have been registered in Egypt - over a tenfold "
              "increase compared with pre-crisis levels.")


class ChildRowTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="evar.pdf", rel_path="insights/evar.pdf", report_date="2026-03-01")
        DocumentText.objects.create(document=self.doc, page=6, text=EVAR_QUOTE)
        self.payload = json.loads(
            (FIXTURES / "payload_comprehensive.json").read_text(encoding="utf-8"))

    def test_the_figures_are_written(self):
        load(self.payload, self.doc)
        figures = Insight.objects.get().figures.all()
        self.assertEqual(figures.count(), 2)
        self.assertEqual(figures[0].figure_as_written, "0.7 million")
        self.assertEqual(figures[0].value, 700000.0)

    def test_the_corridor_is_written(self):
        load(self.payload, self.doc)
        movement = Insight.objects.get().movements.get()
        self.assertEqual(movement.origin_name_as_written, "Sudan")
        self.assertEqual(movement.dest_name_as_written, "Egypt")
        self.assertEqual(movement.flow_type, "cross_border")

    def test_the_coding_roles_are_written(self):
        load(self.payload, self.doc)
        roles = dict(Insight.objects.get().codings.values_list("tag", "role"))
        self.assertEqual(roles["cross_border_arrival"], "subject")
        self.assertEqual(roles["armed_conflict"], "driver")

    def test_a_dropped_figure_is_counted_and_the_insight_survives(self):
        self.payload["insights"][0]["figures"][0]["unit"] = "EGP"
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(report.figures_rejected, 1)
        self.assertEqual(Insight.objects.get().figures.count(), 1)

    def test_a_dropped_corridor_is_counted_and_the_insight_survives(self):
        self.payload["insights"][0]["movements"][0]["flow_type"] = "circular"
        report = load(self.payload, self.doc)
        self.assertEqual(report.written, 1)
        self.assertEqual(report.movements_rejected, 1)
        self.assertEqual(Insight.objects.get().movements.count(), 0)

    def test_reloading_a_pending_insight_replaces_its_children(self):
        """No natural key on either child, so a re-run would otherwise duplicate.

        loader.py already does exactly this for codings, and for the same reason:
        a re-run's reading supersedes its own earlier one.
        """
        load(self.payload, self.doc)
        load(self.payload, self.doc)
        insight = Insight.objects.get()
        self.assertEqual(insight.figures.count(), 2)
        self.assertEqual(insight.movements.count(), 1)

    def test_a_reviewed_insight_keeps_its_corrected_children(self):
        """Gate 4 covers the children too - a reviewer's correction is not rubbish."""
        load(self.payload, self.doc)
        insight = Insight.objects.get()
        insight.figures.update(value=999.0)
        insight.status = "published"
        insight.save()

        report = load(self.payload, self.doc)
        self.assertEqual(report.skipped_reviewed, 1)
        self.assertEqual(insight.figures.first().value, 999.0)

    def test_the_drops_are_named_in_the_job_log(self):
        """A silent drop is lost testimony. Counted is not enough - say which."""
        self.payload["insights"][0]["figures"][0]["unit"] = "EGP"
        job = ExtractionJob.objects.create(producer="anthropic")
        load(self.payload, self.doc, job=job)
        job.refresh_from_db()
        self.assertEqual(job.figures_rejected, 1)
        self.assertIn("EGP", job.log)


class CorridorPlacementTests(TestCase):
    """Both ends resolve independently, and neither inherits the parent's country."""

    def setUp(self):
        self.doc = Document.objects.create(
            file_name="evar.pdf", rel_path="insights/evar.pdf", report_date="2026-03-01")
        DocumentText.objects.create(document=self.doc, page=6, text=EVAR_QUOTE)
        self.payload = json.loads(
            (FIXTURES / "payload_comprehensive.json").read_text(encoding="utf-8"))
        # AdminArea requires `source` and `country_name` - both NOT NULL. iso3 is
        # never null on purpose: the matcher refuses to place a sentence about one
        # country on a polygon in another. BoundarySource needs only `path`.
        source = BoundarySource.objects.create(path="tests/evar-fixture")
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN", country_name="Sudan",
            level=0, pcode="SD", name="Sudan", name_alt=[],
            center_lat=15.5, center_lon=32.5)
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="EGY", country_name="Egypt",
            level=0, pcode="EG", name="Egypt", name_alt=[],
            center_lat=26.8, center_lon=30.8)

    def test_each_end_resolves_against_its_own_country(self):
        load(self.payload, self.doc)
        movement = Insight.objects.get().movements.get()
        self.assertEqual(movement.origin_pcode, "SD")
        self.assertEqual(movement.origin_match_method, "name")
        self.assertEqual(movement.origin_lat, 15.5)
        self.assertEqual(movement.dest_pcode, "EG")
        self.assertEqual(movement.dest_lat, 26.8)

    def test_a_side_with_no_iso3_is_unmatched_and_never_inherits_the_parent(self):
        """Inheriting would invent a placement, and would do it on the very case
        this table exists for: the parent here is EGY, the origin is Sudan."""
        del self.payload["insights"][0]["movements"][0]["origin_iso3"]
        load(self.payload, self.doc)
        movement = Insight.objects.get().movements.get()
        self.assertEqual(movement.origin_name_as_written, "Sudan")
        self.assertIsNone(movement.origin_iso3)
        self.assertIsNone(movement.origin_pcode)
        self.assertEqual(movement.origin_match_method, "unmatched")

    def test_an_unresolvable_end_keeps_its_written_name(self):
        self.payload["insights"][0]["movements"][0]["origin_name_as_written"] = "Sudan"
        self.payload["insights"][0]["movements"][0]["origin_iso3"] = "SDN"
        AdminArea.objects.filter(iso3="SDN").delete()
        load(self.payload, self.doc)
        movement = Insight.objects.get().movements.get()
        self.assertEqual(movement.origin_name_as_written, "Sudan")
        self.assertEqual(movement.origin_match_method, "unmatched")
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec web python manage.py test insights.tests.test_loader -v 2`
Expected: **FAIL** — `AttributeError: 'LoadReport' object has no attribute 'figures_rejected'`.

- [ ] **Step 3: Extend `LoadReport` and add the placement helper**

In `insights/loader.py`, extend the dataclass:

```python
@dataclass
class LoadReport:
    written: int = 0
    rejected_unverifiable: int = 0
    skipped_reviewed: int = 0
    # Figures and corridors dropped for a wrong vocabulary word or an unquoted
    # span. Kept apart from rejected_unverifiable, which means "whole insights
    # that failed the quote gate" and which a reviewer already watches.
    figures_rejected: int = 0
    movements_rejected: int = 0
```

Add the import and the helper after `_coerce_stated_on`:

```python
from insights.models import Insight, InsightCoding, InsightFigure, InsightMovement


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
```

- [ ] **Step 4: Write the children in the row loop**

In `load()`, replace the existing codings block — the `insight.codings.all().delete()` line through `report.written += 1` — with:

```python
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

        for drop in row["drops"]:
            if drop.startswith("corridor"):
                report.movements_rejected += 1
            else:
                report.figures_rejected += 1
            drop_messages.append(f"{document.file_name if document else 'manual'}: {drop}")

        report.written += 1
```

- [ ] **Step 5: Collect the drop messages and record them on the job**

Immediately before `for row in rows:` add:

```python
    # A drop must never be silent - a figure nobody is told about is a figure a
    # reviewer cannot ask for. Counted in the report, named in the job log.
    drop_messages = []
```

Then replace the job-update block at the end of `load()` with:

```python
    if job is not None:
        job.insights_proposed += len(rows)
        job.insights_rejected_unverifiable += report.rejected_unverifiable
        job.insights_skipped_reviewed += report.skipped_reviewed
        job.figures_rejected += report.figures_rejected
        job.movements_rejected += report.movements_rejected
        if drop_messages:
            job.log = "\n".join(filter(None, [job.log, *drop_messages]))
        job.save(update_fields=[
            "insights_proposed", "insights_rejected_unverifiable",
            "insights_skipped_reviewed", "figures_rejected", "movements_rejected",
            "log",
        ])
```

- [ ] **Step 6: Run the loader tests**

Run: `docker compose exec web python manage.py test insights.tests.test_loader -v 2`
Expected: **PASS**, including the pre-existing gate tests.

- [ ] **Step 7: Run the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**.

- [ ] **Step 8: Commit**

```bash
git add insights/loader.py insights/tests/test_loader.py
git commit -m "feat: load figures and corridors, resolving each end on its own

Gate 3 runs twice more per corridor, once per side with that side's own
iso3 - places.py is unchanged. A side with no iso3 is recorded unmatched
rather than given the parent's country, because inheriting would invent
a placement precisely on the cross-border case the table exists for.

A pending parent's children are replaced wholesale, as codings already
are: neither child table has a natural key and a re-run would otherwise
duplicate every row. Gate 4 still skips a reviewed insight whole, so a
corrected figure survives a re-extraction.

Every drop is counted on the report and named in the job log.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The prompt and the schema that gates it

Spec §7, §6 (the third half). **This is the task that makes the feature actually happen.** `anthropic_api.SCHEMA` sets `"additionalProperties": False`, so until it is widened the adapter cannot emit the new fields at all — they are forbidden by the response format, not merely ignored, and a run would look healthy and return nothing new.

**Files:**
- Modify: `insights/prompts/extract_insights.md`
- Modify: `insights/extractors/anthropic_api.py:51-88` (the `SCHEMA` constant)
- Modify: `insights/contract.py` (docstring only — name the third half)
- Create: `insights/tests/test_schema_matches_contract.py`

**Interfaces:**
- Consumes: the vocabularies from Task 2, the payload keys from Task 3.
- Produces: nothing importable. The deliverable is that the Anthropic adapter can emit what the contract accepts.

- [ ] **Step 1: Write the failing test that ties the schema to the contract**

Create `insights/tests/test_schema_matches_contract.py`:

```python
"""The JSON schema is the third half of the contract, and it is load-bearing.

anthropic_api.SCHEMA is passed as the request's json_schema output format with
"additionalProperties": False on both the insight object and the coding object.
A field the contract accepts but the schema omits is not ignored - it is
FORBIDDEN, and the adapter simply never emits it. The failure is silent: the run
looks healthy and returns nothing new.

So the schema is checked against the vocabularies rather than trusted to be kept
in step by hand.
"""
from django.test import SimpleTestCase

from insights.extractors.anthropic_api import SCHEMA
from insights.models import (
    FIGURE_UNIT_VALUES, FLOW_TYPE_VALUES, MOVEMENT_UNIT_VALUES, ROLE_VALUES,
)

INSIGHT = SCHEMA["properties"]["insights"]["items"]["properties"]


class SchemaTests(SimpleTestCase):
    def test_the_insight_object_admits_figures_and_movements(self):
        self.assertIn("figures", INSIGHT)
        self.assertIn("movements", INSIGHT)

    def test_a_coding_admits_a_role_and_its_enum_matches_the_model(self):
        coding = INSIGHT["codings"]["items"]["properties"]
        self.assertIn("role", coding)
        self.assertEqual(set(coding["role"]["enum"]), ROLE_VALUES)

    def test_the_figure_unit_enum_matches_the_model(self):
        figure = INSIGHT["figures"]["items"]["properties"]
        self.assertEqual(set(figure["unit"]["enum"]), FIGURE_UNIT_VALUES)

    def test_a_figure_must_carry_its_span(self):
        """figure_as_written is what makes the number checkable. Not optional."""
        figure = INSIGHT["figures"]["items"]
        self.assertIn("figure_as_written", figure["required"])

    def test_the_movement_enums_match_the_model(self):
        movement = INSIGHT["movements"]["items"]["properties"]
        self.assertEqual(set(movement["flow_type"]["enum"]), FLOW_TYPE_VALUES)
        self.assertEqual(set(movement["unit"]["enum"]), MOVEMENT_UNIT_VALUES)

    def test_a_corridor_is_never_measured_as_a_share(self):
        movement = INSIGHT["movements"]["items"]["properties"]
        self.assertNotIn("percent", movement["unit"]["enum"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec web python manage.py test insights.tests.test_schema_matches_contract -v 2`
Expected: **FAIL** — `AssertionError: 'figures' not found in {...}`.

- [ ] **Step 3: Widen `SCHEMA` in `insights/extractors/anthropic_api.py`**

Add `"role"` to the coding object's properties (leave its `required` as `["dimension", "tag"]`, so a role stays optional):

```python
                    "codings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "tag": {"type": "string"},
                                "role": {"type": "string",
                                         "enum": ["subject", "driver", "barrier"]},
                            },
                            "required": ["dimension", "tag"],
                            "additionalProperties": False,
                        },
                    },
```

And add these two properties to the insight object, beside `codings`:

```python
                    "figures": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "figure_as_written": {"type": "string"},
                                "value": {"type": "number"},
                                "unit": {"type": "string",
                                         "enum": ["people", "percent", "households"]},
                                "measures": {"type": "string"},
                                "applies_to": {"type": ["string", "null"]},
                            },
                            "required": ["figure_as_written", "value", "unit", "measures"],
                            "additionalProperties": False,
                        },
                    },
                    "movements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "origin_name_as_written": {"type": ["string", "null"]},
                                "origin_iso3": {"type": ["string", "null"]},
                                "dest_name_as_written": {"type": ["string", "null"]},
                                "dest_iso3": {"type": ["string", "null"]},
                                "flow_type": {
                                    "type": "string",
                                    "enum": ["cross_border", "internal", "return", "transit"]},
                                "value_as_written": {"type": ["string", "null"]},
                                "value": {"type": ["integer", "null"]},
                                # people or households only. A corridor's value is a
                                # BigIntegerField and a share has no honest reading in it.
                                "unit": {"type": ["string", "null"],
                                         "enum": ["people", "households", None]},
                            },
                            "required": ["flow_type"],
                            "additionalProperties": False,
                        },
                    },
```

Leave the insight object's own `required` list unchanged at `["quote", "page", "voice_type", "iso3", "codings"]` — `figures` and `movements` must stay optional (Global Constraints).

Add above the constant:

```python
# KEEP IN STEP WITH insights/contract.py AND insights/prompts/extract_insights.md.
# "additionalProperties": False means a field the contract accepts but this schema
# omits is FORBIDDEN, not ignored - the model cannot emit it and the run looks
# healthy while returning nothing new. test_schema_matches_contract.py checks the
# enums against insights/models.py so this cannot drift silently.
```

- [ ] **Step 4: Run the schema test**

Run: `docker compose exec web python manage.py test insights.tests.test_schema_matches_contract -v 2`
Expected: **PASS**, 6 tests.

- [ ] **Step 5: Name the third half in `insights/contract.py`'s docstring**

Replace the second paragraph of the module docstring:

```python
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
```

- [ ] **Step 6: Widen the prompt**

In `insights/prompts/extract_insights.md`, replace the section "## What to extract" heading's closing paragraph (the "Most sitreps contain no community voice at all…" block) with the block below, keeping the two `community` / `secondary_analysis` bullets above it untouched:

```markdown
**Label the voice honestly, whatever the topic.** Widening what you read for does
not blur these two. A focus-group finding is `community`; a survey statistic in
the analyst's own prose is `secondary_analysis`, even when both sit in the same
paragraph about the same people.

## Read the document for all of this

Read for each of the following. **Coverage is opportunistic: a topic the document
does not cover yields nothing, and that is still the correct answer.** Do not pad
a thin document to fill these headings — a weekly sitrep that holds two statements
should return two statements.

| What to look for | Where it goes |
|---|---|
| movement numbers | a `movements[]` entry with `value` and `unit` |
| where people came from, where they are going | `movements[]`, both ends named |
| why they moved, why they are returning | the movement tag as `subject`, the cause as `driver` |
| hazards they are exposed to | `hazard` codings |
| who is vulnerable, and why | the group as `subject`, the cause as `driver` |
| coping mechanisms adopted | `coping` codings |
| needs | `need` codings, and `barrier` for what blocks access |
| any other stated quantity | a `figures[]` entry |

### The role on a coding

Each coding carries a `role`, and this is how a reason is recorded:

- `subject` — what the statement is about. The default; omit it if unsure.
- `driver` — the cause. A quote coded `movement_pattern:return_movement` as
  subject and `hazard:armed_conflict` as driver says *why* they are returning.
- `barrier` — what blocks access. `need:health` as subject with
  `vulnerability:statelessness_documentation` as barrier says they cannot reach
  the clinic without papers.
```

Then, in "## The rules that matter", append rules 7 and 8 after the existing rule 6:

```markdown
7. **A figure is only ever an attribute of a quoted sentence, and you must copy
   its span.** Give `figure_as_written` exactly as printed — `"65 percent"`,
   `"0.7 million"`, `"two-fifths of refugee households (44 percent)"` — alongside
   the parsed `value` and `unit`. The span is checked against your quote and the
   figure is discarded if it is not there. If the number is not printed in the
   passage you are quoting, there is no figure. `unit` is one of `people`,
   `percent`, `households`; a corridor's `unit` is `people` or `households` only,
   never a share.
8. **Name only the ends the text names.** Do not infer an origin or a destination
   from surrounding context. A corridor with one end stated and the other genuinely
   absent is recorded with one end; a corridor with neither is not a corridor.
   Give each end its own `iso3` — on a cross-border movement the two differ, and
   neither is assumed from the document's country.
```

Finally, in "## Output", replace the example insight's body with one that shows the new blocks:

```json
    {
      "quote": "…verbatim…",
      "quote_language": "en",
      "page": 7,
      "voice_type": "community",
      "place_name_as_written": "Afar",
      "iso3": "ETH",
      "codings": [
        {"dimension": "movement_pattern", "tag": "cross_border_arrival", "role": "subject"},
        {"dimension": "hazard", "tag": "armed_conflict", "role": "driver"},
        {"dimension": "need", "tag": "health", "role": "subject"}
      ],
      "figures": [
        {"figure_as_written": "65 percent", "value": 65, "unit": "percent",
         "measures": "highly or extremely vulnerable",
         "applies_to": "female-headed households"}
      ],
      "movements": [
        {"origin_name_as_written": "Sudan", "origin_iso3": "SDN",
         "dest_name_as_written": "Egypt", "dest_iso3": "EGY",
         "flow_type": "cross_border",
         "value_as_written": "0.7 million", "value": 700000, "unit": "people"}
      ],
      "people_affected": null,
      "severity": 4,
      "confidence": "high"
    }
```

- [ ] **Step 7: Run the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**. The prompt is loaded by `prompt_text()` in `insights/extractors/__init__.py`; a syntax-free markdown edit cannot fail a test, but `test_extractors` reads it and must stay green.

- [ ] **Step 8: Commit**

```bash
git add insights/prompts/extract_insights.md insights/extractors/anthropic_api.py insights/contract.py insights/tests/test_schema_matches_contract.py
git commit -m "feat: widen the prompt, and the schema that gates it

SCHEMA sets additionalProperties false, so until now the Anthropic
adapter could not emit figures, movements or role at all - forbidden by
the response format rather than ignored, which would have made a widened
prompt look healthy while returning nothing new. A test now checks its
enums against insights/models.py so it cannot drift again, and
contract.py's docstring names it as the third half.

The prompt keeps its anti-padding stance in a new form: coverage is
opportunistic, and a topic the document does not cover yields nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The API

Spec §10.5. Serve what was stored, and let a reader ask the causal question.

**Files:**
- Modify: `insights/views.py`
- Modify: `insights/tests/test_api.py` (append one test class)

**Interfaces:**
- Consumes: the models from Task 2.
- Produces: each result object gains `figures`, `movements`, and a `role` on each coding. New query parameters `?role=` and `?flow_type=`.

- [ ] **Step 1: Write the failing API tests**

Append to `insights/tests/test_api.py`:

```python
class ComprehensiveFieldTests(TestCase):
    """The endpoint is mounted at /api/insights/ - reuse the module's `make` helper,
    which already fills quote_sha1 and the other defaults."""

    def setUp(self):
        self.insight = make(
            "Since the escalation of conflict in Sudan in April 2023, 0.7 million "
            "Sudanese refugees have been registered in Egypt.",
            iso3="EGY", stated_on="2026-03-01", voice_type="secondary_analysis")
        InsightCoding.objects.create(
            insight=self.insight, dimension="movement_pattern",
            tag="cross_border_arrival", role="subject")
        InsightCoding.objects.create(
            insight=self.insight, dimension="hazard", tag="armed_conflict", role="driver")
        InsightFigure.objects.create(
            insight=self.insight, figure_as_written="0.7 million", value=700000.0,
            unit="people", measures="Sudanese refugees registered in Egypt")
        InsightMovement.objects.create(
            insight=self.insight, origin_name_as_written="Sudan", origin_iso3="SDN",
            dest_name_as_written="Egypt", dest_iso3="EGY", flow_type="cross_border",
            value_as_written="0.7 million", value=700000, unit="people")

    def get(self, query=""):
        return self.client.get(f"/api/insights/{query}").json()

    def only_row(self):
        rows = [r for r in self.get()["results"] if r["iso3"] == "EGY"]
        return rows[0]

    def test_the_figures_are_served(self):
        figure = self.only_row()["figures"][0]
        self.assertEqual(figure["value"], 700000.0)
        self.assertEqual(figure["unit"], "people")
        self.assertEqual(figure["as_written"], "0.7 million")

    def test_the_corridor_is_served_with_both_ends(self):
        movement = self.only_row()["movements"][0]
        self.assertEqual(movement["origin"]["name"], "Sudan")
        self.assertEqual(movement["origin"]["iso3"], "SDN")
        self.assertEqual(movement["destination"]["iso3"], "EGY")
        self.assertEqual(movement["flow_type"], "cross_border")

    def test_each_coding_carries_its_role(self):
        roles = {c["tag"]: c["role"] for c in self.only_row()["codings"]}
        self.assertEqual(roles["armed_conflict"], "driver")

    def test_filtering_by_role_and_tag_finds_the_driver(self):
        """'What drives cross-border arrival' - the question the role column adds."""
        self.assertEqual(
            self.get("?dimension=hazard&tag=armed_conflict&role=driver")["count"], 1)

    def test_a_role_that_matches_no_coding_returns_nothing(self):
        self.assertEqual(
            self.get("?dimension=hazard&tag=armed_conflict&role=barrier")["count"], 0)

    def test_filtering_by_flow_type(self):
        self.assertEqual(self.get("?flow_type=cross_border")["count"], 1)
        self.assertEqual(self.get("?flow_type=return")["count"], 0)

    def test_a_pending_insight_is_still_never_served(self):
        self.insight.status = "pending"
        self.insight.save()
        self.assertEqual(self.get("?iso3=EGY")["count"], 0)
```

Add `InsightFigure, InsightMovement` to that file's existing `from insights.models import Insight, InsightCoding` line.

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec web python manage.py test insights.tests.test_api -v 2`
Expected: **FAIL** — `KeyError: 'figures'`.

- [ ] **Step 3: Extend the query and the serialisation in `insights/views.py`**

Change the base queryset's prefetch:

```python
    rows = (Insight.objects.filter(status="published")
            .select_related("document")
            .prefetch_related("codings", "figures", "movements"))
```

Add the `role` handling. Replace the `dimension`/`tag` block with:

```python
    dimension = request.GET.get("dimension")
    tag = request.GET.get("tag")
    role = request.GET.get("role")
    # Every coding constraint goes into ONE .filter() call so a single coding row
    # must satisfy all of them. Chained .filter() calls on a to-many relation join
    # the table separately, so a row could match the dimension in one coding and
    # the tag in another - wrong, and wrong in a way that quietly over-reports.
    coding_filters = {}
    if dimension:
        coding_filters["codings__dimension"] = dimension
    if tag:
        coding_filters["codings__tag"] = tag
    if role:
        coding_filters["codings__role"] = role
    if coding_filters:
        rows = rows.filter(**coding_filters)

    if flow_type := request.GET.get("flow_type"):
        rows = rows.filter(movements__flow_type=flow_type)
```

Update the docstring's filter list:

```python
    """Published community insights. Filters: ?voice_type= &iso3= &dimension=
    &tag= &role= &flow_type= &admin_pcode= &from= &to= &q=
    """
```

In the result dict, replace the `codings` line and add the two new keys:

```python
            "codings": [{"dimension": c.dimension, "tag": c.tag, "role": c.role}
                        for c in row.codings.all()],
            "figures": [
                {
                    "as_written": f.figure_as_written,
                    "value": f.value,
                    "unit": f.unit,
                    "measures": f.measures,
                    "applies_to": f.applies_to,
                }
                for f in row.figures.all()
            ],
            "movements": [
                {
                    # lat/lon on each side are LABEL POSITIONS from
                    # AdminArea.center_*, not addresses. Anything drawing these
                    # must say so, as the subject-place popup already does.
                    "origin": {"name": m.origin_name_as_written, "iso3": m.origin_iso3,
                               "pcode": m.origin_pcode, "admin_level": m.origin_admin_level,
                               "match_method": m.origin_match_method,
                               "lat": m.origin_lat, "lon": m.origin_lon},
                    "destination": {"name": m.dest_name_as_written, "iso3": m.dest_iso3,
                                    "pcode": m.dest_pcode, "admin_level": m.dest_admin_level,
                                    "match_method": m.dest_match_method,
                                    "lat": m.dest_lat, "lon": m.dest_lon},
                    "flow_type": m.flow_type,
                    "value_as_written": m.value_as_written,
                    "value": m.value,
                    "unit": m.unit,
                }
                for m in row.movements.all()
            ],
```

- [ ] **Step 4: Run the API tests**

Run: `docker compose exec web python manage.py test insights.tests.test_api -v 2`
Expected: **PASS**, including the pre-existing published-only tests.

- [ ] **Step 5: Run the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**.

- [ ] **Step 6: Commit**

```bash
git add insights/views.py insights/tests/test_api.py
git commit -m "feat: serve figures, corridors and coding roles

?role= joins ?dimension= and ?tag= inside one .filter() call, so a
single coding row must satisfy all three - which is what makes 'what
drives cross-border arrival' a correct query rather than one that
matches the dimension in one coding and the tag in another.

Published-only is unchanged, and there is still no parameter that
returns a pending or rejected insight.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The review surface

Spec §9. Deliberately asymmetric: the wizard **shows** the new structures so a reviewer can judge the insight and publish or reject it whole; the admin **edits** them.

**Files:**
- Modify: `insights/admin.py:32-41`
- Modify: `insights/templates/insights/_review_row.html`
- Modify: `insights/wizard.py:233-234`
- Modify: `insights/tests/test_admin.py` and `insights/tests/test_wizard_review.py` (append)

**Interfaces:**
- Consumes: the models from Task 2. Produces no importable surface.

- [ ] **Step 1: Write the failing tests**

Append to `insights/tests/test_admin.py`:

```python
class ChildInlineTests(TestCase):
    def test_the_insight_admin_edits_figures_and_corridors(self):
        """Read-only in the wizard, corrected here. A wrong figure needs a home."""
        from django.contrib import admin as django_admin

        from insights.models import Insight, InsightFigure, InsightMovement

        inlines = [inline.model for inline in
                   django_admin.site._registry[Insight].inlines]
        self.assertIn(InsightFigure, inlines)
        self.assertIn(InsightMovement, inlines)

    def test_the_coding_inline_exposes_the_role(self):
        from django.contrib import admin as django_admin

        from insights.models import Insight, InsightCoding

        coding_inline = next(
            inline for inline in django_admin.site._registry[Insight].inlines
            if inline.model is InsightCoding)
        self.assertIn("role", coding_inline.fields)
```

Append to `insights/tests/test_wizard_review.py`:

```python
class ReviewRowShowsChildrenTests(TestCase):
    def test_a_figure_and_a_corridor_are_rendered_under_the_quote(self):
        from django.template.loader import render_to_string

        from insights.models import Insight, InsightFigure, InsightMovement

        insight = Insight.objects.create(
            quote="0.7 million Sudanese refugees have been registered in Egypt.",
            iso3="EGY", stated_on="2026-03-01")
        InsightFigure.objects.create(
            insight=insight, figure_as_written="0.7 million", value=700000.0,
            unit="people", measures="Sudanese refugees registered in Egypt")
        InsightMovement.objects.create(
            insight=insight, origin_name_as_written="Sudan", origin_iso3="SDN",
            dest_name_as_written="Egypt", dest_iso3="EGY", flow_type="cross_border")

        html = render_to_string("insights/_review_row.html", {"insight": insight})
        self.assertIn("0.7 million", html)
        self.assertIn("Sudan", html)
        self.assertIn("cross_border", html)
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec web python manage.py test insights.tests.test_admin insights.tests.test_wizard_review -v 2`
Expected: **FAIL** — `InsightFigure not found in inlines`.

- [ ] **Step 3: Add the admin inlines**

In `insights/admin.py`, import the two models by adding them to the existing `from insights.models import (...)` block, then replace the coding inline and add two more:

```python
class InsightCodingInline(admin.TabularInline):
    model = InsightCoding
    extra = 1
    fields = ("dimension", "tag", "role", "tag_raw")
    readonly_fields = ("tag_raw",)


class InsightFigureInline(admin.TabularInline):
    model = InsightFigure
    extra = 0
    fields = ("figure_as_written", "value", "unit", "measures", "applies_to")


class InsightMovementInline(admin.TabularInline):
    model = InsightMovement
    extra = 0
    fields = ("origin_name_as_written", "origin_iso3", "dest_name_as_written",
              "dest_iso3", "flow_type", "value_as_written", "value", "unit",
              "origin_match_method", "dest_match_method")
    # Resolved by the loader from the written name plus that side's iso3. Editing
    # a match method by hand would claim a placement nothing resolved.
    readonly_fields = ("origin_match_method", "dest_match_method")
```

And on `InsightAdmin`:

```python
    inlines = [InsightCodingInline, InsightFigureInline, InsightMovementInline]
```

- [ ] **Step 4: Show the children in the review row**

In `insights/templates/insights/_review_row.html`, insert this immediately after the closing `</small>` tag and before the closing `</td>`:

```html
    {% if insight.figures.all %}
      <small class="wiz-figures">
        {% for figure in insight.figures.all %}
          <b>{{ figure.figure_as_written }}</b> {{ figure.measures }}{% if figure.applies_to %} <i>({{ figure.applies_to }})</i>{% endif %}{% if not forloop.last %} · {% endif %}
        {% endfor %}
      </small>
    {% endif %}
    {% for movement in insight.movements.all %}
      <small class="wiz-movement">
        {{ movement.origin_name_as_written|default:"?" }}
        {% if movement.origin_pcode %}({{ movement.origin_match_method }}){% else %}(unplaced){% endif %}
        →
        {{ movement.dest_name_as_written|default:"?" }}
        {% if movement.dest_pcode %}({{ movement.dest_match_method }}){% else %}(unplaced){% endif %}
        · {{ movement.flow_type }}{% if movement.value %} · {{ movement.value_as_written }}{% endif %}
      </small>
    {% endfor %}
```

Each side shows its match method for the same reason the subject place does: "somewhere in Sudan" and "we do not know where" are different findings, and a reviewer deciding whether to publish needs to see which one this is.

- [ ] **Step 5: Prefetch the children in the wizard**

In `insights/wizard.py` at line 233-234, extend the prefetch so the review list does not issue two queries per row:

```python
            .select_related("document")
            .prefetch_related("codings", "figures", "movements")
```

- [ ] **Step 6: Run the tests**

Run: `docker compose exec web python manage.py test insights.tests.test_admin insights.tests.test_wizard_review -v 2`
Expected: **PASS**.

- [ ] **Step 7: Run the whole app**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**.

- [ ] **Step 8: Commit**

```bash
git add insights/admin.py insights/templates/insights/_review_row.html insights/wizard.py insights/tests/test_admin.py insights/tests/test_wizard_review.py
git commit -m "feat: show figures and corridors at review, edit them in admin

Asymmetric on purpose. A reviewer in the wizard judges the insight and
publishes or rejects it whole, so the children are read-only there -
with each corridor end's match method visible, because 'somewhere in
Sudan' and 'we do not know where' are different findings. A wrong figure
is corrected in Part 2 admin, where Django gives the inlines almost for
free.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Acceptance on EVAR

Spec §10.6. One real document exercising every path: EGY subject, a cross-border SDN→EGY corridor, community FGD quotes alongside `secondary_analysis` percentages, and figures with subgroups. Everything before this was tested against fixtures; this is the first time a real model reads a real PDF through the widened path.

**Files:**
- Modify: `CLAUDE.md` (the insights section)
- No new test file — this task is a manual run plus a recorded result.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Confirm the whole suite is green before touching a real document**

Run: `docker compose exec web python manage.py test insights -v 2`
Expected: **PASS**, every test from Tasks 1–7. Do not proceed on a red suite — a failure here is much cheaper to read than one mixed into a live extraction.

- [ ] **Step 2: Confirm the boundaries this document needs are loaded**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from boundaries.models import AdminArea
from django.db.models import Count
print(list(AdminArea.objects.filter(iso3__in=['EGY','SDN'], kind=AdminArea.KIND_ADMIN)
      .values('iso3','level').annotate(n=Count('id')).order_by('iso3','level')))
"
```
Expected: EGY at levels 0/1/2 and SDN at levels 0/1/2/3. If EGY is missing, the corridor's destination will resolve `unmatched` and Step 6's check cannot pass — load the EGY boundaries first.

- [ ] **Step 3: Get the document onto a path the container can read**

The file is at `C:\Users\Admin\Downloads\EVAR 2025 FINAL March 2026 - EN.pdf` on the host. `/work` is mounted **read-only** and anything written goes under `/app`. Use the wizard's upload route, which exists for exactly this and writes under `MEDIA_ROOT`:

Open **Admin → Community insights → Part 1 — Documents → insights**, choose the PDF, and let the wizard catalogue it. Note the job id it creates.

- [ ] **Step 4: Extract**

Run, substituting the job id from Step 3:

```bash
docker compose exec web python manage.py extract_insights --job <N>
```

- [ ] **Step 5: Read what the run cost**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from insights.models import ExtractionJob
job = ExtractionJob.objects.latest('id')
print('status', job.status)
print('proposed', job.insights_proposed)
print('rejected unverifiable', job.insights_rejected_unverifiable)
print('figures rejected', job.figures_rejected)
print('movements rejected', job.movements_rejected)
print(job.log or '(no log)')
"
```

Record these five numbers in the commit message at Step 8. `insights_rejected_unverifiable` is the one that matters most: it is a direct per-run measurement of how much this model invents, and a rise in it is the signal that the widening has started encouraging invention (spec §11).

- [ ] **Step 6: Check the four things this document exists to prove**

Run:
```bash
docker compose exec -T web python manage.py shell -c "
from insights.models import Insight, InsightFigure, InsightMovement
rows = Insight.objects.filter(job__isnull=False).order_by('-id')
print('insights', rows.count())
print('community voices', rows.filter(voice_type='community').count())
print('percent figures', InsightFigure.objects.filter(unit='percent').count())
print('figures with a subgroup', InsightFigure.objects.exclude(applies_to=None).count())
for m in InsightMovement.objects.all()[:10]:
    print('corridor', m.origin_name_as_written, m.origin_iso3, m.origin_match_method,
          '->', m.dest_name_as_written, m.dest_iso3, m.dest_match_method, m.flow_type, m.value)
"
```

All four must hold:
1. **Percentages survived as percentages** — `percent figures` is well above zero. This is the gap the whole design opened; a zero here means figures are not being emitted and Task 5's schema is the first place to look.
2. **A cross-border corridor geocoded on both sides** — at least one row printing `SDN … name -> EGY … name`. Both `match_method` values must be `name` or `pcode`, not `unmatched`.
3. **Community voice survived the widening** — `community voices` is above zero. EVAR holds 19 FGDs; if this is zero, the widened prompt has drowned community voice in survey statistics and §7.1 needs strengthening before this ships.
4. **Subgroups were kept** — `figures with a subgroup` is above zero, meaning disaggregated figures were not flattened.

If any fail, stop and fix the cause rather than the check. Record which failed.

- [ ] **Step 7: Update `CLAUDE.md`**

In the "### 2. Extract community insights from documents" section, after the first paragraph, add:

```markdown
The extraction reads a document for the whole situation, not only community
voice: movement corridors and their numbers, why people moved, hazards, who is
vulnerable and why, coping and needs. Every number carries the span as printed
and is discarded unless that span is in the quote, and a corridor's two ends are
geocoded independently — so a Sudan→Egypt flow places each side in its own
country. Coverage is opportunistic: a topic a document does not cover yields
nothing, and a thin sitrep returning two statements is still a correct run.

**The prompt is not the only half.** `insights/contract.py` says what is
accepted, `insights/prompts/extract_insights.md` says what is asked for, and
`insights/extractors/anthropic_api.py`'s `SCHEMA` says what can be emitted at
all — it sets `additionalProperties: False`, so a field missing from it is
forbidden rather than ignored and the run looks healthy while returning nothing
new. All three move together. `openai_compatible.py` is governed by the prompt
alone.
```

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the widened extraction and its first real run

Acceptance run on the Egypt EVAR 2025 assessment (EGY, 43 pages):
  insights proposed:        <N>
  rejected unverifiable:    <N>
  figures rejected:         <N>
  movements rejected:       <N>
  percent figures kept:     <N>
  community voices kept:    <N>
  SDN->EGY corridor:        both ends resolved by name

CLAUDE.md now names all three halves of the contract, because the JSON
schema is the one that silently forbids a field the other two agree on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §4.1/§7 → Task 5; §4.2 → Tasks 2, 3 (`figure_as_written`, the span check); §4.3/§4.5 → Task 2 Step 8 check 4; §4.4 → Task 2; §4.6 → Task 2; §5.1/§5.2/§5.3 → Task 2; §6.1 → Task 1; §6.2 → Task 3; §6.3 → Tasks 2 (counters), 3 (drops), 4 (logging); §6.4 → Task 3; §7.1 → Tasks 5, 8 check 3; §8 → Task 4; §9 → Task 7; §10 → Tasks 1–8; §11 → carried into `CLAUDE.md` at Task 8.

**Type consistency, checked across tasks.** `figure_as_written` (not `as_written`) on the model and in the payload; the API renames it to `as_written` only in its JSON, and Task 6's test asserts that rename. `dest_*` (not `destination_*`) on the model throughout; the API nests it under `destination` and Task 6's test asserts that. `row["drops"]` is a list of strings produced in Task 3 and consumed in Task 4, where a message starting `corridor` counts as a movement drop — which is why every corridor message in `_movements` begins with that word. `ROLE_VALUES`/`FIGURE_UNIT_VALUES`/`MOVEMENT_UNIT_VALUES`/`FLOW_TYPE_VALUES` are defined once in Task 2 and imported by Tasks 3 and 5.

**Known gaps, carried from spec §11 and not solved here:** `PAGES_PER_REQUEST = 8` can split an origin from its figure across two requests; table-only figures are not captured; a `role` miscoded as `subject` is caught only by review.
