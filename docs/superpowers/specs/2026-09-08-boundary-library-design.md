# Boundary library: authoritative admin boundaries in the database

**Date:** 2026-09-08
**Status:** approved design, not yet implemented

## 1. Why

Three things are wrong with how the dashboard handles geography today.

**The polygons are borrowed.** `dashboard/data/boundaries/*.geojson` is built by
`build_map_context` from the geoBoundaries API, plus vendored assets copied from the IFRC
HSP dashboard. Nobody in this office chose those boundaries and nobody here can vouch for
them. Meanwhile the office holds the authoritative OCHA Common Operational Datasets for
every country in the corpus, with p-codes, validity dates and alternate-language names.

**The highlight does not look like a place.** An area named in the reporting is drawn as up
to five inset outlines, one per pillar. The effect reads as tracings laid over the map
rather than as the state or locality the report was talking about.

**Two-country view puts a highlight on the wrong side.** With Sudan and Ethiopia selected,
Ethiopia's vulnerability reporting appears in the Sudan half and nothing appears in the
Ethiopia half. Diagnosed below: two independent faults, both confirmed in the current data.

## 2. Goals

1. Load the office's own boundary files into the database, categorised ADM0 → the lowest
   level each source holds, so any map layer the dashboard or an analyst later needs is
   already there and only has to be asked for.
2. Draw a named area as a real filled polygon from that library.
3. Make the two-country view highlight each country in its own half.

## 3. Non-goals

- No change to what the reports say, which figures are extracted, or how the timeline works.
- No vector-tile infrastructure. 10,867 polygons do not warrant a tile server.
- No GeoDjango. PostGIS on the database side only; the web container stays light.
- The CSV point files (airports, city lists, state capitals) and `Security zones-Chad.kml`
  are out of scope for this pass — they need readers that pyshp does not provide.

## 4. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Geometry storage | **PostGIS** (`postgis/postgis:16-3.4-alpine`) | The user wants QGIS, DBeaver and Power BI to open these tables as real layers, and wants the database able to answer spatial questions itself (which ADM2 contains this camp?). The image is a superset of `postgres:16` sharing the same `PGDATA` layout, so the existing volume is reused. |
| ORM | **Raw SQL for geometry**, Django models for everything else | GeoDjango would require GDAL and GEOS inside the web image for no capability this design needs. |
| Highlight style | **Solid fill in the leading pillar's colour + crisp outline + thin inset edges for the other pillars** | An area reads as a place; convergence of several pillars stays visible. |
| Match depth | **As deep as each source goes** (ADM4 where present) | User's explicit choice, made with the false-positive risk stated. Mitigated by the guards in §10. |
| Delivery to the browser | **On-demand from PostGIS by p-code** | Payload becomes proportional to what is drawn (~130 polygons in practice), so depth stops being a payload decision. Also yields the generic layer endpoint that makes the library reusable. |

## 5. What gets loaded

### 5.1 Administrative boundaries — folder 1

`C:\Users\Admin\OneDrive - IFRC\Sudan Crisis - Chad 2026\Chad Maps\Countries Maps`

| Country | ADM0 | ADM1 | ADM2 | ADM3 | ADM4 | Schema | Publisher |
|---|---|---|---|---|---|---|---|
| Sudan | 1 | 19 | 189 | 237¹ | — | `itos_lower` / `gadm`¹ | OCHA ITOS; GADM¹ |
| Chad | 1 | 23 | 70 | — | — | `itos_lower` | OCHA ITOS |
| Ethiopia | 1 | 13 | 92 | 1,082 | — | `itos_lower` | OCHA ITOS |
| Egypt | 1 | 27 | 365 | 5,716 | — | `itos_lower` | OCHA ITOS |
| Libya | 1 | 3 | 22 | — | — | `itos_lower` | OCHA ITOS |
| Uganda | 1 | 4 | 135 | 208 | 1,520 | `itos_lower` | OCHA ITOS |
| CAR | 1 | 17 | 73 | 176 | 202 | `caf_camel` | SIGCAF / REACH / OCHA |
| South Sudan | 1 | 10 | 79 | 512 | — | `ocha_upper` | IMWG / NBS, 2023-08-29 |
| Eritrea | 1 | 6 | 58 | — | — | `itos_lower` | OCHA ITOS |

¹ Sudan's ADM3 comes from a GADM file (`sdn_adm3`), a different publisher with no p-codes.

**10,867 admin polygons** in total, plus the 14 IFRC Areas of Interest carried over from
`boundaries/aoi.geojson` (there is no other source for them).

Two facts worth recording, because they change what the map shows:

- **Libya's ADM1 is 3 regions, not 22.** The dashboard currently treats Libya's 22
  *districts* as its ADM1. Under the real hierarchy those are ADM2. Since matching now runs
  at every level this is not a loss, but any UI that says "states" must not assume ADM1 is
  the interesting level in Libya.
- **Ethiopia gains two regions** (13 vs the 11 in the current file): the vendored geometry
  predates Sidama and South West Ethiopia.

### 5.2 Physical features — folder 2

`…\Nigeria Malnutrition 2025\HDCC Africa-1 …\QGIS_Template_2024\layers`

Loaded into `map_features`: `10m_rivers_lake_centerlines`, `ne_10m_lakes`,
`World water body limits polygons`, `OCHA National and Regional Capital`, `IFRC_Regions`,
`ICRC Admin Boarders WD Internal`. This **retires the Natural Earth download** in
`build_map_context`: the dashboard's water layer starts coming from the office's own files.

Skipped as redundant with the Carto basemap: `Land`, `naturalearth_landpolygons`,
`naturalearth_world_boundingbox_wgs84`, `naturalearth_world_graticules`.

### 5.3 Extra layers from folder 1

Loaded into `map_features` and available, but not wired into the dashboard in this pass:
Sudan roads 2021, Chad health districts (2020), Chad refugee/IDP sites (OCHA), Ethiopia
refugee camps (UNHCR 2019), UNHCR refugee sites (Jan 2021), Chad security zones.

### 5.4 Eritrea

Eritrea already appears as a country on tag rows in the current data but has no polygon, so
its reporting can never be placed. Loading its boundaries closes that gap. Adding Eritrea as
a tenth country in the dashboard's country filter is **a separate decision, not taken here**
— the boundaries will simply be present when it is.

## 6. Data model

New Django app `boundaries`. Three tables. Every column below except `geom` / `geom_web` is
an ordinary Django field; the geometry columns and their GiST indexes are added by a
`RunSQL` migration and read and written through raw `psycopg` SQL.

### `boundary_sources`
One row per ingested file: `path`, `publisher`, `source_label`, `valid_on`, `version`,
`licence`, `feature_count`, `schema` (one of the four adapters), `sha1`, `ingested_at`.
Every polygon can name the file it came from and the date that file was valid.

### `admin_areas`

| column | type | notes |
|---|---|---|
| `id` | pk | |
| `source` | FK → `boundary_sources` | |
| `kind` | text | `admin` \| `aoi`; extensible |
| `iso3`, `country_name` | text, indexed | **never null**, AOIs included (§9, fault 1) |
| `level` | int, indexed | 0–4; null for non-admin kinds |
| `pcode` | text, indexed | the identity. Synthesised `SDN-GADM3:<id>` where the source has none |
| `name` | text, indexed | primary/English name |
| `ref_name` | text | source's own reference spelling |
| `name_alt` | JSONB | alternates from `adm*_name1..3` with their `lang` — Arabic and French spellings become free aliases for the matcher |
| `parent_pcode` | text, indexed | |
| `name_path` | text | "Sudan › North Darfur › El Fasher", for popups and the ambiguity fallback |
| `valid_on`, `version` | date, text | from source attributes |
| `area_sqkm` | float | |
| `center_lat`, `center_lon` | float | source value where given, else `ST_PointOnSurface` |
| `bbox` | float[4] | for map fitting |
| `geom` | `geometry(MultiPolygon,4326)` | full resolution, GiST-indexed — what QGIS opens |
| `geom_web` | `geometry(MultiPolygon,4326)` | simplified at load for the browser |

Unique constraint `UNIQUE NULLS NOT DISTINCT (source_id, kind, level, pcode)`. The
`NULLS NOT DISTINCT` clause (PostgreSQL 15+) matters: `level` is null for AOIs, and under
the default rule null values never collide, so duplicate AOI p-codes would pass unnoticed.

### `map_features`
`layer` (indexed), `name`, `kind` (`river` / `lake` / `capital` / `road` / `site` / …),
`props` JSONB for whatever the source carried, `source` FK, `geom` (mixed geometry type),
`geom_web`.

### Simplification tolerances

`ST_SimplifyPreserveTopology`, tolerance by level: ADM0/1 `0.005°`, ADM2 `0.002°`,
ADM3 `0.001°`, ADM4 `0.0005°` (roughly 550 / 220 / 110 / 55 m). Coordinates are emitted at
5 decimal places (~1 m). Full-resolution `geom` is never simplified and is what any
spatial query or QGIS session uses.

## 7. The loader

`python manage.py load_boundaries [--only ISO3] [--layer NAME] [--dry-run]`

Both source folders sit outside the container's current mounts, so `docker-compose.yml`
gains two read-only bind mounts, addressed by a `BOUNDARY_SOURCE_DIRS` env var. Source files
are **not** copied into the repository.

`boundaries/sources.py` holds an explicit registry — one entry per shapefile giving iso3,
level, kind, schema adapter, publisher and validity — rather than inferring anything from
filenames. Guessing wrong here files a polygon under the wrong name silently, which is the
one failure mode this whole exercise exists to remove.

Four schema adapters, each a small pure function from a DBF record to the common shape:

| adapter | name field | pcode field | used by |
|---|---|---|---|
| `itos_lower` | `adm2_name` | `adm2_pcode` | SDN, TCD, ETH, EGY, LBY, UGA, ERI |
| `ocha_upper` | `ADM2_EN` | `ADM2_PCODE` | SSD |
| `caf_camel` | `admin2Name` | `admin2Pcod` | CAF |
| `gadm` | `NAME_2` | `ID_2` (synthesised p-code) | SDN ADM3 only |

Per file, in one transaction:

1. Read the `.prj`. **Refuse the file unless it is WGS84** — a silent projection mismatch
   puts a country in the wrong hemisphere.
2. Delete any rows already carrying this source's id, so a reload replaces exactly its own
   rows and the command is safely repeatable.
3. Read features with pyshp; build geometry with shapely; repair self-intersections with
   `buffer(0)`; promote Polygon to MultiPolygon.
4. Map attributes through the adapter; keep alternates and `lang`.
5. Insert via `ST_GeomFromWKB(%s, 4326)`; compute `geom_web`, `bbox`, and a centroid where
   the source gives none.

Two joins cannot be done by name and are done **spatially**:

- **Sudan ADM3 (GADM) → ADM2 (OCHA).** The two publishers transliterate differently
  ("Al Jazirah" vs "Aj Jazirah"), so each ADM3's parent is the ADM2 containing its
  `ST_PointOnSurface`. Recorded as spatially derived in provenance.
- **The 14 IFRC AOIs → a country.** Each AOI's `iso3` is the ADM0 containing its
  point-on-surface. This is what closes fault 1.

New dependencies: `pyshp` (pure Python) and `shapely` (wheels bundle GEOS). No system
packages are added to the image.

## 8. The API

New app URLs under `/api/boundaries/`:

- `GET layers/` — the catalogue: country, level, feature count, source file, publisher,
  `valid_on`. This is the "what maps do we already have" answer.
- `GET layer/?iso3=ETH&level=2[&kind=][&full=1]` — one whole level as GeoJSON, simplified
  unless `full=1`. Requests for full resolution above 1,000 features are refused with a
  message naming the simplified alternative.
- `GET features/?ids=SD01001,ET0101,…` — exactly these polygons; this is what highlighting
  uses. Capped at 500 ids per request; `POST` with a JSON body accepts longer lists.

Responses are `application/geo+json` with `Cache-Control: public, max-age=604800` and an
ETag derived from the newest `ingested_at` among the rows returned. This is deliberately
opposite to the pipeline's data files, which are `no-store` because the pipeline rewrites
them; boundaries change only when someone reloads them.

## 9. The two-country bug

Two independent faults. Both are confirmed against the data currently in
`dashboard/data/tags.json`, not inferred.

### Fault 1 — a highlight on the wrong country

`s03_parse.attribute_area` enforces "the place must be in the country this sentence was
attributed to" only when the place *has* a country:

```python
if place_country and country and place_country != country:
    continue
```

`_load_places` registers the 14 AOI polygons with `country=None`, so that guard never fires
for them and an AOI matches a sentence about any country. In the current data this has put
**20 Sudan-attributed tag rows onto `AOI:Amhara`**, an Ethiopian region whose western edge
(35.3°E) falls inside the Sudan pane's frame — the highlight the user sees on the Sudan
side. The same hole has put 27 Sudan rows on Vakaga (CAR), 34 on Ouaddaï (Chad) and 6
Ethiopia rows on Sila (Chad).

**Fix:** every polygon carries an `iso3` (§7), so the guard always applies.

### Fault 2 — nothing on the Ethiopia side

Every map layer is filled by a render function, except `areas`. `addLayers(m)` creates it
with `data: empty()`, and `loadAreas()` hands the geometry only to the maps alive at the
moment its fetch resolves. `mapB` is built lazily, the first time two countries are
selected — after that. So the right-hand pane holds an empty `areas` source for its whole
life and cannot highlight anything, whatever the data says. `renderThemes` then writes
feature states onto features that do not exist there.

**Fix, immediate:** seed the source at creation — `data: state.data.areas || empty()`.
**Fix, structural:** under §11 `areas` becomes render-filled like every other layer, so the
special case that caused this stops existing.

### Third guard

`renderThemes` will additionally skip a row whose area's country is not the one this pane is
showing. To make that possible without geometry being loaded, `tag_areas.json` gains an
`iso3` per area id. This is belt-and-braces: fault 1 is fixed at source, and this stops a
future data slip from putting a polygon in the wrong half again.

## 10. Matching report text to places

`NarrativeTag.area_id` becomes a p-code; a new `NarrativeTag.area_level` column records how
deep the match went. The lookup is built from `admin_areas` instead of from GeoJSON files.

At ADM3/ADM4 the name space is large and noisy — Egypt alone has 5,716 ADM3 names — so the
lookup gains guards:

1. **Country must agree.** Now enforceable for every polygon, AOIs included.
2. **Alternates join the lookup.** `name_alt` and `ref_name` bring Arabic and French
   spellings in for free, replacing most of the hand-written `_PLACE_ALIASES` table.
3. **Minimum name length rises with depth** — 4 characters at ADM0–2 as today, 6 at ADM3+.
4. **Ambiguity falls back rather than guesses.** A normalised name occurring at several
   places within one country resolves to their nearest common ancestor via `name_path`; if
   they share none, it is dropped.
5. **Stoplist** for names that are ordinary English or French words.
6. **Deepest match still wins** when a sentence names both a locality and the state around
   it.

This requires `run_pipeline --reparse` (steps 3–7), which works from page text already in
the database — no PDFs are re-read. All 63,772 tag rows are re-attributed and **some
highlights will legitimately move**. The audit in §12 reports the largest before/after
shifts so that change is inspected rather than discovered later.

## 11. Rendering

The `areas` source stops being a 2.3 MB file loaded once.

- `renderThemes` computes the p-codes this month and this tag selection need, calls
  `ensureAreas(ids)` — which fetches only ids not already in a client-side cache, chunked at
  200 per request — and hands each pane a FeatureCollection of just the polygons it draws.
- Layers replacing the wash and the five offset bands:
  - `area-fill` — fill in the leading pillar's colour, opacity from mentions (0.18–0.55)
  - `area-outline` — 1.6 px line in the same colour
  - `area-edge-<dim>` — a thin inset line per *non-leading* pillar reporting the same area
- The popup keeps carrying tag-by-tag detail and the sentence from the reporting.

Because geometry now follows the render, ADM4 costs nothing until something is reported at
ADM4, and a newly created pane fills itself.

## 12. Verification

The project has no test suite. This adds Django's built-in runner — no new dependency —
for the parts where an error is silent, plus a data audit.

**Unit tests** (`manage.py test`):
- each of the four schema adapters, against a real record from its own source file
- p-code synthesis and the spatial parent join for Sudan's GADM ADM3
- every matching guard in §10: country disagreement, short name at depth, ambiguous name
  falling back to a shared parent, stoplist, deepest-wins

**`manage.py check_boundaries`** asserts:
- per-level feature counts equal the source files (the table in §5.1)
- every polygon's point-on-surface lies inside its own declared country's ADM0. Publishers
  disagree along disputed and administered boundaries, so **Abyei PCA and the Halayeb
  triangle are named exceptions**: they are reported, not failed. An unexpected polygon
  failing this check is a genuine error and does fail the audit.
- every `parent_pcode` resolves, and no cycles
- every `NarrativeTag.area_id` resolves to a polygon
- no polygon carries a null `iso3`
- and reports the largest before/after shifts in highlighting from the re-parse

**In the browser:** Sudan + Ethiopia selected, vulnerability pillar on — the Ethiopian
regions highlight in the Ethiopia half and no Ethiopian polygon appears in the Sudan half.

## 13. Sequencing

| Phase | Work | Verified by |
|---|---|---|
| 0 | Fault 2 one-line fix | Browser: Sudan + Ethiopia, both halves highlight |
| 1 | `pg_dump -Fc` backup, then PostGIS image swap, `CREATE EXTENSION postgis` | Existing dashboard unchanged; `SELECT postgis_version()` |
| 2 | `boundaries` app, models, migrations, source registry, loader, compose mounts | `check_boundaries` counts match §5.1 |
| 3 | Unit tests + audit command | `manage.py test` green |
| 4 | API endpoints | `layers/` catalogue matches §5.1; `features/` round-trips |
| 5 | Renderer: fill + on-demand geometry | Browser, all pillars, several months |
| 6 | Matcher rewrite, `--reparse`, before/after diff | Audit's shift report reviewed together |
| 7 | Retire geoBoundaries and Natural Earth downloads; water from `map_features`; remove the vendored `boundaries/*.geojson` the dashboard no longer reads | `build_map_context` no longer reaches the network |

`aoi.geojson` is the exception to phase 7's cleanup: it is the **only** source for the 14
IFRC Areas of Interest, so it is not deleted but moved to a `boundaries/sources/` folder and
registered in `sources.py` like any other input file.

Phase 0 lands and is confirmed before anything else moves, so the split-pane fix is proven
independently of the boundary swap.

## 14. Rollback

Phase 1 is the only step touching infrastructure. `postgis/postgis:16-3.4-alpine` shares
`postgres:16`'s `PGDATA` layout, so the existing `pgdata` volume is reused in place. A
custom-format `pg_dump` is taken first and kept until phase 7 passes.

Rollback depends on how far things got:

- **Before phase 2** (extension created, no geometry columns yet): reverting the image tag
  is enough. `DROP EXTENSION postgis` first, since plain `postgres:16` has no PostGIS
  libraries and would fail on any object that depends on them.
- **After phase 2**: restore the `pg_dump` into a fresh `postgres:16` volume. Swapping the
  tag back is not sufficient — the geometry columns in `admin_areas` and `map_features`
  depend on the extension, and a plain PostgreSQL server cannot read them.
