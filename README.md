# Sudan & Neighbouring countries — Community Centered Humanitarian Analysis

Turns a folder of UNHCR situation reports into an interactive map you can drag
through time, from 15 April 2023 to today.

A **Django** application, a **PostgreSQL** database and **pgAdmin**, all running
in **Docker**. Start it with one command.

| | |
|---|---|
| Dashboard | <http://localhost:2026/> |
| One-click updater | <http://localhost:2026/updater/> |
| Database admin | <http://localhost:2026/admin/> |
| JSON API | <http://localhost:2026/api/> |
| pgAdmin | <http://localhost:5050/> |

Full documentation, written for a non-developer:
**[`docs/Community_Centered_Humanitarian_Analysis_Documentation.docx`](docs/Community_Centered_Humanitarian_Analysis_Documentation.docx)**

---

## Getting started

You need Docker Desktop. Nothing else.

```powershell
# 1. Create your settings file and change the three passwords in it
Copy-Item env.example .env          # macOS/Linux: cp env.example .env

# 2. Start everything
docker compose up -d --build

# 3. Fill the empty database (first time only) - pick one:
#    a) restore a dump taken from an existing instance (minutes)
docker compose exec -T db psql -U sudan sudan_neighbouring_pop_movement < backup.sql
#    b) or build everything from the source PDFs (hours, but needs no dump)
docker compose exec web python manage.py run_pipeline
```

Then open <http://localhost:2026/>.

Step 3 gives the empty PostgreSQL database its contents. Option (a) is the
normal route — take `backup.sql` from a running instance with the `pg_dump`
command shown under "Rotating the passwords" below (also in `MAINTENANCE.md`
section 6). Option (b) is the fallback when no dump is at hand: `run_pipeline`
re-reads every PDF under the source folders and rebuilds all seven tables from
scratch — including `locations`, which step 3 regenerates from
`data_pipeline/gazetteer.json`. It is slow (PDF text extraction dominates) but
complete.

## The three containers

| Service | What it is | Address |
|---|---|---|
| `db` | PostgreSQL 16 — stores everything | `localhost:5432` |
| `web` | Django — dashboard, updater, admin, API, pipeline | <http://localhost:2026> |
| `pgadmin` | pgAdmin 4 — browse and query the database | <http://localhost:5050> |

All passwords and ports live in **`.env`** (git-ignored, so it never reaches GitHub; `env.example`
is the committed template). Every setting in it is explained in chapter 4 of the Word
document.

## The database connection

**No database, and no credential, travels with this repository.** The connection
is assembled at start-up from five environment variables and nothing else:

| Variable | Default if unset | What it is |
|---|---|---|
| `POSTGRES_HOST` | `db` (the bundled container) | where PostgreSQL is |
| `POSTGRES_PORT` | `5432` | its port |
| `POSTGRES_DB` | `sudan_neighbouring_pop_movement` | the database name |
| `POSTGRES_USER` | `sudan` | the login |
| `POSTGRES_PASSWORD` | **none — you must set it** | the password |

They are read in exactly one place, `config/settings.py` under
"4. The database", and passed in by `docker-compose.yml` from your `.env`.
There is no connection string anywhere in the code, and `.env` is git-ignored,
so cloning this repository gives you the application and none of the data.

`POSTGRES_PASSWORD` deliberately has **no fallback**. A default password in a
public repository is not a password, and a fallback would let a fresh clone
appear to work while quietly using one. Instead both Docker Compose and Django
stop straight away and tell you what to set.

### Pointing it at your own PostgreSQL

Uncomment `POSTGRES_HOST` and `POSTGRES_PORT` in `.env` and fill in your
server. The bundled `db` container then just sits unused — you can ignore it.
Tables are created for you:

```powershell
docker compose exec web python manage.py migrate
```

If your PostgreSQL runs on your own machine but outside Docker, use
`POSTGRES_HOST=host.docker.internal` — inside a container `localhost` means the
container itself, not your computer. That name resolves on Docker Desktop
(Windows/macOS); on Linux with plain Docker Engine, add
`extra_hosts: ["host.docker.internal:host-gateway"]` to the `web` service.

Note the dashboard's JSON files in `dashboard/data/` *are* committed, so a
fresh clone shows a populated map before you connect anything. Those are
exported snapshots; the live data lives only in your PostgreSQL.

## Rotating the passwords

Editing `.env` is **not enough on its own**. PostgreSQL and pgAdmin each store
the credentials they were first created with inside their own volume, so a new
value in `.env` only changes what the containers *offer*, not what the servers
*expect*. The two then disagree and the dashboard stops connecting.

`docker compose down -v` does make them agree again — by deleting the database.
Never use it to change a password. Do this instead, which keeps every row:

```powershell
# 1. Back up first - one file, restores everything if a step goes wrong
docker compose exec -T db pg_dump -U sudan sudan_neighbouring_pop_movement > backup.sql

# 2. Put the new values in .env (letters, digits, - and _ only:
#    Compose reads $ as interpolation and # as a comment)

# 3. Tell PostgreSQL its new password. Inside the container this connects
#    over a trusted local socket, so the old password is not needed.
docker compose exec -T db psql -U sudan -d sudan_neighbouring_pop_movement `
  -c "ALTER USER sudan WITH PASSWORD 'THE-NEW-PASSWORD';"

# 4. Tell pgAdmin its new password, keeping saved servers and preferences.
#    --role is required: without it the command fails with KeyError: 'role'.
#    Use /venv/bin/python - the system python has no typer module.
docker compose exec -T pgadmin /venv/bin/python /pgadmin4/setup.py `
  update-user admin@example.org --password THE-NEW-PASSWORD --role Administrator

# 5. Restart so the containers pick up .env. NOT "down -v".
docker compose up -d
```

Then check it worked. Connect through the service name **`db`**, not
`localhost`: `pg_hba.conf` trusts loopback, so a `127.0.0.1` connection accepts
*any* password and would look like success even if nothing changed. Only the
`db` route exercises the real `scram-sha-256` rule.

```powershell
# must succeed
docker compose exec -T db psql "postgresql://sudan:THE-NEW-PASSWORD@db:5432/sudan_neighbouring_pop_movement" -c "SELECT 1;"

# must fail with "password authentication failed" - if it succeeds, the
# password did not actually change
docker compose exec -T db psql "postgresql://sudan:THE-OLD-PASSWORD@db:5432/sudan_neighbouring_pop_movement" -c "SELECT 1;"
```

The Django `/admin/` password is not part of this: Django stores its own hash.
`DJANGO_SUPERUSER_PASSWORD` in `.env` is read **only** when no superuser exists
yet. To change it afterwards:

```powershell
docker compose exec web python manage.py changepassword admin
```

Changing `DJANGO_SECRET_KEY` is safe at any time — it only signs out anyone
currently logged in.

## Adding new reports

Drop the PDFs into a year folder of either UNHCR collection, then open
<http://localhost:2026/updater/> and press **Update now**. A progress bar follows
the pipeline and the dashboard preview reloads when it finishes.

The same thing from the command line:

```powershell
docker compose exec web python manage.py run_pipeline            # ingest new PDFs
docker compose exec web python manage.py run_pipeline --reparse  # re-parse only
docker compose exec web python manage.py run_pipeline --list     # show the steps
```

## How it works

```
UNHCR PDFs  ──▶  pipeline (7 steps)  ──▶  PostgreSQL  ──▶  dashboard/data/*.json  ──▶  the map
```

| Step | File | Does |
|---|---|---|
| 1 | `s01_catalog.py` | find new PDFs, work out series/country/date |
| 2 | `s02_extract_text.py` | store every page of text (the archive) |
| 3 | `s03_parse.py` | extract figures, corridors and themes |
| 4 | `s04_events.py` | rebuild the timeline |
| 5 | `s05_export.py` | write the dashboard files |
| 6 | `s06_mcp_layers.py` | rebuild the external map layers |
| 7 | `s07_xlsx.py` | merge in the Excel layers |

The dashboard reads the exported JSON rather than querying the database, which
keeps the map fast: the browser fetches a handful of small files instead of
waiting on SQL. For live database access there is a read-only JSON API at
`/api/`.

## Layout

Every folder in the application is named after the job it does. The two you
open in a browser are `dashboard/` and `updater/`; the two behind them are
`data_track/` (what is stored) and `data_pipeline/` (how it got there).

```
Community Centered Humanitarian Analysis/
├── docker-compose.yml        the three containers
├── .env                      YOUR credentials and ports (never committed)
├── env.example               the template to copy it from
├── Community Centered Humanitarian Analysis Platform/         THE APPLICATION
│   │
│   ├── dashboard/            ── serves  http://localhost:2026/          THE MAP
│   │   ├── templates/dashboard/index.html    the page
│   │   ├── static/dashboard/css|js           its styling and behaviour
│   │   ├── data/                             the JSON/GeoJSON the map fetches
│   │   └── urls.py  views.py
│   │
│   ├── updater/              ── serves  /updater/          THE UPDATE NOW PAGE
│   │   ├── templates/updater/index.html      the page
│   │   ├── static/updater/css|js             its styling and behaviour
│   │   └── urls.py  views.py                 runs the pipeline, streams progress
│   │
│   ├── data_track/           ── serves  /api/  and  /admin/     THE DATA TABLES
│   │   ├── README.md         what each of the seven tables holds
│   │   ├── models.py         one class per table - the only place they are defined
│   │   ├── admin.py          how each table looks at /admin/
│   │   └── views.py  urls.py the read-only JSON API
│   │
│   ├── data_pipeline/        ── no web address              HOW THE DATA IS BUILT
│   │   ├── README.md         the seven steps, and which half is NOT automatic
│   │   ├── steps/s01..s07    catalogue → text → parse → events → export → MCP → Excel
│   │   ├── api_cache/        raw MCP pulls, refreshed by an analyst (see README)
│   │   ├── gazetteer.json    ~90 places and the corridors between them
│   │   ├── taxonomy.json     the keyword lists behind the theme toggles
│   │   └── management/commands/run_pipeline.py
│   │
│   └── config/               ── no web address     settings.py, urls.py (the site map)
│
└── docs/                     the Word manual and the script that builds it
```

## The database

Seven tables, defined in `Community Centered Humanitarian Analysis Platform/data_track/models.py`, all browsable at
`/admin/`.

| Table | One row is |
|---|---|
| `documents` | one source PDF |
| `document_text` | one page of one PDF, as raw text |
| `population_figures` | one number found in a report, with its evidence |
| `movement_flows` | one corridor observation at one date |
| `events` | one dated milestone or incident |
| `narrative_tags` | one mention of a theme in a report |
| `locations` | one place, with coordinates and alternate spellings |

Every figure keeps its `method`, `confidence` and the `snippet` it was read
from, so any number on the dashboard can be traced back to the sentence that
produced it.

## Map layers

| Layer | Source |
|---|---|
| Movement out of / back into Sudan | UNHCR reports |
| Key events | curated milestones + extracted sentences |
| IDP localities (admin2) | IOM-DTM via HDX |
| IDP by state (admin1) | `Sudan IDPs.xlsx` |
| Refugee totals + camps | UNHCR via HDX + Excel |
| Food insecurity (IPC phase, by area) | IPC |
| Border crossings | curated |
| Seasonal calendar | FEWS NET |
| IFRC Areas of Interest | HSP boundaries + IPC |

> **Fetching new data from the MCP servers cannot run inside Docker.** It needs
> the Claude Code client and API keys, so an analyst runs it on the host and it
> refreshes `Community Centered Humanitarian Analysis Platform/data_pipeline/api_cache/`. The **Rebuild external
> layers** button only re-applies what is already cached. See `MAINTENANCE.md`.

## Known limitations

- Power BI map exports scatter their text, so per-country figures are matched to
  the nearest country label geometrically. Implausible values are rejected by
  bounds and a monotonicity filter. Check `method` and `confidence` before
  citing a figure.
- Narrative-regex figures are indicative; the weekly-mapping and CORE-series
  parsers are the authoritative time series.
- Events with `source='extracted'` are verbatim sentences from the reports; only
  curated milestones were cross-checked against the corpus.
- Refugee magnitude is real but per *host country* — the servers do not publish
  per-camp time series. Camp dots mark locations, not counts.
- Egypt figures are UNHCR-registered only; actual presence is far larger.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `env file .env not found` | `cp env.example .env` |
| Port already in use | change `WEB_HOST_PORT` / `POSTGRES_HOST_PORT` / `PGADMIN_HOST_PORT` in `.env` |
| Dashboard is empty | run `run_pipeline`, or restore a `pg_dump` backup |
| Nothing at :2026 | `docker compose logs -f web` |
| Password change had no effect | Editing `.env` alone never changes an existing password — see [Rotating the passwords](#rotating-the-passwords). Do **not** use `down -v`: it deletes the database |

More in chapter 14 of the Word document.
