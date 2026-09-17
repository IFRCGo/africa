# IFRC Montandon hazard layer, clustered by the IFRC hazard codebook

**Date:** 2026-09-17
**Status:** design agreed, plan not yet written
**Revision:** second pass. The first read the codebook as a list to render on the
dashboard. It is a clustering method — see *What the codebook is for*.

## What this is for

One sentence, the office's own: *here are all the hazards for the countries of
focus and the time window, grouped by category and sub-category, where they
happened and when, with a popup saying how severe, and the insights linked to
them where insights exist.*

That unpacks into five things:

1. **Pull hazard data from IFRC Montandon** for the eight countries of focus over
   a window that always starts 15 April 2023 and always ends today, behind a
   **Pull now** button on Admin → Model Context Protocol → Data sources.
2. **Cluster every hazard found** into the IFRC codebook's categories, using the
   codebook's definitions, and record the category in the database on every table
   a hazard comes from.
3. **Two dropdowns on the dashboard** — Hazard and Sub-Hazard — filled from what
   the data actually holds, not from a static list.
4. **Where and when**, on the map, in the hazard polygons that already exist.
5. **A popup** giving severity or intensity, the people affected or displaced
   where a source publishes them, and **the insights linked to that hazard** —
   accepting that some hazards will have insights and many will not.

Montandon is IFRC's disaster-event registry, published as a STAC API at
<https://montandon-eoapi-stage.ifrc.org/stac>. The codebook is *Hazard
definitions*, IFRC, 2021:
<https://www.ifrc.org/sites/default/files/2021-06/04-HAZARD-DEFINITIONS-HR.pdf>.

## What the codebook is for

**It is a clustering method, not a list to render.** The codebook supplies the
categories and the definitions that say what belongs in each. The *contents* of
the dropdowns come from the data: whatever hazards Montandon and the document
corpus actually hold for these countries in this window, sorted into those
categories by their definitions.

This matters because the two are not the same list. The codebook names sixteen
hazards; Montandon publishes eight kinds for these countries, one of which
(convective storm) the codebook never names but whose definition places it
squarely under *Meteorological hazards*. Rendering the codebook would show
tsunamis and volcanic eruptions to a Sahel operation and hide the storms that
actually happen.

So: categories and definitions from the codebook, membership from the data, and a
mapping table that records which decision was made for each observed hazard and
why.

## What was found before designing

Recorded because each of these closed off an option that looked reasonable.

- **Montandon is not open, and this project has no key for it yet.** Staging
  returns `{"detail": "Not authenticated"}` to a direct request. It answered
  earlier only because the `monty` MCP server holds a credential: the Docker MCP
  catalogue declares `IFRC_API_TOKEN` as its secret. The first draft of this
  design said "no key needed"; that was wrong.
- **Country filtering needs POST.** `GET /search` offers only `bbox`. Filtering
  by country means `POST /search` with a CQL2 filter,
  `{"op": "a_contains", "args": [{"property": "monty:country_codes"}, ["SDN"]]}`.
  `a_overlaps` works too, for several countries at once. `fields` trimming and
  `token` pagination both confirmed. The project's existing fetcher plumbing is
  GET-and-offset only.
- **`reference-events` is empty for Sudan.** Monty publishes a deduplicated
  canonical-event collection, which would have removed the need to correlate
  ourselves. Zero rows for Sudan in this window, so events come from the
  per-source collections and correlation is ours to do, on `monty:corr_id`.
- **The precise sources and the coarse ones are different sources.** GDACS, PDC
  and IDMC-IDU publish located points — IDMC-IDU down to *"Sudan: Flood - North
  Darfur (Tawila Locality) - 17/08/2026"*. EM-DAT, GLIDE and IFRC-GO publish the
  whole country polygon, which on a map means Sudan lights up entire.
- **The `nat-*-*-*` slug is absent on roughly 38% of items.** Across the seven
  non-Sudan focus countries, 500 events carried 500 HIP codes but only 311 slugs.
  Keying the mapping on the HIP code is therefore not a preference; it is the
  only option that works.
- **UNDRR's clusters disagree with the IFRC codebook, twice, in the observed
  data.** Wildfire is `nat-cli-wil-wil` — *climatological* to UNDRR, but
  *Non-technological and man-made* in the codebook. Extreme heat is
  `nat-met-ext-hea` — *meteorological* to UNDRR, but the codebook files heat waves
  under *Climatological hazards*. Any design that parses the slug would silently
  disagree with the codebook this work is keyed to.
- **Wildfires dominate the raw feed.** 385 of the first 500 region-wide events,
  and 407 of 500 for Sudan alone, are GDACS satellite forest-fire detections,
  almost all `severity_label: "Green"` with `potentially_affected: 0`. All seven
  other hazard types together are about 115.
- **Severity exists, and its scales are not comparable.** `monty:hazard_detail`
  on the `*-hazards` items gives `{estimate_type, severity_unit, severity_label,
  severity_value}`. GDACS publishes 0.5 / "Green" on a *GDACS Severity Score*;
  PDC publishes 0.1 / "WATCH" on a *PDC Severity Score*. IDMC-IDU has no
  `-hazards` collection at all.
- **Impacts exist, and are the most useful figures here.** `monty:impact_detail`
  on the `*-impacts` items gives `{type, category, unit, value, estimate_type}`.
  IDMC-IDU publishes `displaced_internal` per event — *"Abu Kershola flood,
  25 Aug 2026, 813 people"* — which is exactly what this dashboard is for.
- **`monty:country_codes` is not tight.** A Sudan-filtered query returned
  *"Flood - Kemashi, Benshangul-Gumaz, Ethiopia"*. Some rows will be neighbour
  events that Montandon tagged with a focus country.
- **Production Montandon is closed too.** `montandon-eoapi.ifrc.org` answers 401
  and wants IFRC GO OIDC credentials.

## The vocabulary

`data_pipeline/hazard_codebook.json`, a new file beside `taxonomy.json` and in
the same spirit: data, read by three consumers, edited in one place.

Nine categories. The first seven are the codebook's own, with its headings and
its definitions quoted verbatim. The last two are this project's, and are marked
`in_codebook: false` so nothing can quietly present them as IFRC's.

### The observed hazards, clustered

This is the `hip_codes` seed, and it is the whole of it — the vocabulary for
these eight countries in this window is eight codes across six categories:

| HIP | UNDRR slug | what it is | IFRC category | note |
|---|---|---|---|---|
| `EN0205` | `nat-cli-wil-wil` | Wildfire | **Non-technological and man-made** | codebook names *Wildfires* explicitly; UNDRR says climatological |
| `MH0600` | `nat-hyd-flo-flo` | Flood | **Hydrological** | codebook *Floods* |
| `MH0103` | `nat-met-sto-sto` | Thunderstorm / lightning | **Meteorological** | not named in the codebook; placed by the category's definition. Montandon keywords: *Thunderstorm, Lightning (electrical storm), Convective-Related* |
| `MH0501` | `nat-met-ext-hea` | Extreme heat | **Climatological** | codebook files heat waves as climatological; UNDRR says meteorological |
| `GH0300` | `nat-geo-mmd-lan` | Landslide | **Geophysical** | codebook *Landslide/debris flows* |
| `MH0401` | `nat-cli-dro-dro` | Drought | **Climatological** | codebook *Drought* |
| `MH0301` | `nat-met-sto-sto` | Violent wind / windstorm (`VW`) | **Meteorological** | resolved from the data: IDMC-IDU *"CAR: Storm - Mbomou"* displacement events, keywords *Wind & Pressure-related, Dust Storm or Sandstorm* |
| `GH0101` | `nat-geo-ear-gro` | Earthquake | **Geophysical** | codebook *Earthquakes* |

`MH0103` and `MH0301` were resolved from the data rather than inferred: both are
convective-storm codes, but `MH0103` is thunderstorm/lightning and `MH0301` is
violent wind, and they carry different labels in the dropdown. They share the
`nat-met-sto-sto` slug, which is one more reason the mapping is keyed on the HIP
code.

Resolving them also produced the sharpest illustration of the loose-country
caveat: the `MH0103` events tagged **Egypt** are *"Dense Fog - Negev, Israel"*.

The remaining codebook categories — Biological, Technological and man-made — carry
no Montandon hazard for these countries, and Biological carries the document tag
*disease_outbreak*. Categories with nothing behind them do not appear in the
dropdown.

### The document tags, clustered

| category | document tags |
|---|---|
| Climatological | *extreme_heat_drought* |
| Biological | *disease_outbreak* |
| Hydrological | *flooding* |
| **Conflict and violence** *(not in codebook)* | *armed_conflict · shelling_airstrikes · attacks_on_civilians · siege_blockade · looting_robbery · explosive_ordnance* |
| **Food insecurity and famine** *(not in codebook)* | *famine_food_crisis* |

**Why two extra categories rather than seven pure ones.** Six conflict tags and
one food-crisis tag are most of the hazard reporting in a Sudan dashboard, and
the codebook has nowhere to put them — it explicitly excludes armed conflict from
"man-made hazards". Filing them as "uncategorised" would label the largest group
of hazards in the data as leftovers. They get named categories, flagged as
outside the codebook, so the codebook stays quotable as written and nothing
disappears from the filter.

**A codebook hazard and a document tag about the same thing stay separate
sub-hazards**, which is why *flooding* sits beside Floods. They are different
evidence: Floods is a dated Montandon event with a located point and a severity,
*flooding* is a sentence somebody wrote in a report. Merging them would make a
filter that cannot distinguish "an agency recorded a flood here" from "a document
mentioned flooding here" — precisely the distinction this platform keeps
everywhere else, and the same reasoning that keeps `MovementPattern` apart from
`data_track.PopulationFigure`. Selecting the **category** gets both; selecting a
**sub-hazard** gets exactly one kind of evidence.

**`extreme_heat_drought` stays one tag.** It spans two codebook hazards, but
splitting it means re-parsing every document in the corpus. Splitting it later is
a `taxonomy.json` change and a re-parse, not a change to this design.

### The file

```
categories[]   key, label, in_codebook, definition, sub_hazards[]
hip_codes{}    "EN0205" -> { category, sub, label, note }
tags{}         "flooding" -> { category, sub }
```

`hip_codes` is keyed on the HIP code and **not** on the slug — the slug is absent
on 38% of items and, where present, disagrees with the codebook twice over. Each
entry carries a `note` recording why that placement was made, so the clustering
is auditable rather than asserted. A code Montandon sends that the table does not
hold lands in `uncategorised` and is logged. It is never guessed at.

### Why a file and not a table

Considered and rejected: two seeded tables with foreign keys from
`narrative_tags` and the events table. The dashboard is static JSON, so the join
would only ever run at build time — a relational model paid for and a file's
worth of use got out of it. Worse, it would put curated rows one foreign key away
from a table `s03_parse` truncates on every run.

Also rejected: deriving categories from Montandon's own slugs. See above.

## The data

### `HazardEvent`, new, in `external_data/models.py`

| column | note |
|---|---|
| `source` | always `montandon` — see below |
| `collection` | `gdacs` / `pdc` / `idmc-idu` |
| `event_id` | Montandon's STAC item id |
| `corr_id` | `monty:corr_id` — ties the same real flood across sources, and ties an event to its severity and its impacts |
| `iso3` | one row per country per item |
| `event_date`, `end_date` | `start_datetime` / `end_datetime` |
| `title` | the item title, verbatim |
| `hazard_codes` | the raw list as published, JSON, so the clustering is auditable |
| `hazard_category`, `hazard_sub` | stamped from the codebook at load time |
| `severity_value`, `severity_unit`, `severity_label`, `severity_estimate_type` | from the `*-hazards` item; null for IDMC-IDU |
| `significance` | `event` or `detection` — see *Wildfire detections* |
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
`loaders/base.load()` finishes by computing
`sync.row_count = model.objects.filter(source=..., iso3=...).count()` from the
**sync key**, which is `source='montandon'`. Writing `gdacs` into `source` would
make that count zero forever, and the admin would report "0 rows" after every
successful pull. Every existing table already follows this convention —
`SeasonalCalendar.source` is fewsnet/acaps, `MovementPattern.source` is
hdx/unhcr/excel.

**The natural key is `(collection, event_id, iso3)`.** One Montandon item can
carry two countries — an observed wildfire had `["ETH", "SDN"]`. With `iso3`
outside the key, pulling Chad after Sudan would silently rewrite Sudan's row. One
item spanning two focus countries becomes two rows, which is also what makes a
per-country **Pull now** button honest.

**`severity_value` must never be sorted, compared or aggregated across
collections.** GDACS 0.5 / "Green" and PDC 0.1 / "WATCH" are different scales
with different meanings. The popup shows `severity_label (severity_unit)`; the
bare number is stored for the record and displayed beside its unit or not at all.

### `HazardImpact`, new

One row per impact figure, because Montandon publishes one item per (event,
impact type) — a flood has a `displaced_internal` item, an earthquake may have
`death` and `injured` items.

| column | note |
|---|---|
| `corr_id` | what ties it to its event |
| `collection`, `impact_id`, `iso3` | the natural key is `(collection, impact_id, iso3)` |
| `impact_type` | `displaced_internal` / `death` / `potentially_affected` / … |
| `category` | `people` / `buildings` / … |
| `value`, `unit`, `estimate_type` | as published |
| `event_date` | copied from the item, so the table stands alone |

Joined to `HazardEvent` on `corr_id` rather than by foreign key: impacts and
events are pulled in separate calls, and an impact whose event has not loaded is
a fact worth keeping rather than an integrity error worth raising.

### Wildfire detections

385 of the first 500 region-wide events are GDACS satellite fire detections with
`severity_label: "Green"` and `potentially_affected: 0`. Everything is stored —
nothing is dropped, because a real and damaging fire near a displacement site
would be dropped along with the noise and no record would remain that it had ever
been published.

Instead, `significance` distinguishes them:

- `detection` — a machine observation with no evidence of consequence: the
  lowest severity band for its scale **and** no impact figure above zero.
- `event` — everything else.

**A `detection` draws only when its sub-hazard is explicitly selected, never when
a category is selected.** Picking *Non-technological and man-made* shows fires
that mattered; picking *Wildfires* shows every fire pixel Montandon holds. The
rule is written into `hazard_codebook.json` next to the severity scales it names,
not hard-coded into the loader, because "the lowest band" is a fact about GDACS
and PDC rather than about hazards.

`significance` is set by an UPDATE at the **end** of a country's refresh, once
severity and impacts have both loaded. That is an ordering dependency and it is
named here on purpose: `plan()` yields events → hazards → impacts in that order,
and the runner consumes the generator serially, which is what makes it safe.

### `NarrativeTag` gains `hazard_category` and `hazard_sub`

Stamped by `s03_parse.py` from the same file, null for the non-hazard dimensions.
Derived at parse time, never curated in the table — `s03_parse` deletes and
rebuilds `narrative_tags` on every run, so nothing hand-entered there survives.

## The fetch

`external_data/fetchers/montandon.py` — `source="montandon"`,
`dataset="hazard_events"`, `variant=""`, **`requires=("IFRC_API_TOKEN",)`**.

`plan(sync)` yields **three Calls per press**, in this order:

1. `*-events` → `HazardEvent` rows
2. `*-hazards` → severity, applied onto those rows by `corr_id`
3. `*-impacts` → `HazardImpact` rows, then the `significance` UPDATE

Each is a POST to `/search` carrying that kind's three collections, the fixed
window, and this row's country:

```python
{"collections": ["gdacs-events", "pdc-events", "idmc-idu-events"],
 "datetime":    f"{WINDOW_START}T00:00:00Z/{today}T23:59:59Z",   # 2023-04-15 -> today
 "filter":      {"op": "a_contains",
                 "args": [{"property": "monty:country_codes"}, [sync.iso3]]},
 "fields":      {"include": ["id", "collection", "geometry", "bbox",
                             "properties.title", "properties.datetime",
                             "properties.start_datetime", "properties.end_datetime",
                             "properties.monty:hazard_codes",
                             "properties.monty:country_codes",
                             "properties.monty:corr_id"],
                 "exclude": ["properties.description", "assets",
                             "properties.keywords", "stac_extensions"]}}
```

The hazards call swaps `monty:hazard_detail` into `include`; the impacts call
swaps `monty:impact_detail`. `idmc-idu-hazards` does not exist and is not
requested.

`since()` is **overridden to return `None`, always**. The office asked for the
whole window on every pull, so the inherited 90-day-lookback watermark behaviour
is deliberately switched off. `narrowed` is therefore always `False`, and under
the loaders' "empty is a failure" guarantee a country that genuinely returns
nothing fails loudly rather than being recorded as up to date. Egypt was checked
and has events.

The `fields` trim is not a nicety. It is what keeps a pull to a sane size on disk
and in `data_pipeline/mcp_cache/`.

### Authentication

`IFRC_API_TOKEN` in `.env`, added to `env.example` and to `SECRET_SETTINGS` in
`fetchers/base.py` so it is redacted out of every log line and error message —
the same treatment `IPC_API_KEY` and `HDX_API_TOKEN` already get.

**The header shape is the plan's first task.** Montandon's STAC advertises OIDC
against `goadmin.ifrc.org`, while the `monty` MCP server takes a flat
`IFRC_API_TOKEN`; the two plausible shapes are `Authorization: Bearer <token>`
and IFRC GO's own `Authorization: Token <token>`. One curl settles it, and it is
task one rather than a design decision.

The token exists in the operator's Docker MCP secret store and must be copied
into `.env` by hand. Until it is there, `pull_button` shows *"needs
IFRC_API_TOKEN in .env"* and nothing is called — the existing affordance, for
free.

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

## The loaders

Three, all registered, all writing to the one
`montandon/hazard_events/<iso3>` sync row.

**`Loader` gains two things:**

- `after_insert(rows)` — an optional hook called inside `load()`'s transaction
  after `bulk_create` and the geometry pass. This is where raw SQL that needs the
  rows to exist belongs, and `_write_geometry` is the precedent.
- `counts_rows = True` — a class attribute. `load()` currently always overwrites
  `sync.row_count` from its own model, so with three loaders on one sync row the
  last to run would win and the freshness table would report the impact count as
  the event count. The hazards and impacts loaders set it `False`.

**`MontandonEventLoader`** parses the FeatureCollection into `HazardEvent` rows:
one row per (item × focus country in `monty:country_codes`), hazard codes mapped
through the codebook, `description` dropped, `high_water()` returning the newest
`event_date`.

**`parse()` stays pure.** `loaders/base.py` documents it as *"Pure — no database
access"*, so point-in-polygon cannot happen there. `parse()` sets
`match_method='unmatched'` as the default and `after_insert` runs:

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
`boundaries/migrations/0002_geometry_columns.py`.

`load_hsps.py` resolves its places *before* the rows reach the model, in its own
command; it does not go through `loaders/base.load()`. It is a precedent for the
matching logic and the `match_method` vocabulary, not for where the work happens.

**`MontandonSeverityLoader`** does **not** insert. Hazard items have their own
STAC ids and are not events; upserting them into `HazardEvent` would double every
row. It parses `monty:hazard_detail` into `{corr_id: detail}` and its
`after_insert` writes the four severity columns onto the matching
`HazardEvent` rows **by `corr_id`**, not by the natural key. Its `parse()`
returns the details as rows so the "empty is a failure" guarantee still applies
to a payload that came back broken.

**`MontandonImpactLoader`** writes `HazardImpact` rows, then runs the
`significance` UPDATE described above as the last step of the refresh.

## The dashboard

**The whole visible change is that the Hazard dropdown becomes two dropdowns,
and the hazard popup says more.** No new layer, no new legend row, no new panel,
no new toggle. The hazard polygons look and behave exactly as they do now; there
are simply more of them, two controls choosing which light up, and a richer popup
when one is clicked.

### The two dropdowns

`initThemeControls()` special-cases the hazard dimension and builds two
`makeDropdown`s instead of one, reusing the existing component unchanged.

```
state.activeHazards      category keys   ("hydrological")
state.activeSubHazards   sub-hazard keys ("floods", "flooding")
```

Both lists are built from `hazards.json`, which is written from **what the data
holds** — a category with nothing behind it never appears. The Sub-Hazard list is
narrowed by whatever Hazard has selected: pick Climatological and you see only
its sub-hazards; pick nothing and you see them all.

Those two sets then **resolve down into the existing `state.activeTags` set** as
`hazard|<tag>` keys, via the codebook's `tags` lookup. Selecting *Hydrological*
ticks `hazard|flooding`; selecting the sub-hazard *Flooding* ticks that one
alone. Trends, Community Insights and Top reported hazards therefore keep working
through the machinery they use today, **unchanged**.

Sub-hazards that exist only in Montandon — wildfires, earthquake — have no
document tag and filter the event feed only.

### The one named change to `renderThemes`

The two feeds are **not merged into `state.data.tags.hazard`**, and this is the
spec's most easily-got-wrong point. Merging them would light the polygons for
free, but `monthTagTotals("hazard", …)` reads the same object, so **Top reported
hazards** would start showing "wildfires: 407" from GDACS fire pixels beside
document mentions — the exact evidence-mixing the vocabulary section argues
against.

So: `renderThemes()` gains **one change, in one place** — its
`for (const key of state.activeTags)` loop, which accumulates `byArea` and
`detail`, is followed by a second short loop over `hazard_events.by_sub` adding
into the same `byArea[area].hazard` count and into a separate
`detail[area].hazardEvents` list. Everything downstream of that is untouched:

| reads | fed by |
|---|---|
| area fills (the polygons) | document tags **∪** Montandon events |
| area popup | both, labelled by which |
| Trends · Top reported hazards · Community Insights | document tags only |

That is the whole JavaScript change beyond building the second dropdown and
extending the popup.

### Montandon events light the same polygons

`build_theme_areas()` widens its p-code set to the union of `narrative_tags` and
`hazard_events`, so a locality only Montandon knows about still gets a polygon
built for it. Nothing else in that function changes.

Two new files under `dashboard/data/`, both written by `s06_mcp_layers.py`:

- **`hazards.json`** — the categories and sub-hazards **present in the data**, in
  codebook order, each with `in_codebook`, its definition, and its counts.
- **`hazard_events.json`** — **no geometry at all**; geometry comes from
  `areas.geojson`. It holds:
  - `by_sub` — per sub-hazard, monthly counts keyed by
    `{month, country, count, area}`. Deliberately the same shape as a
    `tags.json` entry, so the union above is a union of like things.
  - `events` — per area and month: date, title, sub-hazard, `significance`,
    `severity_label` + `severity_unit`, the impact figures, the sources that
    reported it, and `insight_ids`.

Deduplication on `corr_id`, preferring `idmc-idu` → `pdc` → `gdacs` — the order
of place-name specificity, since *"North Darfur (Tawila Locality)"* beats
*"Forest fires in Sudan"*. Three reports of one flood light one area once; the
other sources are kept on the entry so the popup can name them.

`tags.json` keeps its current shape. Nothing downstream of it churns.

### The popup

For a polygon lit by a Montandon hazard, the popup gains:

- **what and when** — sub-hazard and date, with its category named
- **how severe** — `severity_label (severity_unit)`, never a bare number, and
  omitted entirely where the source published none (every IDMC-IDU event)
- **who it touched** — the `HazardImpact` figures, each labelled by type:
  *"813 people displaced (IDMC-IDU)"*
- **who said so** — the collections that reported it
- **linked insights** — the quotes, where any link

Nothing is invented to fill a gap. An IDMC-IDU flood shows displacement and no
severity; a GDACS fire shows severity and no displacement. Empty sections are
absent rather than shown as "unknown".

### Linking insights to hazards

Computed at build time in `s06`, written as `insight_ids` on each event entry.
An `Insight` links to a `HazardEvent` when **all three** hold:

1. **Same hazard** — the insight has an `InsightCoding` in the `hazard` dimension
   whose tag maps, through the codebook's `tags` table, to the event's
   `hazard_category`; a shared `hazard_sub` is recorded as a stronger link.
2. **Same place** — `Insight.admin_pcode` equals the event's `admin_pcode`, or is
   an ancestor of it. A country-level insight does not link to every event in the
   country.
3. **Same month** — `Insight.stated_on` falls in the month of `event_date`.

Only published insights are considered. **Many events will link to nothing, and
that is expected** — it is what the office asked for: the hazards are the spine,
the insights attach where they exist.

This step **reads** the `insights` app and never writes to it. That app is never
written by any pipeline step, deliberately, and this design does not change that.

## Error handling

| situation | behaviour |
|---|---|
| `IFRC_API_TOKEN` not set | button reads "needs IFRC_API_TOKEN in .env"; nothing is called |
| Montandon 401 | `FetchError`, token redacted, recorded on the `PullJob`; no watermark moves |
| Montandon unreachable or non-JSON | same |
| country returns zero events | `EmptyPayload` — an unnarrowed empty is a fault, by the loaders' existing guarantee |
| HIP code not in the codebook | row loads with `hazard_category='uncategorised'`, and the code is logged |
| point falls in no admin polygon | row loads with `match_method='unmatched'` and draws nothing |
| severity item with no matching event | ignored; the UPDATE simply matches nothing |
| impact item with no matching event | kept — an impact whose event has not loaded is a fact, not an integrity error |
| neighbour-country event tagged with a focus country | kept; `title` carries the published wording so a reader can see it |
| a `taxonomy.json` hazard tag with no codebook mapping | the test suite fails |

## Testing

New, under `external_data/tests/`:

- **`test_fetcher_montandon.py`** — `plan()` emits three POST Calls in the order
  events → hazards → impacts; the window starts `2023-04-15` and ends today; the
  CQL2 filter names the row's country; `since()` returns `None` so `narrowed` is
  `False`; a missing `IFRC_API_TOKEN` calls nothing; token pagination follows a
  two-page mock to the end and returns one FeatureCollection.
- **`test_loader_montandon.py`** — a fixture payload loads; an item with
  `["ETH", "SDN"]` becomes two rows and a second country's pull does not
  overwrite the first; an unknown HIP code lands in `uncategorised` rather than
  guessing; `description` never reaches the database; a point inside Tawila
  resolves to Tawila's p-code and a point in open desert comes back `unmatched`;
  severity lands on the event by `corr_id` **without** creating a second row; a
  Green zero-affected GDACS fire is classified `detection` and a displacing flood
  `event`; and `sync.row_count` counts events after all three loaders have run.
- **`test_hazard_codebook.py`** — every tag in `taxonomy.json`'s hazard dimension
  has a mapping (this is the test that fails the day someone adds a tag and
  forgets); every observed HIP code has one too; every category resolves to one
  of the nine; the seven codebook categories carry their verbatim definitions.

Plus a `data_pipeline` test that `s03_parse` stamps the two new columns, a test
that the insight-linking rule links a same-place same-month flood insight and
does **not** link a country-level one, and the dashboard checked in a real
browser rather than assumed.

## The traps to write into the plan

**`docker compose restart web` is a step, not an afterthought.** Gunicorn never
autoreloads, so without it the new admin registration, the changed templates and
the changed `app.js` are simply not served. The sharper form of this trap —
`AddField` backfilling a default then dropping it, and a stale worker raising
`NotNullViolation` — does not apply here: the new `NarrativeTag` columns are
nullable and the writers run in fresh `manage.py` processes.

**GDACS episodes are not duplicates.** GDACS publishes
`gdacs-event-1028591-1`, `-2`, `-3` for one wildfire; these are episodes and each
carries its own `corr_id`. Dedupe on `corr_id` keeps them separate, which is
correct when they are separate fire fronts on separate days. Collapsing episodes
is a follow-up change with its own evidence, not a guess made now.

## Out of scope

- EM-DAT, GLIDE, IFRC-GO and DesInventar events: country-polygon geometry, which
  would light a whole country and defeat the point of this layer.
- Splitting `extreme_heat_drought` into two tags.
- A per-category colour palette. The hazard fill keeps its one colour.
- Collapsing GDACS episode series into one event.
- Production Montandon, until someone holds IFRC GO OIDC credentials.
- Writing anything back to the `insights` app.
