# External data in the database: subject tables, watermarks and incremental pulls

**Date:** 2026-09-09
**Status:** approved design, not yet implemented
**Scope:** sub-project A of four. B (multi-country seasonal + food security), C
(drag-to-resize sidebars) and D (frontend onto the boundary API, with GO SharePoint
ADM1/ADM2 and zoom-progressive outlines) each get their own spec and are **out of scope
here**.

## 1. Why

Every external humanitarian layer on this dashboard is pulled through an MCP server by the
assistant, dropped into `data_pipeline/mcp_cache/` as a JSON file, and flattened by
`data_pipeline/steps/s06_mcp_layers.py` into files under `dashboard/data/`. Three things
follow from that, and all three are problems.

**The data never reaches the database.** PostgreSQL holds the PDF corpus — documents, page
text, figures, flows, tags, events — and, since last week, the boundary library. It holds
nothing at all from HDX, IPC, FEWS NET or UNHCR. An analyst who opens the database in Power
BI or DBeaver can see what the UNHCR reports said and cannot see a single IPC phase.

**Every refresh is a fresh pull.** Nothing records what has already been fetched, so
re-running a refresh re-downloads data the project already has. This is not a small cost:
IPC country geometry runs 8–15 MB per pull, and on the 2026-07-06 refresh requesting two
countries in parallel closed the IPC MCP connection and took that server down for the rest
of the session. Repeating work that has already been done is exactly how that happens.

**Some of it was never pulled at all.** `SEASONAL`, `REF_COUNTRIES` and `CROSSINGS` in
`s06_mcp_layers.py` are hand-typed Python dictionaries. The seasonal calendar in particular
is documented as coming from "FEWS NET `get_seasons`" but is five literal bands somebody
typed for Sudan. The API has real, structured season data for Sudan and its neighbours, and
the dashboard has never seen it.

## 2. Goals

1. Persist external data in PostgreSQL in **subject-named tables** — Seasonal Calendar,
   Food Security (IPC), Movement Patterns, Community Insights — with the originating source
   recorded as a column rather than baked into the table name.
2. Record, per source × dataset × country, what is already held and how fresh it is, so a
   refresh pulls **only what is missing or newer**.
3. Make the data queryable directly — SQL, Power BI, Excel — through both the tables and a
   read-only JSON API.
4. Change `s06_mcp_layers.py` to read the database instead of `mcp_cache/`, with the
   dashboard's output files equivalent to what they are now, so nothing on screen changes
   yet.

## 3. Non-goals

- **No new fetching mechanism.** MCP tools remain callable only by the assistant in Claude
  Code on the host, exactly as `MAINTENANCE.md` §4 and `updater/views.py` already state.
  Django does not gain HTTP clients, API keys or a scheduler. This was an explicit choice;
  a scheduled REST fetcher is a possible later sub-project, and the loader is designed not
  to care who produced the JSON it is handed.
- **No new countries on screen.** Chad, South Sudan, Ethiopia and CAR gain rows in the
  tables; showing them is sub-project B.
- **No frontend change.** No sidebar, map, boundary or theme work here.
- **No GeoDjango.** Geometry columns are added by raw SQL migration and read by raw SQL,
  following the pattern `boundaries/models.py` established and for the reason it gives:
  GDAL in the web image buys nothing this project needs.
- **No merging of API figures with PDF figures.** See §5.5.

## 4. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Table naming | **Subject, not source** — `seasonal_calendar`, `food_security`, `movement_patterns` | The user's framing: "if ACAPS pulls Seasonal Calendar information then in the database I see Seasonal calendar". Sources vary per row and are a column. |
| Where they live | **New app `external_data`** | Third app beside `data_track` (corpus) and `boundaries` (geography). Keeps migrations and ownership clean. |
| Cache role | **Staging, not truth** | `mcp_cache/` becomes the drop-box between the host pull and the loader. The database is the source of truth. Caches stay on disk as a replay buffer. |
| Incrementality | **Two strategies** — date watermark, and identity diffing | Not every source supports date filtering. §6. |
| Geometry | **PostGIS columns via raw SQL**, simplified `geom_web` alongside full `geom` | Same as `admin_areas`. IPC polygons are drawn on the web and must be small. |
| API vs PDF figures | **Separate tables** | Different provenance measuring overlapping quantities. Merging them would silently double-count displacement. |
| Community Insights | **A SQL view, not a table** | The quotes already exist as `narrative_tags.snippet`. A second copy would drift. |
| Hardcoded dicts | **Seeded into tables once, then deleted from code** | `SEASONAL` is replaced by a real FEWS NET pull; `REF_COUNTRIES` and `CROSSINGS` are seeded as curated rows. |

## 5. Data model

New app `external_data`. Django models for every column except geometry, which migration
`0002` adds in raw SQL exactly as `boundaries/migrations/0002_geometry_columns.py` does.

Five tables — `source_sync`, `seasonal_calendar`, `food_security`, `movement_patterns` and
`border_crossings` (§8, curated points with no API behind them) — plus the
`community_insights` view.

### 5.1 `source_sync` — the bookkeeping table

The table that makes goal 2 real. One row per thing that can be pulled.

| Column | Type | Notes |
|---|---|---|
| `source` | text | `fewsnet` / `ipc` / `hdx` / `unhcr` / `acaps` |
| `dataset` | text | `seasonal_calendar` / `food_security` / `idps` / `refugees` |
| `iso3` | char(3), null | null for a global pull |
| `tool` | text | the MCP tool called, e.g. `get_areas_by_analysis` |
| `variant` | text | which slice of the dataset this row tracks, e.g. `admin2-overview` vs `admin1` |
| `params` | JSONB | the last call actually made, for reproducibility — **not** part of identity |
| `last_pulled_at` | timestamptz | |
| `high_water_date` | date, null | latest **data** date held — not the pull date |
| `known_ids` | JSONB | identities already held (e.g. IPC analysis ids). §6.2 |
| `row_count` | integer | rows currently in the subject table from this pull |
| `notes` | text, null | e.g. "source publishes annually, latest 2024" |

Unique on `(source, dataset, iso3, variant)`.

**Identity must not include the call's arguments, and this is load-bearing.** The obvious
design — digest `params` into the unique key — destroys the mechanism it exists to serve:
`start_date` is itself one of the arguments, so every incremental pull would hash
differently, create a fresh row, and leave §6.1 with no accumulated watermark to read. The
row identifies *a thing that can be pulled*, not *a pull*. `variant` distinguishes genuinely
different slices (IDPs at admin1 and at admin2 are two rows); date windows, page offsets and
result limits are never part of identity.

`high_water_date` and `last_pulled_at` are deliberately different columns. A pull that
returns nothing new still advances `last_pulled_at` and must not advance
`high_water_date` — that distinction is what stops a no-op refresh from looking like fresh
data. The 2026-07-06 refresh found HDX IDP data topping out at 2025-12-31, IPC Sudan at Feb
2026 and UNHCR refugees at 2024; those ceilings belong in `notes`.

### 5.2 `seasonal_calendar`

| Column | Type | Notes |
|---|---|---|
| `iso3`, `country_name` | char(3), text | |
| `admin_pcode` | text, null | null for a national calendar; ACAPS publishes at admin-1 |
| `source` | text | `fewsnet` / `acaps` / `curated` |
| `source_ref` | text | FEWS NET `fnid`, or the ACAPS record id |
| `label` | text | "Lean", "Main harvest", "Post-harvest" |
| `season_type` | text | `Lean` / `Harvest` / `Dry` / `Rainy` |
| `purpose` | text | FEWS NET's `NutritionIndicator` / `CropProductionIndicator` |
| `start_month`, `end_month` | integer | 1–12; wraps when `end < start` (Chad's cold off-season is Nov–Feb) |
| `alignment` | text, null | FEWS NET's `Start` / `End` |
| `description`, `aliases` | text, JSONB | aliases are free multilingual synonyms — "soudure" for lean |
| `display_order` | integer | the source's own ordering |

Unique on `(source, iso3, admin_pcode, purpose, label)`.

**No colour column, and that is deliberate.** The current `SEASONAL` dict carries a hex
colour per band and `renderSeasonal` reads `it.color` — but FEWS NET returns none, so a
colour column would be null for every real row and the calendar would render grey. Colour is
presentation, derived at build time from `season_type` (lean, harvest, dry, rainy) so that
the same kind of season is the same colour in every country. `build_seasonal` owns that
mapping.

**De-duplication is required at load.** FEWS NET returns the same season once per historical
geographic-unit version: Chad's `get_seasons` gives 15 rows for roughly 6 distinct seasons,
repeated under `fnid` values `TD`, `TD1960A0`, `TD2008A0`, `TD2012A0`. The loader keeps only
rows where `unit_type` is `Admin 0` **and** `fnid` equals the plain country code, discarding
the historical versions. Without this the calendar renders each band three times.

### 5.3 `food_security`

| Column | Type | Notes |
|---|---|---|
| `source` | text | `ipc` / `ch` / `fewsnet` — see below |
| `analysis_id`, `analysis_title` | text | IPC's own identifiers |
| `condition` | char(1) | `A` acute, `C` chronic |
| `iso3` | char(3) | |
| `period_date` | date | first day of the period the row describes |
| `period_type` | text | `current` / `projection` / `second_projection` |
| `area_id`, `area_title` | text | IPC's analysis unit, which is **not** an admin unit |
| `admin_pcode` | text, null | best-effort spatial join to `admin_areas`; null when no confident match |
| `phase` | integer | overall IPC phase 1–5 |
| `phase3plus_pct` | float | phases 3+4+5 combined |
| `phase1_population` … `phase5_population`, `total_population` | bigint, null | |
| `colour` | text | IPC's own phase colour, so the map never invents one |
| `geom`, `geom_web` | PostGIS, raw SQL | full and simplified |

Unique on `(source, analysis_id, period_type, area_id)`.

**FEWS NET and IPC are different products and must not be conflated.** The IPC MCP serves
official IPC and Cadre Harmonisé analyses; FEWS NET's `get_ipc_classifications` are FEWS
NET's own IPC-compatible assessments. Both are legitimate, both land here, and the `source`
column keeps them apart. Chad's analyses are Cadre Harmonisé (`source='ch'`) on the same
five-phase scale, so they compose with Sudan's cleanly.

**IPC areas are not admin areas.** IPC redraws its analysis units per round, which is why
the existing `ipc_areas_fs.geojson` carries one full snapshot per period. The geometry is
therefore stored as IPC published it; `admin_pcode` is a convenience join, populated where a
polygon confidently matches one in `admin_areas` and left null otherwise. Nothing depends on
it being complete.

### 5.4 `movement_patterns`

Long format, one row per place per date per metric — the shape trend analysis wants.

| Column | Type | Notes |
|---|---|---|
| `date` | date | |
| `iso3`, `admin_pcode`, `admin_level`, `place_name` | | `admin_pcode` null for national totals |
| `metric` | text | `idps` / `refugees` / `returnees` / `asylum_seekers` |
| `population_group` | text, null | |
| `value` | bigint | |
| `unit` | text | `individuals` / `households` |
| `source`, `source_dataset` | text | `hdx` + `iom-dtm`; `unhcr` + `get_refugees`; `excel` + the workbook name |
| `reference_period_start`, `reference_period_end` | date, null | DTM reports periods, not instants |
| `lat`, `lon` | float, null | for sources that carry a point rather than a p-code |

Unique on `(source, metric, iso3, admin_pcode, date, population_group)`.

**Excel is a first-class source here, not an afterthought.** `s07_xlsx.py` reads two
workbooks an analyst maintains by hand beside the PDFs — `neighbouring countries Pop
movement data.xlsx` and `Sudan IDPs.xlsx` — and they carry the *freshest* movement data the
project holds: a 2026 biweekly refugee series, against UNHCR's annual figures that stop at
2024, plus Sudan's admin1 IDP snapshots that no MCP layer produces at all. Both load into
`movement_patterns` with `source='excel'` and the workbook in `source_dataset`, and both get
`source_sync` rows keyed on file `sha1` and modification time rather than a date watermark.

This is the case the user's phrase "Movement Patterns … IDPs, Refugees" most directly names,
and leaving it in a spreadsheet would have left the newest numbers outside the database the
whole design exists to fill.

### 5.5 What this table is **not**

`data_track.PopulationFigure` and `data_track.MovementFlow` hold displacement numbers read
out of UNHCR PDFs, each with the sentence that produced it. `movement_patterns` holds the
same *kinds* of quantity from the agencies' own APIs. They overlap and they disagree,
because a UNHCR situation report and IOM DTM count different things on different dates.

They stay in separate tables. An analyst who wants both writes a `UNION` and chooses what
that means. A single merged table would produce plausible, wrong totals that nobody could
trace back — which is the failure mode this project's whole evidence trail exists to
prevent.

### 5.6 `community_insights` — a view

Created by `RunSQL` in a migration, not a table:

```sql
CREATE VIEW community_insights AS
SELECT t.id, t.report_date, t.dimension, t.tag, t.country,
       t.area_id, t.area_name, t.area_level,
       t.snippet AS quote,
       d.file_name AS source_document, d.family, d.rel_path
FROM narrative_tags t
LEFT JOIN documents d ON d.id = t.document_id
WHERE t.snippet IS NOT NULL AND t.snippet <> '';
```

This gives the user the named object they asked for, in the database, with zero duplication
and no possibility of drift. It also makes the quotes reachable from Power BI without anyone
learning the `narrative_tags` schema.

### 5.7 Relationship to the boundary library

`admin_pcode` columns are plain text, **not** foreign keys. `admin_areas` is unique on
`(source, kind, level, pcode)`, so a p-code alone does not identify one row — the same
p-code can legitimately appear from two publishers. Joins resolve on `(iso3, level, pcode)`
and are the caller's decision. This is recorded here so nobody later "fixes" it by adding a
constraint that cannot hold.

## 6. How incremental refresh actually works

Two strategies, because the sources differ. Both are driven by `source_sync`, and the
assistant reads it **before** pulling.

### 6.1 Date watermark — where the API filters by date

HDX IDP series. The assistant reads `high_water_date` for `(hdx, idps, SDN)`, passes it as
`start_date`, and receives only newer rows. If nothing comes back, `last_pulled_at` advances
and `high_water_date` does not.

### 6.2 Identity diffing — where it does not

IPC has no date filter. `list_analyses` is a small, cheap call returning analysis ids;
comparing that list against `known_ids` says exactly which analyses are missing, and only
those are fetched. This matters because the fetch is the expensive part:

> **Recorded from the 2026-07-06 refresh:** IPC `get_areas` whole-country GeoJSON is 8–15 MB
> per country, and requesting two in parallel returned `-32000 Connection closed` and took
> the IPC MCP server down for the remainder of the session.

So food-security pulls are **strictly one country at a time**, and identity diffing is what
keeps that sequential work from being repeated. FEWS NET seasons are diffed the same way;
they change rarely and re-pull only on demand.

**Analyses before 2023-01 are not pulled.** Chad alone has twelve analyses back to 2020, and
at 8–15 MB each, strictly sequential, pulling every one for four countries is hours of work
for data the dashboard cannot show: the timeline starts at `CRISIS_START`, 15 April 2023.
The cap is a decision, not an oversight, and it is recorded in `source_sync.notes` so a
later reader can tell a deliberate floor from a failed pull.

### 6.3 What the assistant is told to do

`python manage.py external_status` prints the same information `/api/sync/` serves: per
source × dataset × country, what is held, its latest data date, and what is missing. This is
the first command of any refresh, and `MAINTENANCE.md` §4 is rewritten around it.

## 7. The loader

```
python manage.py load_external <dataset> <file.json> [--iso3 TCD] [--dry-run]
```

One command, one dataset argument selecting a parser. Each parser is a small module in
`external_data/loaders/` exposing `parse(payload) -> list[dict]` plus a natural key, so a new
source is a new file and not a change to the command.

Required properties:

- **Idempotent.** Upsert on the natural key. Loading the same file twice must produce an
  identical table and identical `row_count`. This is tested, not assumed.
- **Transactional.** One dataset load is one transaction; a malformed record aborts the whole
  file rather than half-loading it.
- **Writes `source_sync` last**, inside that transaction, so the watermark can never claim
  data the tables do not have.
- **Refuses silently-empty payloads.** An MCP error serialised as `[]` must be reported as a
  failed load, not recorded as "up to date". This is the failure mode most likely to make the
  whole design lie to its user.
- **`--dry-run`** reports what would change and writes nothing.

## 8. Seeding what is currently hardcoded

A one-time `python manage.py seed_external`:

| Source | Becomes | Then |
|---|---|---|
| `SEASONAL` (Sudan, hand-typed) | seeded with `source='curated'` | **replaced** by a real FEWS NET `get_seasons` pull for SDN; the curated rows are deleted once the pull verifies |
| `REF_COUNTRIES` | `movement_patterns`, `metric='refugees'`, `source='unhcr'` | matches the source as of 2024, its latest annual release |
| `CROSSINGS` | new small table `border_crossings` | genuinely curated geography, no API behind it; keeps `source='curated'` permanently |

After seeding, these three dictionaries are **deleted** from `s06_mcp_layers.py`. Leaving
them in place as a fallback would guarantee that one day the code path nobody watches is the
one serving the dashboard.

## 9. The API

New read-only endpoints in `external_data/views.py`, mounted at `/api/`, following the
conventions `data_track/views.py` already established — plain `JsonResponse`, GET only,
capped result sets, filters as query parameters.

```
/api/seasonal/?iso3=TCD
/api/food-security/?iso3=TCD&period=2025-11-01
/api/movement/?iso3=SDN&metric=idps&from=2024-01-01
/api/community-insights/?dimension=hazard&q=flood
/api/sync/
```

`/api/sync/` is the one that changes how the project is operated: it is what the updater page
renders, and what tells an analyst which pull to ask the assistant for.

The `/api/` index is extended to list them, so the API stays self-describing in a browser.

## 10. `s06_mcp_layers.py` and `s07_xlsx.py` read the database

The step keeps its name, its outputs and its place in the pipeline. Each `build_*` function
swaps its `json.loads((CACHE / ...).read_text())` for an ORM query. `build_seasonal` gains a
country loop and writes `{iso3: {...}}` instead of a bare Sudan object — the only output
whose *shape* changes, and it changes now so sub-project B is a frontend change alone.

**`s07_xlsx.py` moves with it, and must.** s07 runs after s06 and *rewrites*
`refugee_camps.json`, merging its 2026 biweekly Excel series into the file s06 just
produced; it also writes `idp_states.json`, which s06 never touches. If s06 alone were
moved onto the database, step 7 would silently overwrite it on the very next pipeline run
and the work would appear to revert for no visible reason. So s07 also loads into
`movement_patterns` (§5.4) and rebuilds its two outputs from there, and the two steps stop
writing the same file from different sources.

`data_pipeline/steps/_build_aoi_ipc.py` is fixed in this pass. It currently reads IPC pulls
from `TOOLRES`, a hardcoded path pinned to a Claude session from June, so it silently reads
stale data or nothing at all depending on what still exists on disk. It moves onto
`food_security` like everything else, and the pinned path is deleted.

## 11. The updater page

`updater/views.py` derives external-layer freshness from file modification times. It moves to
`source_sync`, and the page gains, per dataset × country: last pulled, latest data date held,
and whether a newer analysis or period is known to exist. The "Rebuild external layers from
latest cache" button becomes "Rebuild external layers from the database".

## 12. Verification

Each of these is a command with an expected result, run before the sub-project is called
done.

1. **Migrations apply on the live volume.**
   `docker compose exec web python manage.py migrate` — clean, and `\dt` shows the five new
   relations plus the view.
2. **Loader is idempotent.** Load a fixture twice; assert identical row counts and identical
   `source_sync.row_count`. Automated test.
3. **Empty payload fails loudly.** Load a fixture containing `[]`; assert a non-zero exit and
   that `source_sync` is unchanged. Automated test.
4. **Watermark advances correctly.** Load month 1, then months 1–2; assert `high_water_date`
   moves once and `row_count` reflects the union, not the sum. Automated test.
5. **FEWS NET de-duplication.** Load the real Chad `get_seasons` payload (15 rows); assert 6
   rows stored, none with a versioned `fnid`. Automated test.
6. **`s06`/`s07` output is equivalent — checked semantically, not by diff.** A byte diff
   cannot pass and must not be the gate: PostGIS `ST_Simplify` does not round coordinates
   the way `_simplify` does, p-code centroids from `admin_areas` are not the name-matched
   geoBoundaries centroids `build_idp_localities` uses today, and `seasonal.json` changes
   substantively because Sudan's hand-typed bands are replaced by the real FEWS NET pull
   (§8). Setting an impossible gate here would guarantee somebody skips it. Instead, assert
   on the rebuilt files: the same number of IPC periods and the same feature count per
   period; the same phase for every area title present in both; the same locality names and
   values in `idp_localities.json`; the same country totals in `refugee_camps.json`
   including the 2026 Excel series; and `idp_states.json` unchanged in state count.
7. **Real refresh round-trip.** `external_status` → pull only what it names → load →
   `external_status` again shows the new high-water mark. Run against Chad, which has
   genuinely new data.
8. **The database answers a real question.** In DBeaver, join `food_security` to
   `admin_areas` and return Chad's ADM2 units at phase 3+ for the November 2025 analysis.
   Confirms goal 3 with the tool the user will actually use.

## 13. Sequencing

1. App skeleton, models, migrations (including geometry columns and the view).
2. `source_sync` + `external_status` command — the bookkeeping before anything writes.
3. Loader framework + the seasonal parser (smallest real source), with its tests.
4. Remaining parsers: food security, movement patterns (MCP sources and the two Excel
   workbooks).
5. `seed_external`, then delete the three dictionaries.
6. Pull Chad, South Sudan, Ethiopia and CAR — one country at a time for IPC.
7. `s06` and `s07` read the database; verification item 6.
8. API endpoints; updater page onto `source_sync`.
9. `MAINTENANCE.md` §4 rewritten around `external_status`.

Steps 1–4 are the foundation and are worth doing test-first; the parsers are pure functions
over recorded fixtures, which is the easiest possible thing to test well.

## 14. Rollback

Every change is additive until step 5. Steps 1–4 create new tables nothing reads; the
dashboard is unaffected and rollback is dropping them.

Step 5 deletes code, and step 7 changes what `s06` reads — the first genuinely irreversible
points. Both are guarded by verification item 6, which compares the dashboard's output files
before and after. `mcp_cache/` is left on disk throughout, so any load can be replayed
without re-pulling from a single MCP server.

## 15. Known limits, stated rather than discovered later

- **Coverage is uneven and the tables will show it.** Verified on 2026-09-09: Egypt and Libya
  return **no IPC analyses at all**, Libya's FEWS NET seasons are a single placeholder
  "Annual" band, and Egypt has crop seasons but no lean season. These are real absences, not
  load failures, and sub-project B must render them as such.
- **Uganda's IPC coverage is Karamoja-only**, which does not include Kiryandongo where the
  Sudanese caseload is. Recorded from the previous refresh.
- **CAR and Uganda AOI phases were never pulled**, so their grey on the current AOI layer is
  a missing pull rather than a confirmed absence. Pulling them is step 6.
- **Source ceilings as of 2026-07-06:** HDX IDP admin2 ends 2025-12-31; UNHCR refugees are
  annual to 2024. Loaded into `source_sync.notes` so `external_status` explains a no-op
  refresh instead of looking broken.
- **New settings, if any, use `get(X) or default`** — an empty string in `.env` must fall
  through to the default, which `get(X, default)` does not do.
- **The `community_insights` view constrains future migrations.** Its migration must declare
  a dependency on `data_track`'s latest migration or a fresh `migrate` fails on ordering. And
  PostgreSQL refuses to drop or alter a column a view references: `narrative_tags` already
  gained columns in `0002` and `0003` and will again, so **any future migration touching
  `narrative_tags` must drop the view first and recreate it after**. Written here because
  the failure surfaces months later, in someone else's unrelated migration.
