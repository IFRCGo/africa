# Maintaining Sudan & Neighbouring countries

Everything runs in Docker. Start the stack once and leave it running:

```powershell
docker compose up -d
```

| | |
|---|---|
| Dashboard | <http://localhost:2026/> |
| Updater | <http://localhost:2026/updater/> |
| Database admin | <http://localhost:2026/admin/> |
| pgAdmin | <http://localhost:5050/> |

Every command below is run against the `web` container. The prefix is always
the same, so it is written once here and shortened afterwards:

```powershell
docker compose exec web python manage.py <command>
```

---

## 1. New documents arrive — the no-command-line way

1. Drop the PDFs into the right year folder of
   `UNHCR Regional Population Movement pdfs` or `UNHCR Sudan only pdfs`.
2. Open <http://localhost:2026/updater/> and press **Re-check folders**.
3. Press **Update now**. A progress bar follows the seven pipeline steps and the
   log box shows what each one is doing.
4. When it finishes, the embedded dashboard preview reloads by itself.

With no new files the button reads **Rebuild anyway**, which re-exports
everything from the stored text — useful after changing a parser.

The same thing from a terminal:

```powershell
docker compose exec web python manage.py run_pipeline
```

## 2. Tuning without re-reading PDFs

Steps 1 and 2 (catalogue, extract text) only ever *add* to the database. Steps 3
to 7 delete and rebuild what they own, so re-tuning never needs the PDFs again.

```powershell
docker compose exec web python manage.py run_pipeline --reparse       # steps 3-7
docker compose exec web python manage.py run_pipeline --only s05      # export only
docker compose exec web python manage.py run_pipeline --only s06,s07  # external layers
docker compose exec web python manage.py run_pipeline --list          # show the steps
```

| To change… | Edit… | Then run |
|---|---|---|
| which theme toggles exist | `Community Centered Humanitarian Analysis Platform/data_pipeline/taxonomy.json` | `--reparse` |
| places and corridors | `Community Centered Humanitarian Analysis Platform/data_pipeline/gazetteer.json` | `--reparse` |
| how figures are read | `Community Centered Humanitarian Analysis Platform/data_pipeline/steps/s03_parse.py` | `--reparse` |
| the curated milestones | `Community Centered Humanitarian Analysis Platform/data_pipeline/steps/s04_events.py` | `--reparse` |
| how numbers are cleaned | `Community Centered Humanitarian Analysis Platform/data_pipeline/steps/s05_export.py` | `--only s05` |
| the map itself | `dashboard/static/dashboard/js/app.js`, `dashboard/static/dashboard/css/app.css`, `dashboard/templates/dashboard/index.html` | nothing — refresh |

Python changes take effect after `docker compose restart web`. Changes to
`requirements.txt` need `docker compose up -d --build`.

> A restart takes about 90 seconds. Almost all of it is the `collectstatic
> --noinput --clear` line in `Community Centered Humanitarian Analysis Platform/entrypoint.sh`: `--clear` deletes and
> re-copies every static file, which is slow over a OneDrive-synced folder.
> Dropping `--clear` makes restarts near-instant; keep it only if you are
> chasing a stale-static-file problem. Editing the dashboard's own `app.js` or
> `app.css` needs no restart at all - just refresh.

## 3. Updating the Excel data layers

Two workbooks live beside the PDFs in the `SUDAN Ops` folder:

| Workbook | Feeds |
|---|---|
| `neighbouring countries Pop movement data.xlsx` | the biweekly refugee series per host country |
| `Sudan IDPs.xlsx` | IDP bubbles per Sudanese state (admin1) |

Update the workbook, then rebuild step 7 only:

```powershell
docker compose exec web python manage.py run_pipeline --only s07
```

Step 7 *extends* what step 6 wrote, so if you rebuild both, always run them in
order (`--only s06,s07`).

## 4. Refreshing the MCP layers

> **This cannot run inside Docker.** MCP tools (HDX, IPC, FEWS NET, UNHCR) can
> only be called by the assistant in Claude Code, which needs the client and API
> keys. The container only re-applies what has already been cached.

The workflow is two halves:

**Half 1 — pull (on the host, in Claude Code).** Ask, for example:

> "Refresh the external MCP data for Sudan & Neighbouring countries: pull the latest IDP
> localities from HDX, the latest IPC food-security snapshots, and update the
> refugee country totals."

Claude makes the MCP calls and overwrites the caches in
`Community Centered Humanitarian Analysis Platform/data_pipeline/mcp_cache/`.

**Half 2 — rebuild (in Docker).** Press **Rebuild external layers from latest
cache** on the updater page, or:

```powershell
docker compose exec web python manage.py run_pipeline --only s06,s07
```

The updater page shows, per layer, when its cache was last pulled and when the
map layer was last built — so you can always see which half is out of date.

### What each layer needs

| Layer (`dashboard/data/`) | Source | How to refresh |
|---|---|---|
| `idp_localities.json` | IOM-DTM via **HDX** `get_idps` (admin2 "Overview") | MCP re-pull → cache |
| `ipc_areas_fs.geojson` | **IPC** `get_areas_by_analysis` (area level, per period) | MCP re-pull → cache |
| `aoi_ipc.geojson` | **IPC** `get_areas` + HSP boundaries | MCP re-pull → `build_aoi_ipc` → cache |
| `refugee_camps.json` | UNHCR via **HDX** `get_refugees` + Excel | edit `REF_COUNTRIES` in `s06`, then step 7 |
| `seasonal.json` | **FEWS NET** `get_seasons` | edit `SEASONAL` in `s06` |
| `crossings.json` | curated crossings tagged to `flows.json` | edit `CROSSINGS` in `s06` |

Detail for the cache-driven layers:

- **IDP localities** — call HDX `get_idps` for `SDN`, `admin_level=2`, paginating
  with `offset` (0, 4000, …) until all ~185 localities are covered; keep rows
  where `operation == "Armed Clashes in Sudan (Overview)"`; overwrite
  `mcp_cache/idps_admin2_overview.json` with the deduped Overview rows.
  Centroids come from `sdn_adm2.geojson` (geoBoundaries) and rarely change.
- **Food security (IPC)** — call IPC `list_analyses` (country `SD`, type `A`),
  then `get_areas_by_analysis` (`format=geojson`) for each analysis period, saving
  each as `mcp_cache/ipc_area_<YYYY-MM>.geojson`. Use period `C` (Current);
  if empty try `P`, then `A`. Step 6 reads every `ipc_area_*.geojson`, simplifies
  the geometry and rebuilds the layer.
- **IFRC Areas of Interest** — the AOI polygons and the country/state outlines are
  vendored from the IFRC HSP dashboard and are static. To refresh the IPC phase
  per area, call IPC `get_areas` (`format=geojson`) for TD, SS, ET, CF and UG
  (Sudan comes from the existing snapshot), then run

  ```powershell
  docker compose exec web python manage.py build_aoi_ipc
  ```

  which point-in-polygons each IPC area centroid into the AOIs and writes
  `mcp_cache/aoi_ipc_phases.json`. Step 6 merges that cache onto the
  polygons.

## 5. Auditing a number

Every figure keeps the parser that produced it (`method`), a `confidence` level
and the `snippet` it was read from.

**The easy way** — <http://localhost:2026/admin/> → *Population figures*. Filter
by metric, country or confidence, open a row, read the snippet, follow the link
to the source document.

**With SQL** — pgAdmin at <http://localhost:5050/>, or any client on
`localhost:5432` (database `sudan_neighbouring_pop_movement`, user from `.env`):

```sql
-- where did a number come from?
SELECT d.file_name, f.value, f.method, f.snippet
FROM population_figures f JOIN documents d ON d.id = f.document_id
WHERE f.country = 'Chad' AND f.metric = 'cumulative_arrivals'
ORDER BY f.report_date DESC LIMIT 10;

-- documents dated only by file-modified time (the weakest evidence)
SELECT file_name, report_date FROM documents WHERE date_source = 'mtime';

-- how many figures each parser produced
SELECT method, confidence, COUNT(*) FROM population_figures
GROUP BY method, confidence ORDER BY 3 DESC;
```

**Over HTTP** — `http://localhost:2026/api/figures/?metric=idps&country=Sudan`.

If a wrong value reaches the dashboard, find it with the query above and fix the
*parser* in `s03_parse.py` — deleting the row alone will not last, because
`--reparse` rebuilds it.

## 6. Database care

```powershell
# back up
docker compose exec db pg_dump -U sudan sudan_neighbouring_pop_movement > backup.sql

# restore into an empty database
docker compose exec -T db psql -U sudan sudan_neighbouring_pop_movement < backup.sql
```

- PostgreSQL data lives in the Docker volume `pgdata`. It survives
  `docker compose down`; only `docker compose down -v` destroys it.
- Changing a password is **not** a reason to run `down -v`. Rotate it in place
  with `ALTER USER` — see "Rotating the passwords" in `README.md`.
- The volume is deliberately **not** a folder inside this repository: the repo
  sits in a OneDrive-synced directory, and letting OneDrive sync live database
  files corrupts them.
- `pg_dump` above is the only backup of the database. Take one before any
  migration or bulk edit; PostgreSQL is now the single source of truth (the
  pre-migration SQLite archive was removed once PostgreSQL had absorbed it).
- The source PDFs can be archived at any time — the full text stays in
  `document_text`.

To change the table structure:

```powershell
# 1. edit Community Centered Humanitarian Analysis Platform/data_track/models.py
docker compose exec web python manage.py makemigrations data_track
docker compose exec web python manage.py migrate
```

## 7. Things that still need a human

- **Curated events** — the extractor catches incident sentences automatically, but
  defining milestones (a city falling, a famine declaration) deserve a
  hand-written entry in `s04_events.py` with a severity rating.
- **New document layouts** — if UNHCR redesigns a series (it has happened twice
  with the returns dashboards), spot-check the new files and extend the matching
  parser in `s03_parse.py`. Detection is content-based, so old layouts keep
  working.
- **Estimate revisions** — big jumps (Egypt 500K → 1.2M) are accepted only once
  later reports confirm them, so a genuine revision appears after the next one or
  two documents. This lag is deliberate.

## 8. Rebuilding the documentation

The Word manual is generated from a script, so it can be regenerated whenever the
project changes:

```powershell
docker compose exec web python /docs/build_docs.py
```

It writes `docs/Community_Centered_Humanitarian_Analysis_Documentation.docx`.
