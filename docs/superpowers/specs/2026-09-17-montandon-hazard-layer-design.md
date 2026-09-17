# IFRC Montandon hazard layer, and a hazard vocabulary from the IFRC codebook

**Date:** 2026-09-17
**Status:** design agreed, plan not yet written

## What this is for

Two things the office asked for, which turn out to be one piece of work:

1. **Pull hazard data from IFRC Montandon** for the countries of focus, over a
   fixed window that always starts 15 April 2023 and always ends today, behind a
   **Pull now** button on Admin → Model Context Protocol → Data sources.
2. **Split the dashboard's Hazard dropdown into Hazard and Sub-Hazard**, keyed to
   the IFRC hazard codebook, with the same categories recorded in the database on
   every table a hazard comes from.

They are one piece of work because both halves need the same answer to the same
question: *what are the hazard categories, and which hazard belongs to which one?*
Montandon events and document tags must share a vocabulary or the two dropdowns
cannot govern both.

Montandon is IFRC's disaster-event registry, published as a STAC API at
<https://montandon-eoapi-stage.ifrc.org/stac>. The codebook is *Hazard
definitions*, IFRC, 2021:
<https://www.ifrc.org/sites/default/files/2021-06/04-HAZARD-DEFINITIONS-HR.pdf>.

## What was found before designing

Recorded because each of these closed off an option that looked reasonable.

- **Country filtering needs POST.** Montandon's `GET /search` offers only `bbox`.
  Filtering by country means `POST /search` with a CQL2 filter,
  `{"op": "a_contains", "args": [{"property": "monty:country_codes"}, ["SDN"]]}`.
  Confirmed working, as are `fields` trimming and `token` pagination. The
  project's existing fetcher plumbing is GET-and-offset only.
- **`reference-events` is empty for Sudan.** Monty publishes a deduplicated
  canonical-event collection, which would have removed the need to dedupe
  ourselves. It returns zero rows for Sudan in this window, so events come from
  the per-source collections and correlation is ours to do.
- **The precise sources and the coarse ones are different sources.** GDACS, PDC
  and IDMC-IDU publish located points — IDMC-IDU down to
  *"Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026"*. EM-DAT, GLIDE
  and IFRC-GO publish the whole country polygon, which on a map means Sudan
  lights up entire.
- **UNDRR's clusters are not the IFRC codebook's categories.** Sudan's wildfires
  arrive as `nat-cli-wil-wil` / `EN0205` — *climatological* to UNDRR, but the
  IFRC codebook files wildfires under *Non-technological and man-made hazards*.
  Any design that parses the slug would silently disagree with the codebook this
  work is keyed to.
- **Most of the existing hazard tags have no codebook category.** Seven of the
  ten tags in the dropdown today are conflict or food-crisis tags, and the
  codebook explicitly excludes armed conflict from "man-made hazards".
- **`monty:country_codes` is not tight.** A Sudan-filtered query returned
  *"Flood - Kemashi, Benshangul-Gumaz, Ethiopia"*. Some rows will be neighbour
  events that Montandon tagged with Sudan.
- **Production Montandon is closed.** `montandon-eoapi.ifrc.org` answers 401 and
  wants IFRC GO OIDC credentials. Staging answers openly and is what this
  design uses.

## The vocabulary

`data_pipeline/hazard_codebook.json`, a new file beside `taxonomy.json` and in
the same spirit: data, read by three consumers, edited in one place.

Nine categories. The first seven are the codebook's own, with its headings and
its definitions quoted verbatim. The last two are this project's, and are marked
`in_codebook: false` so nothing can quietly present them as IFRC's:

| category | sub-hazards |
|---|---|
| Climatological hazards | Drought · Extreme heat / heat wave · Extreme cold / cold wave · *extreme_heat_drought* |
| Biological hazards | Biological emergency · Major epidemic and potential pandemic diseases · *disease_outbreak* |
| Geophysical hazards | Earthquakes · Landslide/debris flows · Tsunami · Volcanic eruption |
| Meteorological hazards | Tropical cyclones |
| Hydrological hazards | Floods · Storm surge · Hailstorms · *flooding* |
| Technological and man-made hazards | Man-made · Nuclear emergency · Radiological emergency · Chemical emergency |
| Non-technological and man-made hazards | Wildfires |
| **Conflict and violence** *(not in codebook)* | *armed_conflict · shelling_airstrikes · attacks_on_civilians · siege_blockade · looting_robbery · explosive_ordnance* |
| **Food insecurity and famine** *(not in codebook)* | *famine_food_crisis* |

Italics are this project's document tags; the rest are the codebook's sixteen
named hazards.

**A codebook hazard and a document tag about the same thing stay separate
sub-hazards**, which is why *flooding* sits beside Floods and *disease_outbreak*
beside Major epidemic. They are different evidence: Floods is a dated Montandon
event with a located point, *flooding* is a sentence somebody wrote in a report.
Merging them would make a filter that cannot distinguish "an agency recorded a
flood here" from "a document mentioned flooding here" — which is precisely the
distinction this platform keeps everywhere else, and the same reasoning that
keeps `MovementPattern` apart from `data_track.PopulationFigure`. Selecting the
**category** gets both; selecting a **sub-hazard** gets exactly one kind of
evidence.

**Why two extra categories rather than seven pure ones.** Six conflict tags and
one food-crisis tag are most of the hazard reporting in a Sudan dashboard, and
the codebook has nowhere to put them. Filing them as "uncategorised" would label
the largest group of hazards in the data as leftovers. They get named categories,
flagged as outside the codebook, so the codebook stays quotable as written and
nothing disappears from the filter.

**`extreme_heat_drought` stays one tag.** It spans two codebook hazards, but
splitting it means re-parsing every document in the corpus. It maps to
Climatological with its own sub-hazard label. Splitting it later is a
`taxonomy.json` change and a re-parse, not a change to this design.

The file has four parts:

```
categories[]   key, label, in_codebook, sub_hazards[]{ key, label, definition, source }
hip_codes{}    "EN0205" -> { category, sub }      keyed on the HIP code
tags{}         "flooding" -> { category, sub }    all ten document tags
```

`hip_codes` is keyed on the HIP code (`EN0205`) and **not** on the `nat-*-*-*`
slug, because that is exactly where UNDRR and IFRC disagree. The file records the
IFRC answer and says so in a comment. A code Montandon sends that the table does
not hold lands in `uncategorised` and is logged. It is never guessed at.

### Why a file and not a table

Considered and rejected: two seeded tables (`hazard_category`, `hazard_type`)
with foreign keys from `narrative_tags` and the events table. The dashboard is
static JSON, so the join would only ever run at build time — a relational model
paid for and a file's worth of use got out of it. Worse, it would put curated
rows one foreign key away from a table `s03_parse` truncates on every run.

Also rejected: deriving categories from Montandon's own slugs. See the wildfire
finding above.

## The data

### `HazardEvent`, new, in `external_data/models.py`

Subject-named like its neighbours, so a second event source could load into it
later.

| column | note |
|---|---|
| `source` | always `montandon` — see below |
| `collection` | `gdacs` / `pdc` / `idmc-idu` — which Montandon collection published it |
| `event_id` | Montandon's STAC item id |
| `corr_id` | `monty:corr_id` — ties the same real flood across sources |
| `iso3` | one row per country per item |
| `event_date`, `end_date` | `start_datetime` / `end_datetime` |
| `title` | the item title |
| `hazard_codes` | the raw list as published, JSON, so the mapping is auditable |
| `hazard_category`, `hazard_sub` | stamped from the codebook at load time |
| `lat`, `lon` | all three chosen sources publish points |
| `admin_pcode`, `admin_level`, `match_method` | where the point resolved to; `match_method` is `point-in-polygon` or `unmatched` |
| `source_url` | the STAC item link |

The place is not stored separately. Montandon writes it into the title
(*"Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026"*) in a shape that
varies by source, so `title` is kept verbatim and `admin_pcode` is the parsed,
checkable answer. Inventing a `place_name` column would mean three sources' worth
of title-parsing to fill it, with nothing depending on the result.

**`description` is dropped and never stored.** One Montandon item carries
kilobytes of Word-exported HTML. It is excluded in the request's `fields` and
never reaches the database.

**No PostGIS columns.** All three chosen sources publish points, so `lat`/`lon`
are sufficient, exactly as on `BorderCrossing` and `MovementPattern`. This
removes the raw-SQL geometry migration that `FoodSecurityArea` needed.

**`source` is `montandon` on every row, and the publisher goes in `collection`.**
This is not cosmetic. `loaders/base.load()` finishes by computing
`sync.row_count = model.objects.filter(source=..., iso3=...).count()` from the
**sync key**, which is `source='montandon'`. Writing `gdacs` into `source` would
make that count zero forever, and the admin would report "0 rows" after every
successful pull. Every existing table already follows this convention —
`SeasonalCalendar.source` is fewsnet/acaps, `MovementPattern.source` is
hdx/unhcr/excel — and it is the publisher of the *payload*, not of the individual
record.

**The natural key is `(collection, event_id, iso3)`.** One Montandon item can
carry two countries — an observed wildfire had `["ETH", "SDN"]`. With `iso3`
outside the key, pulling Chad after Sudan would silently rewrite Sudan's row. One
item spanning two focus countries becomes two rows, which is also what makes a
per-country **Pull now** button honest.

**`match_method`** mirrors `HumanitarianServicePoint`'s column and exists for the
same reason: a point that falls in no polygon is kept as `unmatched` and draws
nothing, and the column is what tells you afterwards which events never placed.

### `NarrativeTag` gains `hazard_category` and `hazard_sub`

Stamped by `s03_parse.py` from the same file, null for the non-hazard dimensions.
Derived at parse time, never curated in the table — `s03_parse` deletes and
rebuilds `narrative_tags` on every run, so nothing hand-entered there survives.

## The fetch

`external_data/fetchers/montandon.py` — `source="montandon"`,
`dataset="hazard_events"`, `variant=""`, `requires=()`.

`plan(sync)` yields **one Call per press**: a single POST to `/search` carrying
all three collections, the fixed window and this row's country.

```python
{"collections": ["gdacs-events", "pdc-events", "idmc-idu-events"],
 "datetime":    f"{WINDOW_START}T00:00:00Z/{today}T23:59:59Z",   # 2023-04-15 -> today
 "filter":      {"op": "a_contains",
                 "args": [{"property": "monty:country_codes"}, [sync.iso3]]},
 "fields":      {"include": ["id", "collection", "bbox", "geometry",
                             "properties.title", "properties.datetime",
                             "properties.start_datetime", "properties.end_datetime",
                             "properties.monty:hazard_codes",
                             "properties.monty:country_codes",
                             "properties.monty:corr_id"],
                 "exclude": ["properties.description", "assets",
                             "properties.keywords", "stac_extensions"]}}
```

`since()` is **overridden to return `None`, always**. The office asked for the
whole window on every pull, so the inherited 90-day-lookback watermark behaviour
is deliberately switched off. `narrowed` is therefore always `False`, and under
the loaders' "empty is a failure" guarantee a country that genuinely returns
nothing fails loudly rather than being recorded as up to date. Egypt was checked
and has events; if this ever bites, a red chip saying so is the truthful answer.

The `fields` trim is not a nicety. It is what keeps a pull to a sane size on disk
and in `data_pipeline/mcp_cache/`.

### Three additions to `external_data/fetchers/base.py`

- `http_post_json(url, body, timeout)` — the POST twin of the existing helper,
  with the same `redact()` on the way out.
- `fetch_all_pages_token(url, body)` — STAC pages by a `token` handed back inside
  `links[rel="next"].body`, not by an `offset`. It follows that chain and returns
  one combined FeatureCollection, so the loader never knows paging happened —
  the same trick `fetch_all_pages` plays for HAPI.
- `fetch(call)` — one dispatcher: GET or POST, paged or not.

`Call` gains `method` (default `"GET"`) and `body`. The paginator follows from
the method, so there is no third flag to keep in step with `paginated`.

`refresh_external.py`'s loop loses its hardcoded
`from external_data.fetchers.hdx import fetch_all_pages` in favour of
`payload = base.fetch(call)`.

**`fetch_all_pages` stays in `hdx.py`.** `test_fetcher_hdx.py` patches
`external_data.fetchers.hdx.http_get_json` by name; moving the function would
break four passing tests for no gain. `base.fetch` imports it lazily, exactly as
the runner does today, so both patch targets keep working.

### The loader

`external_data/loaders/montandon.py` parses the FeatureCollection into
`HazardEvent` rows: one row per (item × focus country in `monty:country_codes`),
hazard codes mapped through the codebook, `description` dropped, `high_water()`
returning the newest `event_date`.

**`parse()` stays pure.** `loaders/base.py` documents it as *"Pure — no database
access"*, so the point-in-polygon resolution cannot happen there. `parse()` sets
`match_method='unmatched'` as the default, and the resolution is a **post-insert
raw-SQL pass inside `load()`'s transaction**, keyed on the natural key — the same
shape `_write_geometry` already uses, and for the same reason.

`Loader` therefore gains one optional hook, `after_insert(rows)`, called inside
`load()` after `bulk_create` and the geometry pass. Loaders that do not implement
it are unaffected. `MontandonLoader.after_insert` runs a single statement:

```sql
UPDATE hazard_events h
   SET admin_pcode  = m.pcode,
       admin_level  = m.level,
       match_method = 'point-in-polygon'
  FROM (SELECT DISTINCT ON (e.id) e.id AS event_id, a.pcode, a.level
          FROM hazard_events e
          JOIN admin_areas a
            ON a.iso3 = e.iso3
           AND ST_Contains(a.geom, ST_SetSRID(ST_MakePoint(e.lon, e.lat), 4326))
         WHERE e.collection = %s AND e.iso3 = %s
         ORDER BY e.id, a.level DESC) m      -- deepest level wins
 WHERE h.id = m.event_id;
```

`ORDER BY a.level DESC` is the **deepest** matching level — the same "finest
first, most precise wins" rule `build_theme_areas()` already applies. The GIST
index this needs is already on `admin_areas.geom`, from
`boundaries/migrations/0002_geometry_columns.py`. `lat`/`lon` stay on the row as
the evidence for the match.

Note that `load_hsps.py` resolves its places *before* the rows reach the model,
in its own command — it does not go through `loaders/base.load()`, so it is a
precedent for the matching logic and its `match_method` vocabulary, not for where
the work happens.

### Settings

```python
MONTANDON_STAC_URL = os.environ.get("MONTANDON_STAC_URL") \
    or "https://montandon-eoapi-stage.ifrc.org/stac"
```

The `or` form, not the two-argument `get`, so an empty line in `.env` falls back
to the default instead of pointing the fetcher at nothing. Production is one env
var away the day someone has GO OIDC credentials.

### The button

`pull_button` and `pullable()` both key off the fetcher registry, with no
whitelist. **Registering the fetcher is the button.** The only admin edits are:

- `SOURCE_LABELS["montandon"] = "IFRC Montandon"` in `mcp/admin.py`
- a read-only `HazardEventAdmin` in `external_data/admin.py`

Migration `0014` seeds eight `source_sync` rows — **SDN, TCD, SSD, EGY, ETH, LBY,
CAF, UGA** — following `0013_seed_skipped_ids`, each with a `notes` line
recording the fixed window so a person reading the freshness table knows why the
watermark never narrows anything. Eight rows means eight **Pull now** buttons,
one per country of focus, and they join the existing "pull everything out of
date" batch for free.

## The dashboard

**The whole visible change is that the Hazard dropdown becomes two dropdowns.**
No new layer, no new legend row, no new panel, no new toggle. The hazard
polygons look and behave exactly as they do now; there are simply more of them,
and two controls choosing which light up.

### The two dropdowns

`initThemeControls()` special-cases the hazard dimension and builds two
`makeDropdown`s instead of one, reusing the existing component unchanged.

```
state.activeHazards      category keys   ("hydrological")
state.activeSubHazards   sub-hazard keys ("floods", "flooding")
```

The Sub-Hazard list is **narrowed by whatever Hazard has selected** — pick
Climatological and you see only its sub-hazards; pick nothing and you see them
all.

Those two sets then **resolve down into the existing `state.activeTags` set** as
`hazard|<tag>` keys, via the codebook's `tags` lookup. Selecting *Hydrological*
ticks `hazard|flooding`; selecting the sub-hazard *Flooding* ticks that one
alone. Trends, Community Insights and Top reported hazards therefore keep
working through the machinery they use today, **unchanged**. That is what makes
"only this change" achievable rather than a rewrite.

Sub-hazards that exist only in Montandon — wildfires, earthquake — have no
document tag and filter the event feed only.

### The one named change to `applyFilters`

The two feeds are **not merged into `state.data.tags.hazard`**, and this is the
spec's most easily-got-wrong point. Merging them would light the polygons for
free, but `monthTagTotals("hazard", …)` reads the same object, so **Top reported
hazards** would start showing "wildfires: 40" from Montandon events beside
document mentions — the exact evidence-mixing the vocabulary section above argues
against.

So: `applyFilters` gains **one change, in one place** — the call that computes
which areas to light takes the **union of two feeds**, `tags.hazard` and
`hazard_events.by_sub`. Everything downstream of that call is untouched, and the
three panels stay document-only:

| reads | fed by |
|---|---|
| area fills (the polygons) | document tags **∪** Montandon events |
| area popup | both, labelled by which |
| Trends · Top reported hazards · Community Insights | document tags only |

That is the whole JavaScript change beyond building the second dropdown.

### Montandon events light the same polygons

`build_theme_areas()` widens its p-code set to the union of `narrative_tags` and
`hazard_events`, so a locality only Montandon knows about still gets a polygon
built for it. Nothing else in that function changes.

Two new files under `dashboard/data/`, both written by `s06_mcp_layers.py`:

- **`hazards.json`** — the codebook as the dashboard needs it: the nine
  categories in order, each with its sub-hazards, `in_codebook`, and the
  definitions. Filtered to what actually occurs in the data, so a category with
  nothing behind it does not offer an empty dropdown.
- **`hazard_events.json`** — **no geometry at all**; geometry comes from
  `areas.geojson` as it does today. It holds:
  - `by_sub` — per sub-hazard, monthly counts keyed by
    `{month, country, count, area}`. Deliberately the same shape as a
    `tags.json` entry, so `applyFilters` merges it into the existing
    area-lighting path rather than growing a second one.
  - `events` — a compact list per area and month (date, title, sub-hazard, the
    sources that reported it), so a polygon lit by Montandon can say what lit it.

Deduplication on `corr_id`, preferring `idmc-idu` → `pdc` → `gdacs` — the order
of place-name specificity, since *"North Darfur (Tawila Locality)"* beats
*"Forest fires in Sudan"*. Three reports of one flood light one area once; the
other sources are kept on the entry so the popup can name them.

`tags.json` keeps its current shape. Nothing downstream of it churns.

## Error handling

| situation | behaviour |
|---|---|
| Montandon unreachable or non-JSON | `FetchError`, redacted, recorded on the `PullJob`; no watermark moves |
| country returns zero events | `EmptyPayload` — an unnarrowed empty is a fault, by the loaders' existing guarantee |
| HIP code not in the codebook | row loads with `hazard_category='uncategorised'`, and the code is logged |
| point falls in no admin polygon | row loads with `match_method='unmatched'` and draws nothing |
| neighbour-country event tagged with a focus country | kept; `title` carries the published wording so a reader can see it |
| a `taxonomy.json` hazard tag with no codebook mapping | the test suite fails |

## Testing

New, under `external_data/tests/`:

- **`test_fetcher_montandon.py`** — `plan()` emits one POST Call; the window
  starts `2023-04-15` and ends today; the CQL2 filter names the row's country;
  `since()` returns `None` so `narrowed` is `False`; token pagination follows a
  two-page mock to the end and returns one FeatureCollection.
- **`test_loader_montandon.py`** — a fixture payload loads; an item with
  `["ETH", "SDN"]` becomes two rows and a second country's pull does not
  overwrite the first; an unknown HIP code lands in `uncategorised` rather than
  guessing; `description` never reaches the database; a point inside Tawila
  resolves to Tawila's p-code and a point in open desert comes back `unmatched`;
  and — the regression this spec exists to prevent — `sync.row_count` is
  non-zero after a successful load, which it would not be if `source` carried the
  collection name.
- **`test_hazard_codebook.py`** — every tag in `taxonomy.json`'s hazard dimension
  has a mapping (this is the test that fails the day someone adds a tag and
  forgets); every category resolves to one of the nine; the seven codebook
  categories carry their verbatim definitions.

Plus a `data_pipeline` test that `s03_parse` stamps the two new columns, and the
dashboard checked in a real browser rather than assumed.

## The trap to write into the plan

`docker compose restart web` is a step in the plan, not an afterthought. Gunicorn
never autoreloads, so without it the new admin registration, the changed
templates and the changed `app.js` are simply not served.

The sharper form of this trap — `AddField` backfilling a default, then dropping
it, and a stale worker raising `NotNullViolation` on the next INSERT — **does not
apply here**, and the plan should not claim it does. The two new `NarrativeTag`
columns are nullable, and the writers are `s03_parse` and the loader, both of
which run in a fresh `manage.py` process rather than in a gunicorn worker. The
restart is still required; it is just required for a duller reason.

## GDACS episodes are not duplicates

GDACS publishes `gdacs-event-1028591-1`, `-2`, `-3` for one wildfire — these are
**episodes**, and each carries its own `corr_id`
(`…-EN0205-1-GCDB`, `…-EN0205-2-GCDB`). Deduplication on `corr_id` therefore
keeps them as separate rows, which is correct when they are separate fire fronts
on separate days and merely noisy when they are not. The loader keeps them; the
dedupe step's job is cross-*source* correlation, not collapsing one source's own
episode series. If the dashboard proves too noisy in practice, collapsing
episodes is a follow-up change with its own evidence, not a guess made now.

## Out of scope

- Impact figures (`*-impacts` collections): deaths, displaced, affected. Montandon
  publishes them and they would sit naturally beside these events, but nobody has
  asked for them yet.
- EM-DAT, GLIDE, IFRC-GO and DesInventar events: country-polygon geometry, which
  would light a whole country and defeat the point of this layer.
- Splitting `extreme_heat_drought` into two tags.
- A per-category colour palette. The hazard fill keeps its one colour.
- Production Montandon, until someone holds IFRC GO OIDC credentials.
