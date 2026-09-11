# Working in this repository

The Community Centered Humanitarian Analysis Platform: a Django + PostGIS
application that reads humanitarian documents and APIs into a database and draws
the result on a MapLibre dashboard.

Everything runs in Docker. There is no Django environment on the host:

    docker compose exec web python manage.py <command>
    docker compose exec web python manage.py test <app> -v 2

## The two jobs an agent does here

### 1. Pull external data through the MCP servers

`.mcp.json` in this folder configures five humanitarian MCP servers — `hdx`,
`fewsnet`, `ifrc-go`, `unhcr-refugees`, `ipc`. Claude Code reads it
automatically; nothing else needs configuring.

The rule is **fetch, save, then load** — never fetch straight into the database:

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

## Things worth knowing before changing anything

- `/work` is mounted **read-only**. Anything written goes under `/app`.
- `data_pipeline/steps/s03_parse.py` deletes and rebuilds `population_figures`,
  `movement_flows` and `narrative_tags` on every run, and `s04_events.py` deletes
  every row in `events`. Do not put hand-curated data in those tables.
- The `insights` app is never written to by any pipeline step. That is deliberate.
- Settings use `os.environ.get(X, default)` by default; use `get(X) or default` (or `env_path()`) only when an empty .env value must fall back to the default instead of being treated as empty.
- Specs are in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`.
