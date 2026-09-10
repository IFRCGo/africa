# Community insights: what people said, who wrote it down, and how it reaches the map

**Date:** 2026-09-10
**Status:** designed, not implemented
**Scope:** sub-project 1 of three. The MCP channel (2) and primary data collection (3)
are described in §13 only far enough to show that this design does not block them; each
gets its own spec and is **out of scope here**.

## 1. Why

The platform holds two kinds of data and has a way in for each. Numbers read out of UNHCR
PDFs arrive through the seven-step pipeline. External layers — IPC, FEWS NET, DTM, UNHCR
APIs — arrive as MCP payloads that a loader upserts into subject tables. Both are working.

Neither carries what a community actually said.

A community in Afar told an assessment team, in substance: *when it rains we get flash
floods, and with the fighting around us the hospitals are gone — we have cholera now and
nowhere to take the sick.* That single statement names a place, two hazards, two needs and
a vulnerable group, and it does so with an authority no derived indicator has. The platform
has nowhere to put it.

What it has instead is `narrative_tags.snippet`: sentences a regex matched in a UNHCR
report, surfaced in the dashboard's Community Insights panel. Those are useful and they
stay. But they are an analyst's prose, matched by keyword — not a community's words. The
panel is currently named for something it does not contain.

Three specific gaps follow:

**There is no route for a document that is not a UNHCR PDF.** `s01_catalog` walks two
hard-coded folders. An assessment report, an FGD write-up or a partner's PDF sitting in
any other folder cannot enter the system at all, however relevant it is.

**There is no route for a human to type one in.** Every table is written by a pipeline
step or a loader. A statement relayed by a field team over WhatsApp has no home.

**Nothing that a human curates survives.** `s03_parse` deletes and rebuilds
`population_figures`, `movement_flows` and `narrative_tags` on every run. `s04_events`
deletes *every* event, including the curated milestones, and rebuilds them from a literal
Python list. A hand-corrected row in any of those tables is destroyed by the next
"Update now". This is not a hypothetical: it is why `Event.source` has a `'curated'` value
that protects nothing.

## 2. Goals

1. Store a community statement **whole and verbatim**, with the codings derived from it
   hanging off it, so the words and the interpretation are never confused for each other.
2. Accept those statements from **three intake routes** — a folder of documents read by an
   AI agent, a single uploaded document, and a form typed by a human — writing all three
   to one table.
3. Be **producer-agnostic**: Claude Code, Codex, a local model, or a hosted API can all
   feed the same JSON contract, and correctness must not depend on which one did.
4. Publish **only what a human has reviewed**, from Django Admin, and have publishing take
   effect immediately.
5. Show them on the dashboard: three tabs (community / analyst / both) with tab-scoped
   search, and a quote-bubble map layer filtered by the same theme selection as every
   other panel.
6. Never be truncated by a pipeline run.

## 3. Non-goals

- **No changes to the pipeline's tables or steps.** `narrative_tags`, `population_figures`,
  `movement_flows` and `events` are untouched. `s03_parse` keeps rebuilding what it owns.
- **No fix for `s04_events` deleting curated milestones.** It is a real bug of the same
  family and it is flagged in §14, not fixed here.
- **No new scheduler, queue or worker service.** No Celery. Background work reuses the
  updater's existing subprocess-and-lock pattern.
- **No GeoDjango.** Consistent with `boundaries/models.py` and `external_data/models.py`:
  `lat`/`lon` are plain floats, `admin_pcode` is plain text.
- **No decision on the updater's future.** §14 records the criterion for deciding later.
- **No primary data collection form.** Sub-project 3.
- **No automatic translation.** A French statement stores its original; a translation is
  entered by a reviewer if one is wanted.

## 4. Decisions taken

| Decision | Why |
|---|---|
| A new `insights` app, not new models in `data_track` | `data_track` is the pipeline's app and its tables are rebuilt. Human-reviewed rows must not live where a step can truncate them. |
| Parent `Insight` + child `InsightCoding` | The unit of record is the statement. Codings are derived from it and there may be many; flattening them into one tagged row loses the statement. |
| Verbatim enforced by Django, not trusted from the model | Anthropic's Citations API would guarantee it natively, but only for Claude. Re-matching the quote against stored page text works identically for a local 8B model, and is the only guard that makes "bring your own agent" safe. |
| `tag` constrained to `taxonomy.json` | Inherits the dashboard's existing dimension colours and labels, and stops the vocabulary growing by model whim. |
| `status` gate, published rows only on the dashboard | Requested explicitly; also the only defensible position for LLM-derived text in an operational tool. |
| Table named `insights`, not `community_insights` | `/api/community-insights/` already exists and serves `narrative_tags`. See §5.6. |
| Live API endpoint for this one panel | Quotes are low-volume text. The map layers keep their pre-built files, so map performance is unaffected, and "publish" can mean published. |
| Two LLM adapters, not N | Anthropic native plus one OpenAI-compatible path covers OpenAI, Codex, Ollama, LM Studio and vLLM, which all speak the same wire format. |
| Phase 1 ships without any LLM dependency | The external-agent route needs no API key, no egress and no new package. It is usable before any of those questions are answered. |

## 5. Data model

New app `insights`. Four tables. Nothing in `data_pipeline` writes to any of them.

### 5.1 `insights` (model `Insight`) — the statement

One row is one thing a community said, kept whole.

| Column | Type | Notes |
|---|---|---|
| `quote` | text | **The record.** Verbatim, in full, never summarised or trimmed. |
| `quote_language` | text | ISO 639-1. Chad and CAR sources are French. |
| `quote_translated` | text, null | Entered by a reviewer. The original stays authoritative. |
| `quote_sha1` | char(40) | Fingerprint of the normalised quote. Part of the natural key. |
| `voice_type` | text | `community` or `secondary_analysis`. Drives the dashboard tabs. |
| `channel` | text | `document_ai` / `manual` / `primary`. |
| `document` | FK `data_track.Document`, null | The source page in the archive. Null for manual and primary. |
| `page` | int, null | Page the quote was found on. Null with `document`. |
| `stated_on` | date, indexed | When it was said: the report date, or the collection date. The dashboard's month timeline rides on this. |
| `iso3` | char(3), indexed | |
| `place_name_as_written` | text, null | "Afar", exactly as the source wrote it. |
| `admin_pcode` | text, null | Resolved boundary. Plain text, not a FK — see §5.5. |
| `admin_level` | int, null | |
| `match_method` | text | `pcode` / `name` / `unmatched`, following `HumanitarianServicePoint`. |
| `lat`, `lon` | float, null | Copied from the matched polygon's point-on-surface, so a map needs no join. Null when unmatched. |
| `people_affected` | bigint, null | **Optional, and usually null.** Most statements carry no number. |
| `severity` | int, null | 1–5, the same scale `Event.severity` uses. Optional. |
| `method` | text | `llm` or `manual`. |
| `model_used` | text, null | Which model produced it, for the record. |
| `confidence` | text, null | `high` / `medium` / `low`, as the producer reported it. |
| `status` | text, indexed | `pending` / `published` / `rejected`. Default `pending`. |
| `rejection_reason` | text, null | Kept. A rejected extraction is evidence about the model. |
| `reviewed_by` | FK `auth.User`, null | |
| `reviewed_at` | datetime, null | |
| `job` | FK `ExtractionJob`, null | Which run proposed it. |
| `created_at` | datetime | |

```
constraints:
  UniqueConstraint(document, page, quote_sha1, name="uniq_insight_quote", nulls_distinct=False)
indexes:
  (status, voice_type, stated_on)
  (iso3, stated_on)
```

`nulls_distinct=False` for the same reason `source_sync` and `admin_areas` need it:
manually entered rows have a null `document` and a null `page`, and under PostgreSQL's
default rule two nulls never collide, so every duplicate manual entry would be accepted
silently.

**`people_affected` and `severity` are nullable by deliberate choice.** The Afar statement
carries no number. A required field would invite a model to invent one, and an invented
number in a humanitarian platform is worse than an absent one.

### 5.2 `insight_codings` (model `InsightCoding`) — what the statement says

Many per insight. This is the interpretation, kept separate from the words.

| Column | Type | Notes |
|---|---|---|
| `insight` | FK `Insight`, cascade | |
| `dimension` | text | `hazard` / `vulnerability` / `need` / `coping` / `movement_pattern` — the five `taxonomy.json` already defines. |
| `tag` | text | **Must be a key under that dimension in `taxonomy.json`**, or the literal `other`. |
| `tag_raw` | text, null | What the producer actually proposed, when it fell outside the vocabulary. |

```
constraints:
  UniqueConstraint(insight, dimension, tag, name="uniq_insight_coding")
```

The Afar statement produces five rows: `hazard/flooding`, `hazard/disease_outbreak`,
`need/health`, `need/water_wash`, `vulnerability/disability_elderly`.

Constraining `tag` to the existing vocabulary is what lets the dashboard render these with
the colours and labels in `DIM_META` without a single new mapping. An off-vocabulary
proposal keeps its dimension, becomes `other`, preserves the raw suggestion in `tag_raw`,
and is flagged in review — so the taxonomy grows by a human decision.

### 5.3 `insight_folders` (model `InsightFolder`) — a registered source folder

| Column | Type | Notes |
|---|---|---|
| `label` | text | "IOM DTM Chad round 12" |
| `path` | text, unique | Must resolve inside the container. Validated on save. |
| `default_iso3` | char(3), null | A hint passed to the producer. |
| `recursive` | bool | |
| `created_at` | datetime | |

### 5.4 `insight_jobs` (model `ExtractionJob`) — one extraction run

| Column | Type | Notes |
|---|---|---|
| `folder` | FK `InsightFolder`, null | Null for a single-document job. |
| `producer` | text | `external` / `anthropic` / `openai_compatible` |
| `model_used` | text, null | |
| `status` | text | `queued` / `running` / `loaded` / `failed` |
| `documents_total`, `documents_done` | int | |
| `insights_proposed` | int | |
| `insights_rejected_unverifiable` | int | Quotes that failed the verbatim check. |
| `insights_skipped_reviewed` | int | Rows a human had already touched. |
| `log` | text | |
| `started_at`, `finished_at` | datetime, null | |

`insights_rejected_unverifiable` is the number that matters most. It is a direct,
per-run measurement of how much a given model invents, and it is the reason a cheap or
local model is safe to try.

### 5.5 Relationship to the boundary library

`admin_pcode` is plain text, **not** a foreign key, for the reason the external-data spec
§5.7 already records: `admin_areas` is unique on `(source, kind, level, pcode)`, so a
p-code alone does not identify a row. Joins resolve on `(iso3, level, pcode)` and are the
caller's decision. Recorded again here so nobody "fixes" it by adding a constraint that
cannot hold.

### 5.6 The name collision, stated plainly

`external_data/views.py:164` already serves `/api/community-insights/`, reading
`narrative_tags` through the ORM. The `CREATE VIEW community_insights` in the
external-data spec §5.6 was never implemented — no migration creates it — but the API
path is live and documented in the API index.

Therefore:

- The new table is `insights`, **not** `community_insights`.
- `/api/community-insights/` **keeps its current behaviour and is not changed.** It
  returns regex snippets from `narrative_tags`, which in this design's vocabulary are
  `secondary_analysis` voice.
- The new endpoint is `/api/insights/` (§10).

Two endpoints with similar names returning different things is a wart. It is the correct
trade against breaking a documented URL, and the intent is to deprecate
`/api/community-insights/` once the panel reads the new endpoint — a later, separate
change.

## 6. The extraction contract

The contract is what makes "bring your own agent" work. One JSON shape, one prompt file,
one loader; Claude Code, Codex, a local model and the in-container adapter are all merely
producers of that shape.

### 6.1 The prompt file is the single source of truth

`insights/prompts/extract_insights.md` holds the instructions and the JSON schema, and
nothing else holds them. The in-container adapter reads it at runtime. A new `CLAUDE.md`
at the repo root — with `AGENTS.md` beside it, which is the name Codex reads — says little
more than: *to extract community insights, read `insights/prompts/extract_insights.md` and
follow it.* One file to edit when the extraction changes; every producer picks it up.

This also answers the question that prompted this work. **`.mcp.json` needs no change and
no companion file.** Claude Code reads it automatically from this folder — that is why the
HDX, IPC, FEWS NET, IFRC GO and UNHCR tools are available in a session opened here — and
Codex reads the same format. The settings for connecting to the MCP servers in use are
already correct. What was missing was never a second config file; it is the instructions
file telling an agent what to do in this repository, and this repository has never had one.

### 6.2 Where a payload lands

`data_pipeline/mcp_cache/insights/<document-stem>.json`.

Writable, already mounted, and already the "an agent left a payload here" convention the
external-data loaders use. It matters that this is not under `/work`: that mount is
**read-only** (`docker-compose.yml`, mount 1), so an agent running on the host cannot
write a payload there for the container to read.

### 6.3 The payload

```json
{
  "source": {
    "rel_path": "assessments/2026/chad-ouaddai-fgd-march.pdf",
    "sha1": "…",
    "report_date": "2026-03-14"
  },
  "producer": { "agent": "claude-code", "model": "claude-opus-5" },
  "insights": [
    {
      "quote": "When it rains we get flash floods, and with the fighting around us the hospitals are gone — we have cholera now and nowhere to take the sick.",
      "quote_language": "en",
      "page": 7,
      "voice_type": "community",
      "place_name_as_written": "Afar",
      "iso3": "ETH",
      "codings": [
        { "dimension": "hazard",        "tag": "flooding" },
        { "dimension": "hazard",        "tag": "disease_outbreak" },
        { "dimension": "need",          "tag": "health" },
        { "dimension": "need",          "tag": "water_wash" },
        { "dimension": "vulnerability", "tag": "disability_elderly" }
      ],
      "people_affected": null,
      "severity": 4,
      "confidence": "high"
    }
  ]
}
```

### 6.4 The four gates

Every **document-derived** payload passes these before a row is written. They are the
design's load-bearing element: the loader **validates** rather than trusts, so an unknown
model produces *fewer* insights, not wrong ones.

1. **Verbatim check — when, and only when, `document` is not null.** `quote` must occur in
   `document_text` for the page it names, after whitespace and unicode-dash normalisation. A
   quote that is not there is rejected, counted on the job, and never shown to a reviewer.
   This is the one guard that does not depend on the provider, which is exactly why it is the
   one that matters.

   **A null `document` skips it, by necessity and by design.** Manual and primary-collected
   statements have no stored page to check against; there is nothing to compare and no
   pretence that there is. `method='manual'` records the absence, and the human who typed it
   is the guarantee. This is the single rule — §9's quote-edit behaviour follows it rather
   than adding an exception to it.
2. **Vocabulary check.** Each `tag` must be a key under its `dimension` in `taxonomy.json`,
   or it degrades to `other` + `tag_raw` and is flagged.
3. **Place resolution.** `place_name_as_written` + `iso3` is matched against `admin_areas`;
   `match_method` records `pcode`, `name` or `unmatched`, and `lat`/`lon` are copied from the
   matched polygon. Unmatched is a normal outcome, not a failure.
4. **Conflict rule.** Insert if new. If the row exists and its `status` is no longer
   `pending`, **skip and count it** — do not update. `external_data/loaders/base.py`
   overwrites on conflict, which is right for API data and wrong here: it would silently
   discard a reviewer's corrections on every re-run.

   **A still-`pending` row is overwritten, and that is correct.** The loader is replacing its
   own earlier proposal on a row no human has touched — a re-run with a better model should
   improve the queue, not double it. `status` is the whole test: untouched means the loader
   still owns the row, anything else means a person does.

Everything lands as `status='pending'`.

### 6.5 What the loader shares with `external_data`, and what it does not

Shares: parse is pure and does no database access; one payload is one transaction; an
empty payload is an error rather than a quiet success.

Does not share: `SourceSync` (there is no watermark — documents are not a date-filtered
feed), and overwrite-on-conflict (§6.4 gate 4).

## 7. Intake

Two routes in, both from Django Admin, both ending at a `Document` row plus its
`DocumentText` pages.

**A folder.** Register an `InsightFolder`; Admin lists its contents and marks what is
already catalogued. "Catalogue and queue" walks the folder, creates a `Document` per file,
extracts text page by page with PyMuPDF — the same `fitz` calls `s02_extract_text` makes —
and opens an `ExtractionJob`.

The path must be under a mount the container can see. `/work` is the whole *SUDAN Ops*
folder and is already mounted, so anything beneath it works today. Admin validates on save
and reports an unreachable path immediately rather than failing later inside a job. A
folder elsewhere needs one line in `docker-compose.yml`, exactly as the boundary library's
three extra mounts already do.

**A single document.** A file field on the same screen. Uploads land under a new
`MEDIA_ROOT` inside `/app` (writable), then follow the identical path.

PDF and DOCX. `python-docx` is already pinned for the documentation build.

### 7.1 What intake writes on the `Document` row

`Document.rel_path` is unique and is what `s01_catalog` matches on, so these values are
part of the design rather than an implementation detail:

| Field | Value |
|---|---|
| `rel_path` | Relative to `SOURCE_ROOT` when the file is under `/work`, so it resolves exactly as a UNHCR PDF's does. `media/<subpath>` for an upload. Unique either way. |
| `source_collection` | `insights` — distinguishing these from `regional` and `sudan_only`. |
| `family` | `insight_source`. |
| `report_date`, `date_source` | From the folder registration or the review screen; `date_source='intake'`. |
| `sha1`, `pages`, `file_size` | Computed at intake, as `s01` computes them. |

### 7.2 Why this does not collide with the pipeline

Verified against the code, not assumed:

- `s01_catalog` walks only `SOURCE_COLLECTIONS` and **never deletes** — it skips paths
  already stored. Documents from this channel are invisible to it.
- `s02_extract_text` selects `Document.objects.filter(texts__isnull=True)`. Because intake
  writes `DocumentText` itself, these documents are never selected, so `s02` never tries to
  reopen a file at a path it cannot resolve. Its `fitz.open` is inside a `try/except` in any
  case.
- `s03_parse` dispatches its positional parsers on `family` and nothing else
  (`s03_parse.py:811` `family == "weekly_mapping"`, `:813` `family == "sudan_return"`,
  `:817` `family in NARRATIVE_FAMILIES`). `insight_source` matches none of them, so none
  fire. The `"CORE Return" in rel_path` test at `s03_parse.py:310` sits *inside*
  `parse_sudan_return` and is only reached once `family` has already matched — so an
  uploaded file whose name happens to contain "Return" cannot trigger it.
- `s03_parse`'s taxonomy tagger, however, runs for **every** document that has text
  (`s03_parse.py:823`, outside the family branches). Uploaded documents will therefore be
  regex-tagged into `narrative_tags` like any other. That is harmless and correct: those
  tags are analyst voice, they live in the table that is rebuilt each run, and they never
  touch `insights`.

Documents from this channel therefore sit in the archive alongside the UNHCR reports
without the pipeline touching them, and without them touching the pipeline.

## 8. Producing the insights

### 8.1 Phase 1 — an external agent

The job sits `queued`. An analyst opens Claude Code or Codex in this folder; the agent
reads `CLAUDE.md` → the prompt file → the queued documents, and writes payloads to
`mcp_cache/insights/`. An Admin action, "Load payloads", runs the four gates and loads
them.

No API key. No container egress. No new Python package. This phase is complete and usable
on its own.

### 8.2 Phase 2 — in-container adapters

A "Run extraction now" button runs `manage.py extract_insights --job N` as a subprocess,
reusing the updater's existing lock-and-stream pattern so progress is watchable. No Celery,
no new service.

Two adapters behind one interface:

- **Anthropic** — the official `anthropic` SDK. Model `claude-opus-5`, adaptive thinking
  (`thinking={"type": "adaptive"}`; `budget_tokens` is rejected on this model), structured
  outputs via `output_config={"format": …}` against the §6.3 schema, streaming for long
  documents.
- **OpenAI-compatible** — one code path covering OpenAI, Codex, Ollama, LM Studio and
  vLLM, which all speak the same wire format. A local model is `base_url` pointing at
  `host.docker.internal`.

Configured by `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. These are read
with the `get(X) or default` idiom, **not** `get(X, default)`: an empty value in `.env`
must fall back rather than blank the setting.

Note for whoever implements this: the bundled `claude-api` skill produces Anthropic SDK
code only, and asks to be told when a design is deliberately provider-neutral. It applies
to the Anthropic adapter and not to the OpenAI-compatible one. That is intentional here,
not an oversight.

Structured outputs and Citations cannot be combined (the API returns 400), which is a
second reason the verbatim guarantee lives in Django: it costs nothing and works for every
provider.

## 9. Review, and the form

Both of the user's stated Admin requirements are the same screen, because a hand-keyed
insight and a reviewed AI insight should be indistinguishable once saved.

**The queue.** `Insights` in the Admin sidebar, filtered by default to `status=pending`.
Columns: first line of the quote, country and place, dimensions found, source document,
proposer. Filters on voice type, country, dimension, method, status and job.

**Reviewing one.** The quote sits at the top, in full and unedited, linked to its source
document and page — the reviewer reads the actual words before seeing what the model made
of them. Below it, everything the producer proposed is editable:

- codings, as inline rows, each constrained to the taxonomy vocabulary
- the place, as a dropdown over `admin_areas`, pre-filled on a successful match
- `voice_type` — **the field most likely to be wrong**, and the one the dashboard tabs
  depend on, so it is prominent
- `people_affected` and `severity`, usually blank and left blank
- anything flagged: off-vocabulary tag, unmatched place, low confidence

Actions: **Publish**, **Reject** (reason required and kept), **Save as pending**. Bulk
publish exists for a run already read through; it is not the default.

The quote is editable only to repair an OCR artefact, and editing it re-runs the verbatim
check and recomputes `quote_sha1`. What a community said cannot be quietly rewritten.

**The form** is the same change form with the document fields empty: type or paste the
statement, set language, pick the place, add codings, set `channel='manual'` and
`voice_type`. The verbatim check is skipped — there is no document to check against — and
`method` records `manual`. The author is the reviewer, so Save publishes directly; there is
no second gate to pass through one's own typing.

The form is therefore also the fallback for everything the AI cannot reach: a WhatsApp
message from a field team, a note from a coordination meeting, a quote read over the phone.

## 10. The API

`/api/insights/` in the new app, returning **published rows only**.

Filters: `voice_type`, `iso3`, `dimension`, `tag`, `admin_pcode`, `from`, `to`, `q`.
Each row carries quote, translation, language, voice type, place, `match_method`,
`stated_on`, codings, `lat`/`lon`, and the source document where there is one.

This is the one dashboard panel that reads PostgreSQL live. The map layers keep reading
their pre-built files in `dashboard/data/`, so nothing about map performance changes, and
Publish means published: refresh and it is there.

`/api/community-insights/` is unchanged (§5.6).

## 11. The dashboard

The Community Insights panel already exists — `renderVoices` at `app.js:1720`, its search
box wired at `initVoiceSearch` (`app.js:2808`), fed by `tags.json` snippets. Everything it
shows today is `secondary_analysis`. This is a change to an existing panel.

### 11.1 Three tabs

`Community` · `Analyst` · `Both`, above the search box.

- **Community** — published insights with `voice_type='community'`, and nothing else. Its
  emptiness in a given month is itself a finding worth seeing.
- **Analyst** — the existing regex snippets from `tags.json`, plus published insights
  marked `secondary_analysis`. Same kind of thing; one list.
- **Both** — the union, each card labelled so the reader always knows which they have.

**Search is scoped to the active tab.** Typing with Community selected never returns an
analyst passage. The existing behaviour — empty box shows the current month, a search
widens to the whole archive — is kept; it exists because any single month holds only a
handful of quotes.

### 11.2 The cards

A community card carries the **full statement**, not the truncated `"…snippet…"` form the
panel uses now — the whole point is that the words are read entire. Place, date, dimension
chips in the existing `DIM_META` colours, and the source document where there is one. A
French statement shows the original with the translation beneath. Clicking a search result
moves the timeline to that month, as it does now.

### 11.3 The map layer

Every published insight whose place resolved gets a **quote bubble** at its point.
Insights with no traceable location are simply not mapped; the panel shows a count of them
so the reader knows what the map is not showing.

**Filtered by the same theme selection as everything else.** `state.activeTags`
(`app.js:151`) is one flat set of `"dimension|tag"` keys shared by the map layers and every
panel, and `app.js:1632` states the rule outright: both filters must be applied in one
place *"or those panels drift apart from the map."* The bubble layer reads
`activeTagsIn(dim)` and the country filter exactly as `monthTagTotals` does. Tick the
flooding hazard and only flood-tagged insights remain, on the map and in the panel
together. One filter, four consumers.

The three tabs filter the bubbles as well as the cards, so selecting Community gives a map
of community voice alone.

**The bubble.** A small marker in its dimension's colour, **not sized by anything** — a
single quote is not a quantity, and sizing it would imply one. Several insights at one
point cluster into a marker with a count. Clicking opens the full statement in a popup and
highlights the matching card in the panel, so map and panel are tied in both directions.

**Honest placement.** Where a place matched to a district rather than a settlement, the
bubble sits at the district's label point and the popup says so — *"located to Afar
(region)"* — rather than implying anyone stood at that coordinate. `match_method` already
records the difference; this surfaces it. The same care `HumanitarianServicePoint` takes
in its docstring about not reading its dots as building locations.

## 12. Verification

1. **Migrations apply and the pipeline is unaffected.** `migrate`, then a full
   `run_pipeline`; row counts in `narrative_tags`, `population_figures`, `movement_flows`
   and `events` change exactly as they did before, and no `insights` row is touched.
2. **The verbatim gate rejects an invented quote.** Hand-write a payload whose quote is not
   in the page text; the loader rejects it, `insights_rejected_unverifiable` increments, and
   no row is created.
3. **The conflict rule protects a reviewer.** Load a payload, edit and publish an insight,
   re-load the same payload; the row is unchanged and `insights_skipped_reviewed` is 1.
4. **Off-vocabulary tags degrade.** A payload proposing `hazard/locusts` yields `tag='other'`,
   `tag_raw='locusts'`, flagged in review.
5. **Unmatched places are accepted.** A payload naming a place absent from `admin_areas`
   loads with `match_method='unmatched'` and null `lat`/`lon`, and is not mapped.
6. **Duplicate manual entries collide.** Two identical hand-typed insights — both with null
   `document` and `page` — are rejected by `uniq_insight_quote`. This is what
   `nulls_distinct=False` is for.
7. **Only published rows leave the API.** A pending insight is absent from
   `/api/insights/`; publishing it makes it present without any pipeline run.
8. **The pipeline cannot see uploaded documents.** After intake, `s02_extract_text` reports
   zero documents to process for them and logs no error.
9. **Tab-scoped search.** With Community selected, a term appearing only in an analyst
   snippet returns nothing.
10. **The map filter agrees with the panel.** With only `hazard|flooding` ticked, the
    bubbles on the map and the cards in the panel are the same set.

## 13. How sub-projects 2 and 3 fit

**Sub-project 2, the MCP channel, is mostly documentation.** `.mcp.json` is correct and
working; the missing piece is `CLAUDE.md` / `AGENTS.md` (§6.1), extended to cover which MCP
server answers which question, where a pull is saved in `mcp_cache/`, which `load_external`
loader consumes it, and how to check the result with `external_status`. The plumbing is
already built and already says so: `external_data/loaders/base.py` separates fetching from
loading precisely because *"the assistant pulls through MCP today and something else might
fetch the same JSON tomorrow."* The insights contract is that pattern applied to a second
kind of payload.

**Sub-project 3, primary collection, is unblocked by this design and not started by it.**
`Insight.channel` already has a `primary` value and `document` is already nullable, so
primary-collected statements write to this table and appear in this panel with no
migration. A Kobo path already exists — `load_hsps` reads Kobo exports and a Kobo MCP is
available. The real work is form design and a consent question, and neither belongs here.

## 14. The updater, and one thing left broken

**Keep the updater.** It is not replaced by any of this. Its job is running the seven-step
pipeline that builds every map layer, with a progress bar over a slow PDF-extraction step.
The insights channel catalogues documents and loads payloads — different work, different
tables, and deliberately out of the pipeline's way.

What overlaps is narrower: both screens now watch a long job and stream progress. So the
question after Phase 1 is not *keep or drop* but *should these be one operations page*, and
the criterion is: **once the insights channel has run on a real folder, if the updater is
opened only to re-run the pipeline after loading insights, merge them; if the two are used
for genuinely separate work, leave them apart.** Decided on use, not in advance.

**Left broken, deliberately and on the record:** `s04_events` deletes every row in `events`
— including the curated milestones its own docstring describes as hand-checked — and
rebuilds them from a literal Python list. `Event.source='curated'` protects nothing. It is
the same trap this design avoids for insights, still live in the timeline, and it is out of
scope here.

## 15. Known limits, stated rather than discovered later

- **The verbatim gate cannot catch a true quote used misleadingly.** A model can lift a real
  sentence and code it wrongly. That is what human review is for; the gate only guarantees
  the words are real.
- **`voice_type` is a judgement, and models will get it wrong.** A report paraphrasing what
  people said sits genuinely between the two categories. The reviewer decides, and the field
  is prominent in the form for that reason.
- **`stated_on` is usually the report date, not the date of speaking.** A March report may
  quote a January conversation. The column means "the best date we have", and where a source
  gives the real one, a reviewer can correct it.
- **Place resolution is only as good as the boundary library.** Camps, informal settlements
  and neighbourhoods will not match; they land `unmatched` and stay off the map. That is
  correct behaviour, not a gap to paper over.
- **The Analyst tab mixes durable and rebuilt content.** Published `secondary_analysis`
  insights persist; the `tags.json` snippets beside them are rebuilt by `s03_parse` on every
  pipeline run. An analyst snippet found by search last week can be absent after the next
  "Update now" — not deleted, simply no longer matched. Community-voice content is never
  affected, because none of it comes from `tags.json`.
- **A slightly reworded quote on re-run creates a second row, not a skip.** The natural key
  hashes the quote, so a model that drops a comma the second time produces a new pending
  insight beside the reviewer's published one, and `insights_skipped_reviewed` does not
  increment. This is the conflict rule working — the published row is protected, which is the
  point — but it looks like a duplication bug the first time it is seen. The reviewer rejects
  the near-duplicate.
- **The panel mixes two evidence standards in the Both tab.** A regex-matched analyst
  sentence and a human-reviewed community quote appear in one list. They are labelled, and
  the tabs exist so they can be separated, but the Both tab is a convenience with a real
  cost.
- **Two identical hand-typed quotes are treated as one.** The natural key is
  `(document, page, quote_sha1)`, and a manual entry has null `document` and `page`, so the
  quote text alone distinguishes it. Two communities saying exactly the same sentence, word
  for word, would collide and the second would be rejected. Deduplication is the more useful
  default and the collision is vanishingly unlikely on real statements, but it is a real
  loss and not a validation bug — a reviewer who hits it should extend one quote to its full
  context rather than work around the constraint.
- **`insights` and `/api/community-insights/` will confuse someone.** §5.6 records why and
  what the exit is.
- **No throughput estimate is offered for Phase 2.** Cost and speed per document depend
  entirely on the provider chosen, and guessing here would be worse than measuring once the
  adapter exists. `ExtractionJob` records what is needed to measure it.
