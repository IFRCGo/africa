# Comprehensive insight extraction: the numbers, the corridors, and the reasons

**Date:** 2026-09-16
**Status:** designed, not implemented
**Extends:** `2026-09-10-community-insights-design.md`. That spec's data model, four
gates and review flow stand. This one widens what a single extraction reads out of a
document and adds three structures to hold the result.

## 1. Why

The insights extraction reads a document for one thing: what a community said. Its prompt
says so plainly — *"Most sitreps contain no community voice at all. Returning only
`secondary_analysis` passages, or a short list, is the correct answer for such a document.
Do not pad."* Against a weekly sitrep that stance is right and it stays right.

Against an assessment report it leaves most of the document on the floor.

The worked example is `EVAR 2025 FINAL March 2026 - EN.pdf` — the Egypt Vulnerability
Assessment of Refugees, UNHCR/WFP with Egypt's CAPMAS, 43 pages, ISO3 **EGY**. Read it
today and the extraction returns a handful of quotes. What it walks past:

- **253 figures stated as percentages.** "About 65 percent of refugees are highly or
  extremely vulnerable"; "Nearly 58 percent face moderate to severe food insecurity";
  "Only 15 percent of refugees have access to a bank account". `Insight.people_affected`
  is a `BigIntegerField`. It cannot hold any of them.
- **A cross-border corridor.** 0.7 million Sudanese refugees registered in Egypt since
  April 2023; Egypt described as "both a transit and destination country". `Insight.iso3`
  is one required country and `places.resolve()` resolves one place. There is nowhere to
  say *from Sudan, to Egypt*.
- **The causes.** The document says why people came, who among them is most vulnerable and
  what that follows from. A quote can already carry both a `movement_pattern` tag and a
  `hazard` tag — but nothing records that the second is the *reason* for the first, so
  "what drives return movement this quarter" is not a question the database can answer.
- **19 focus group discussions.** Real community voice, on pages 3, 7–8, 17, 20–21, 23, 26
  and 34–35, sitting alongside the survey statistics.

The request this spec answers, in the user's words: *both qualitative and quantitative
information on population movement numbers, where they are coming from and where they are
going, why they are moving, why they are going back, the hazards they are exposed to, who
is vulnerable and why, the coping mechanisms they have adopted and their needs — all
wrapped with geolocation information where it is there.*

## 2. Goals

1. One extraction reads a document for all eight topics, not one.
2. A figure stated as a share is stored as a share, queryable and comparable across
   documents.
3. A movement statement names both ends of its corridor, each geocoded independently, so a
   cross-border flow can be drawn.
4. A cause is recorded as a link between codings, not as prose.
5. Nothing already published changes meaning, and no existing payload stops validating.

## 3. Non-goals

- **Table and chart figures.** The verbatim gate matches against stored page text. A table
  cell or a chart legend does not survive PyMuPDF's `get_text("text")` as a quotable
  sentence — EVAR's p.10 pie chart flattens to `Sudan Syria South Sudan Eritrea…`. Figures
  that exist *only* in a table are out of scope, decided knowingly (§4.2). EVAR's prose
  restates most headline figures, so the loss is small and it is visible rather than silent.
- **Splitting the extraction into two prompt modes.** Considered and rejected in §4.1.
- **A second review screen.** The wizard shows the new structures; it does not edit them
  (§9).
- **Dashboard rendering.** Drawing the arrows is a separate piece of work. This spec makes
  the data exist and serves it over the API; it does not touch `app.js`.

## 4. Decisions taken

### 4.1 One widened prompt, not two modes

A second prompt selected per job would let a sitrep keep the anti-padding stance while an
assessment got the deep read. It was rejected: two prompts are two things to keep in step
with `contract.py`, and a job pointed at the wrong one produces a quietly thin result that
looks like a thin document.

The anti-padding guard survives in a different form, and the prompt must state it:
**coverage is opportunistic. A topic the document does not cover yields nothing, and that
is still the correct answer.** Without that sentence, eight headings become eight things a
model feels obliged to fill.

### 4.2 Every item keeps its verbatim quote, and every number keeps its span

Numbers, origins, destinations and reasons are attributes **of a quoted sentence**, never
free-standing facts. `verify.py` stays universal — there is no row kind that skips it.

That alone is not enough, and it is worth being precise about why. `verify.py` checks the
*quote* against the page; it says nothing about a number typed beside it. A model could
quote "About 65 percent of refugees are highly or extremely vulnerable" perfectly and write
`value: 56`, and every gate would pass.

So a figure carries **`figure_as_written`** — the span exactly as printed: `"65 percent"`,
`"0.7 million"`, `"two-fifths of refugee households (44 percent)"`. It is required, and it
must occur in the normalised quote (`verify.normalise`, the same folding the quote gate
uses). `value` and `unit` are the *parsed reading* of that span. `InsightMovement.value`
carries `value_as_written` under the identical rule.

This is the repo's own idiom, one level down: `place_name_as_written` is what the document
said and `admin_pcode` is what we resolved it to, and the pair is what makes the resolution
auditable. A number gets the same treatment. It also handles "0.7 million" → `700000`
without a brittle digit-for-digit match, because the check is on the printed span, not on
the parsed value.

A figure whose span is not in the quote is dropped and counted (§6.3) — the insight and its
quote survive.

### 4.3 The subject place keeps its meaning

`Insight.iso3`, `place_name_as_written`, `admin_pcode`, `lat`, `lon` continue to mean *the
community this statement is about*. Origin and destination are added beside them, not in
place of them. Every non-movement insight is unaffected.

### 4.4 A corridor is a child row, not a pair of columns

Flat `origin_*`/`destination_*` columns on `Insight` were the first proposal. They fail on
a real EVAR sentence: p.10 names eight origin countries at once ("from more than 60
countries … including Sudan, Syrian Arab Republic, South Sudan, Eritrea, Ethiopia, Somalia,
Yemen and Iraq"), and the `(document, page, quote_sha1)` unique constraint means one quote
cannot be split into eight rows to hold them.

A child table where each row is a **complete corridor** handles it: eight rows, eight
unambiguous arrows, one quote. It also matches the shape `data_track.MovementFlow` already
proved is what draws an arrow.

### 4.5 `Insight` gains no columns

All three additions are a new column on an existing child table and two new child tables.
Every existing row, the `/insights/` API, the map layer and the review screen keep working
untouched. This is a property worth protecting, not an accident.

### 4.6 A corridor owns its own number

`InsightMovement` carries `value` and `unit` rather than pointing at an `InsightFigure`.
There is mild redundancy between the two. It is accepted: an arrow's thickness is set by
the number on that corridor, and a foreign key between two child tables of the same parent
buys nothing a reviewer or a query can use.

## 5. Data model

Three changes, one additive migration, no backfill.

### 5.1 `InsightCoding.role`

```python
CODING_ROLES = [("subject", "Subject"), ("driver", "Driver"), ("barrier", "Barrier")]

role = models.TextField(choices=CODING_ROLES, default="subject")
```

The unique constraint becomes `(insight, dimension, tag, role)`. The same tag may
legitimately appear twice on one statement in two roles — displacement as the thing
happening and displacement as what drives a further need.

- `subject` — what the statement is about. The default, and what every existing row means.
- `driver` — the cause. `movement_pattern:return_movement` as subject plus
  `hazard:armed_conflict` as driver *is* "why they are returning", as a query.
- `barrier` — what blocks access. `need:health` subject plus
  `vulnerability:statelessness_documentation` barrier is "they cannot reach the clinic
  without papers".

"Who is vulnerable and why" uses the identical mechanism with `vulnerability` as subject.
**No new taxonomy entries are required.** The vocabulary in `data_pipeline/taxonomy.json`
already covers all five dimensions; what was missing was the edge between two codings, not
more nodes.

### 5.2 `InsightFigure`

```python
class InsightFigure(models.Model):
    insight           = FK(Insight, related_name="figures", on_delete=CASCADE)
    figure_as_written = models.TextField()                       # "65 percent", "0.7 million"
    value             = models.FloatField()
    unit              = models.TextField(choices=FIGURE_UNITS)   # people / percent / households
    measures          = models.TextField()                       # "highly or extremely vulnerable"
    applies_to        = models.TextField(null=True, blank=True)  # "non-Arabic speaking households"
```

`value` is a float because a share is not an integer. `unit` is closed and validated: an
invented unit changes what a number means, so an unknown one is a hard error, not a
degradation (§6.3).

`applies_to` is what makes the table earn its place. EVAR p.22 states three figures in one
passage — "44 percent … 36 percent among non-Arabic speaking households … 26 percent in
other regions". One quote, three rows, each keeping the subgroup it belongs to. Flattening
that to a single number on the parent would keep one figure and lose two.

`Insight.people_affected` is untouched and still holds the headline people-count.

### 5.3 `InsightMovement`

```python
class InsightMovement(models.Model):
    insight            = FK(Insight, related_name="movements", on_delete=CASCADE)

    origin_name_as_written   = TextField(null=True, blank=True)
    origin_iso3              = CharField(max_length=3, null=True, blank=True)
    origin_pcode             = TextField(null=True, blank=True)
    origin_admin_level       = IntegerField(null=True, blank=True)
    origin_match_method      = TextField(default="unmatched")
    origin_lat, origin_lon   = FloatField(null=True, blank=True) x2

    dest_name_as_written     = TextField(null=True, blank=True)
    dest_iso3                = CharField(max_length=3, null=True, blank=True)
    dest_pcode               = TextField(null=True, blank=True)
    dest_admin_level         = IntegerField(null=True, blank=True)
    dest_match_method        = TextField(default="unmatched")
    dest_lat, dest_lon       = FloatField(null=True, blank=True) x2

    flow_type          = TextField(choices=FLOW_TYPES)   # cross_border / internal / return / transit
    value_as_written   = TextField(null=True, blank=True)          # "0.7 million"
    value              = BigIntegerField(null=True, blank=True)
    unit               = TextField(choices=MOVEMENT_UNITS, null=True, blank=True)  # people / households
```

A corridor stating a number carries `value_as_written` under the §4.2 rule, checked against
the quote the same way. A corridor with no number states no number — `value_as_written`,
`value` and `unit` are all null together, and a corridor is still worth recording without
one.

`unit` here is **not** `FIGURE_UNITS`. A corridor counts people or households; it is never a
share, and `value` is a `BigIntegerField` that could not hold one honestly. A percentage
about a moving population is a figure (§5.2) attached to the same quote, not a corridor.

`flow_type` is the corridor's **direction class**, and it is deliberately a small closed set
of its own — `cross_border`, `internal`, `return`, `transit` — matching what
`data_track.MovementFlow.flow_type` already means, because that is what decides how an arrow
is drawn. It is not the same thing as the `movement_pattern` coding on the parent insight,
which is the richer label from the taxonomy (`relocation_to_camps`, `mixed_movement`,
`evacuation` and the rest). One quote can carry `flow_type = cross_border` on its corridor
and `movement_pattern:mixed_movement` as its coding; neither is derivable from the other and
neither validates against the other's vocabulary.

`origin_match_method` and `dest_match_method` carry the same `pcode` / `name` / `unmatched`
honesty `places.py` already documents for the subject place: "somewhere in Sudan" and "we
do not know where" are different findings and only this column tells them apart afterwards.

`origin_lat/lon` are **label positions** copied from `AdminArea.center_lat/center_lon`, not
addresses — the identical caveat the subject place carries, and the dashboard popup must
repeat it when these are eventually drawn.

## 6. The contract

`insights/contract.py` and `insights/prompts/extract_insights.md` are two halves of one
thing and change together. That rule is in `contract.py`'s docstring and this spec does not
relax it — it corrects it.

**There is a third half, and it is load-bearing.** `insights/extractors/anthropic_api.py`
hard-codes a `SCHEMA` constant passed as the request's `json_schema` output format, and that
schema sets `"additionalProperties": False` on both the insight object and the coding object.
Until it is updated, the Anthropic adapter **cannot emit** `figures`, `movements` or
`codings[].role` at all: the fields are not merely ignored, they are forbidden by the
response format. A prompt-and-contract change alone would produce a run that looks healthy
and returns nothing new.

`insights/extractors/openai_compatible.py` is unaffected — it asks for
`{"type": "json_object"}` with no schema, so it is governed by the prompt alone.

`contract.py`'s docstring should be amended to name the schema as the third half, so the
next person to widen the payload finds this stated rather than discovers it.

### 6.1 Everything new is optional

`codings[].role`, `figures[]` and `movements[]` are all optional. **Every payload written
before today still validates and still produces byte-identical rows.** This is the first
test to write (§10).

### 6.2 `role` degrades, like `tag`

An unrecognised `role` becomes `subject`, matching how `taxonomy.normalise_coding` turns an
unknown tag into `other`. A role is an interpretation; a wrong one costs a query, not a
fact.

### 6.3 A bad figure costs the figure, never the document

`unit` and `flow_type` are closed vocabularies and they never degrade to a default:
silently reading `percent` as `people` would turn "65 percent" into "65 people" and store it
as a fact.

But the penalty is scoped to the row. An unknown `unit` or `flow_type`, or a
`figure_as_written` that is not in the quote, **drops that figure or corridor and is
counted** — the insight, its quote and its codings still load. EVAR states currency amounts
and ratios alongside its percentages; one figure the model labels `EGP` must not zero out a
43-page run. Rejecting the whole payload for one bad vocabulary word would also undo §4.1:
the widened prompt asks for far more small structured items per document, so the chance of
one being wrong is much higher than it was, and the blast radius has to shrink to match.

`ContractError` on the whole payload is reserved for a malformed *shape* — `figures` not a
list, a figure that is not an object, a missing required key — which is a broken producer
rather than a wrong reading.

The dropped counts are surfaced, never swallowed: `ExtractionJob` gains
`figures_rejected` and `movements_rejected` beside the existing
`insights_rejected_unverifiable`, and each drop is written to `ExtractionJob.log` naming the
insight and the reason. `insights_rejected_unverifiable` keeps its current meaning — whole
insights that failed the quote gate — so the number a reviewer already watches does not
quietly change definition.

The precedent is `verify.py`: a quote that does not match is discarded and counted, and the
run continues.

### 6.4 A corridor needs at least one end

A `movements[]` entry with no `origin_name_as_written` **and** no `dest_name_as_written`
names nothing and is dropped and counted (§6.3). "They fled here", with neither end stated,
produces no movement row rather than a guessed one.

One end named and the other absent is **allowed** and recorded as such. A half-known
corridor is a finding: "arrivals from Sudan" with no stated destination is true, useful, and
honestly incomplete, and `dest_match_method` says so.

## 7. The prompt

`extract_insights.md` keeps its five numbered rules verbatim and its output example grows
the new blocks. It gains a section naming what to look for, mapped onto the structures
above rather than onto eight free-text headings:

| What is asked for | Where it lands |
|---|---|
| movement numbers | `InsightMovement.value` / `unit` |
| where from / where to | `InsightMovement` origin and destination, each geocoded |
| why they move, why they return | `movement_pattern` as `subject`, the cause as `driver` |
| hazards | `hazard` codings, unchanged |
| who is vulnerable, and why | `vulnerability` as `subject`, the cause as `driver` |
| coping mechanisms | `coping` codings, unchanged |
| needs | `need` codings, plus `barrier` for what blocks access |
| everything else quantitative | `InsightFigure` |

Two rules are added to the five:

6. **A figure is only ever an attribute of a quoted sentence, and you must copy its span.**
   Give `figure_as_written` exactly as printed — "65 percent", "0.7 million" — alongside the
   parsed `value` and `unit`. If the number is not printed in the passage you are quoting,
   there is no figure.
7. **Name only the ends the text names.** Do not infer an origin or a destination from
   surrounding context. A corridor with one end stated and the other genuinely absent is
   recorded with one end; a corridor with neither is not a corridor (§6.4).

And the guard from §4.1, stated where the eight topics are introduced: coverage is
opportunistic; a topic the document does not cover yields nothing.

### 7.1 `voice_type` does real work now

EVAR's 19 FGDs are `community`. Its 253 percentages are `secondary_analysis`. That column
is what stops a widened stance from drowning community voice in survey statistics, and the
API already filters on it. The prompt must be explicit that widening the topics does **not**
blur the two labels.

## 8. Loading

`insights/loader.py` keeps its four gates. Two extensions:

**Gate 3 runs twice more.** For each movement row, `places.resolve()` is called once per
side with that side's own `iso3` — `places.py` itself is unchanged. Verified against the
live boundary library: every country carries a level-0 row, so `Sudan` → SDN centroid and
`Alexandria` → an EGY governorate both resolve today. EGY holds 27 admin-1 and 365 admin-2
areas, so EVAR's named locations geocode.

**Each side's `iso3` comes from the payload, and is never inherited.** `places.resolve()`
needs a country per side, and on the corridor that matters — SDN → EGY — neither side equals
the parent's `iso3` in both positions. The model states `origin_iso3` and `dest_iso3` in
`movements[]`. A side with no `iso3` is recorded `unmatched` with its written name kept;
defaulting it to the parent's country would invent a placement and would be wrong precisely
on cross-border movement, the case this table exists for.

**Gate 4 covers the children.** A reviewed insight is skipped whole — its figures and
movements are not rewritten either. Re-running an extraction must not discard a figure a
reviewer corrected, for exactly the reason gate 4 exists for the quote.

**A pending parent's children are replaced wholesale.** Neither child table has a natural
key, so re-running a job on a still-pending insight would otherwise duplicate every figure
and corridor. This is not a new rule: `loader.py` already does exactly this for codings
(`insight.codings.all().delete()` before `bulk_create`), with the reason in a comment there
— a re-run's reading of a statement supersedes its own earlier one, and merging the two
accumulates rows no single reading ever proposed. Figures and movements follow it.

## 9. Review

Deliberately asymmetric, to keep the change shippable:

- **Wizard review step** (`insights/templates/insights/_review_row.html`) shows figures and
  movements **read-only** beneath the quote, with each corridor's match method visible. A
  reviewer's job here is to judge the insight and publish or reject it whole, not to retype
  a number.
- **Part 2 admin** gains `InsightFigure` and `InsightMovement` inlines beside the existing
  codings, and `role` on the coding inline. That is where a wrong figure is corrected, and
  Django gives it almost for free.

## 10. Verification

Test-driven, in this order:

1. **Backwards compatibility.** An existing fixture payload — no `figures`, no `movements`,
   no `role` — loads and produces rows identical in every pre-existing column, with
   `role = subject` and no children. Written first, before any new field exists.
2. **Contract.** Unknown `unit`, unknown `flow_type`, and a `figure_as_written` absent from
   the quote each drop their own row and leave the insight intact, counted and logged;
   unknown `role` degrades to `subject`; a movement with neither end named is dropped; a
   malformed shape still raises `ContractError` for the payload.
3. **Loader.** Both sides of a corridor resolve independently (SDN level-0 origin, EGY
   level-1 destination); a side with no `iso3` is `unmatched` and is *not* given the
   parent's country; an unresolvable origin is recorded `unmatched` rather than dropped;
   re-loading a pending insight replaces its children rather than duplicating them; gate 4
   leaves a reviewed insight's children untouched on re-extraction.
4. **Model.** The widened coding constraint admits the same tag in two roles and still
   rejects a true duplicate.
5. **API.** `figures`, `movements` and `role` are serialised; `?role=` and `?flow_type=`
   filter correctly, using the single-`.filter()` join rule `views.py` already documents
   for `dimension`+`tag`.
6. **Acceptance, end to end, on EVAR itself.** One document exercising every path in this
   design: EGY subject, a cross-border SDN→EGY corridor, community FGD quotes alongside
   `secondary_analysis` percentages, and figures with subgroups. The check is that the
   corridor geocodes on both sides and that percentage figures survive as `percent`.

Run as the repo requires:

    docker compose exec web python manage.py test insights -v 2

## 11. Known limits, stated rather than discovered later

- **Chunking can split a corridor.** `PAGES_PER_REQUEST = 8` keeps page numbers close to
  the text, which is right. It also means an origin named on page 8 and its figure on page
  9 are read in different requests and may not be joined. Not solved here.
- **Table-only figures are not captured** (§3). Visible rather than silent: the figure
  simply does not appear, rather than appearing unverified.
- **A widened prompt costs more tokens per document** than the community-voice stance did,
  on every document including the thin ones. `ExtractionJob.insights_rejected_unverifiable`
  is the column to watch after the first real batch — a rise there is the signal that the
  widening has started encouraging invention.
- **`role` is a model's judgement.** A driver miscoded as a subject is not caught by any
  gate; only review catches it. This is the same standing exposure the codings already
  carry.
