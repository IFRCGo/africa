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

### 4.2 Every item keeps its verbatim quote

Numbers, origins, destinations and reasons are attributes **of a quoted sentence**, never
free-standing facts. `verify.py` stays universal — there is no row kind that skips it.

This is the decision that keeps the whole design honest. A model cannot be talked into
inventing a figure that must also appear, word for word, on the page it cites.

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
    insight     = FK(Insight, related_name="figures", on_delete=CASCADE)
    value       = models.FloatField()
    unit        = models.TextField(choices=FIGURE_UNITS)   # people / percent / households
    measures    = models.TextField()                       # "highly or extremely vulnerable"
    applies_to  = models.TextField(null=True, blank=True)  # "non-Arabic speaking households"
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
    value              = BigIntegerField(null=True, blank=True)
    unit               = TextField(choices=MOVEMENT_UNITS, null=True, blank=True)  # people / households
```

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
relax it.

### 6.1 Everything new is optional

`codings[].role`, `figures[]` and `movements[]` are all optional. **Every payload written
before today still validates and still produces byte-identical rows.** This is the first
test to write (§10).

### 6.2 `role` degrades, like `tag`

An unrecognised `role` becomes `subject`, matching how `taxonomy.normalise_coding` turns an
unknown tag into `other`. A role is an interpretation; a wrong one costs a query, not a
fact.

### 6.3 `unit` and `flow_type` are hard errors

An unknown `unit` or `flow_type` raises `ContractError` and the payload is rejected. These
are not interpretations: silently defaulting `percent` to `people` would turn "65 percent"
into "65 people" and store it as a fact. The existing boolean guards on `severity` and
`people_affected` exist for the same reason and are the precedent.

### 6.4 A corridor needs both ends

A `movements[]` entry with no `origin_name_as_written` **and** no `dest_name_as_written` is
rejected. "They fled here" with no stated origin produces no movement row rather than a
guessed one. One end named and the other absent is allowed and recorded as such — a
half-known corridor is a finding.

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

6. **A figure is only ever an attribute of a quoted sentence.** If the number is not
   printed in the passage you are quoting, there is no figure.
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

**Gate 4 covers the children.** A reviewed insight is skipped whole — its figures and
movements are not rewritten either. Re-running an extraction must not discard a figure a
reviewer corrected, for exactly the reason gate 4 exists for the quote.

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
   no `role` — loads and produces identical rows. Written first, before any new field
   exists.
2. **Contract.** Unknown `unit` and unknown `flow_type` raise `ContractError`; unknown
   `role` degrades to `subject`; a movement with neither end named is rejected.
3. **Loader.** Both sides of a corridor resolve independently (SDN level-0 origin, EGY
   level-1 destination); an unresolvable origin is recorded `unmatched` rather than
   dropped; gate 4 leaves a reviewed insight's children untouched on re-extraction.
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
