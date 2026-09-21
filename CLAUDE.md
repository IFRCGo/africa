# Working in this repository

The Community Centered Humanitarian Analysis Platform: a Django + PostGIS
application that reads humanitarian documents and APIs into a database and draws
the result on a MapLibre dashboard.

Everything runs in Docker. There is no Django environment on the host:

    docker compose exec web python manage.py <command>
    docker compose exec web python manage.py test <app> -v 2

## The two jobs an agent does here

### 1. Pull external data

**For a person, the route in is Admin → Model Context Protocol (MCP) → Data
sources.** Each row carries its last pull and its newest data date, and every
API-backed row has a **Pull now** button that fetches, saves the raw response
under `data_pipeline/mcp_cache/`, and loads it. Rebuilding the dashboard
afterwards is a **separate** button on that page, so the database and the map
move only when you say so.

From a terminal, the same thing, and this is what the button runs:

    docker compose exec web python manage.py refresh_external <source> <dataset> --iso3 <ISO3>

Those buttons call the upstream APIs **directly**, because the container cannot
run the MCP servers: they are Node scripts on a host share that is not mounted
into it. The payloads are identical — every MCP tool this project uses is a
pass-through wrapper ending in `return response.data` — but the distinction
matters the day a fetcher and its tool disagree. Fetchers live in
`external_data/fetchers/`, mirroring `loaders/`; each records the tool it
reproduces. `IPC_API_KEY` and `HDX_API_TOKEN` go in `.env` (the HDX one also
covers the `unhcr` rows); FEWS NET needs no key. Design:
`docs/superpowers/specs/2026-09-15-mcp-data-sources-admin-design.md`.

**IPC pulls are filtered, and not only by what is held.** `known_ids` says what
loaded; `skipped_ids` says what a person deliberately excluded, plus anything
that came back empty. Without the second list a refresh re-pulls every
exclusion — Chad's March 2024 displaced-population analysis among them — and
retries the known-empty analyses forever.

`.mcp.json` in this folder configures five humanitarian MCP servers — `hdx`,
`fewsnet`, `ifrc-go`, `unhcr-refugees`, `ipc`. Claude Code reads it
automatically; nothing else needs configuring.

**For an agent, and for the sources with no fetcher** (`excel`, `kobo`,
`acaps`), the rule is unchanged — **fetch, save, then load**, never fetch
straight into the database:

1. Check what is already held: `manage.py external_status`.
2. Call the MCP tool for what is missing or newer.
3. Save the raw response under `data_pipeline/mcp_cache/`.
4. Load it: `manage.py load_external <dataset> <path> --iso3 <ISO3>`.

Loaders live in `external_data/loaders/`; `external_data/loaders/base.py` states
the four guarantees each one keeps.

**Never pull two IPC countries in parallel.** Recorded incident: the connection
closed and the server stayed down for the rest of the session.

### 2. Extract community insights from documents

Read `insights/prompts/extract_insights.md` and follow it exactly. That file is
the single source of truth for the extraction and its output format; this section
does not restate it.

The route in for a person is **Admin → Community insights → Part 1 — Documents →
insights**: pick files or a folder from a native window on your own machine,
**read them** (step 2, below), extract (watchable, and it survives the tab
closing), then review and publish. Part 2 is the statement table, for typing one
in by hand and for auditing anything ever published.

**Documents are read with Docling before the model sees them.** Step 2, "Read
these documents", converts each PDF or Word file to per-page markdown — reading
order, tables and headings kept, scanned pages OCR'd — and **replaces** the
PyMuPDF text intake wrote. That replacement is the point: `verify.py` re-matches
every quote against the same `DocumentText` rows the model read, so the two must
never diverge. Terminal equivalent, and what the button runs:

    docker compose exec web python manage.py convert_documents --job <N>

Three things about it that are not guessable:

- **A document Docling cannot read keeps its intake text** and is badged "Docling
  failed" on the preview. A re-read always tries Docling again first — the
  fallback is never sticky.
- **A document that already has a non-rejected insight is refused.** Moving the
  page text under a quote that was verified against it would invalidate that
  check with nothing left to say so. The practical cost: a batch already
  extracted from PyMuPDF text cannot be upgraded without rejecting its pending
  queue first.
- **OCR languages are not a free combination.** EasyOCR will not load Arabic
  beside any other non-English language, and one pass has one language list, so
  `DOCLING_OCR_LANGS` is `en,ar` or `en,fr`, not both. Both sets of weights are
  in the image; switching is a `.env` edit and a restart.

`ExtractionJob.status` reads `collecting → collected → converting → converted →
queued → running → loaded`. **`queued` means converted and ready to extract**,
not "files are in".

An archive already sitting on a mounted share should be registered as an
`InsightFolder` instead — nothing is copied that way. Which folders may be
browsed is `INSIGHT_DOCUMENT_ROOTS`; there is no hardcoded `/work` any more, and
the host folder behind the mount is `SOURCE_HOST_DIR`.

## Things worth knowing before changing anything

- `/work` is mounted **read-only**. Anything written goes under `/app`.
- **`web` runs gunicorn, which never autoreloads. After a model change, run
  `docker compose restart web`** — migrating alone is not enough. The symptom is
  not a stale page: `AddField` sets a DB default only to backfill it and then
  drops it, so a worker that booted before the field existed omits the column
  from its INSERT and the next request raises
  `NotNullViolation: null value in column "<field>"`. `manage.py test` forks a
  fresh process, so the whole suite stays green while the running site is broken.
- `data_pipeline/steps/s03_parse.py` deletes and rebuilds `population_figures`,
  `movement_flows` and `narrative_tags` on every run, and `s04_events.py` deletes
  every row in `events`. Do not put hand-curated data in those tables.
- The `insights` app is never written to by any pipeline step. That is deliberate.
- Settings use `os.environ.get(X, default)` by default; use `get(X) or default` (or `env_path()`) only when an empty .env value must fall back to the default instead of being treated as empty.
- Specs are in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`.
