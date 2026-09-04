# `data_track/` — the data tables

This app **is** the database. Every number the dashboard shows is stored in one
of the seven tables defined here, and nothing else in the project defines a
table. If you want to know what the system actually holds, this is the folder.

Two ways to look at the data:

- **<http://localhost:2026/admin/>** — browse and edit every table by hand.
  In the sidebar the group is called **Data tables (documents, text, figures, flows, tags, events, locations)**.
- **<http://localhost:2026/api/>** — the same data as read-only JSON, built live
  from PostgreSQL.

## The seven tables

Each table is one Python class in `models.py`. The **table name** column is the
real name in PostgreSQL — that is what you type in pgAdmin, psql, Power BI or
QGIS.

| Table name in PostgreSQL | Class in `models.py` | One row is | Filled by |
|---|---|---|---|
| `documents` | `Document` | one source PDF: where it came from, what it covers, its date | pipeline step 1 |
| `document_text` | `DocumentText` | one page of one PDF, as raw text | step 2 |
| `population_figures` | `PopulationFigure` | one population number read out of a report, with the sentence it came from | step 3 |
| `movement_flows` | `MovementFlow` | one movement corridor at one date — what draws the arrows on the map | step 3 |
| `narrative_tags` | `NarrativeTag` | one mention of a theme in a report — what the dashboard's toggles filter on | step 3 |
| `events` | `Event` | one dated milestone or incident on the timeline | step 4 |
| `locations` | `Location` | one place: name, coordinates, alternate spellings | step 3, from `data_pipeline/gazetteer.json` |

`documents` is the parent of all of them: every other table except `locations`
points back at a document, so any figure on the dashboard can be traced to the
PDF and page it came from.

## What is in here

```
data_track/
├── models.py      the seven tables above - the single definition of the data
├── admin.py       how each table looks and is searched at /admin/
├── views.py       the read-only JSON API
├── urls.py        which address serves which API view
└── migrations/    Django's record of how the tables were built
```

## The JSON API

Mounted at `/api/` by `config/urls.py`. Open `/api/` in a browser for the index.

| Address | Returns |
|---|---|
| `/api/meta/` | row counts and the date range held |
| `/api/documents/` | the catalogue of source PDFs |
| `/api/figures/` | population figures |
| `/api/flows/` | movement corridors |
| `/api/events/` | the timeline |
| `/api/tags/` | narrative themes |
| `/api/headline/` | the headline totals |

Note the dashboard does **not** use this API — it reads the pre-built files in
`dashboard/data/` instead, so the map stays fast. The API is for other tools
(Power BI, Excel, a notebook) that want live data.

## Changing a table

Editing `models.py` is not enough on its own; PostgreSQL has to be told too:

```powershell
docker compose exec web python manage.py makemigrations data_track
docker compose exec web python manage.py migrate
```

Back up first — `pg_dump` is in `MAINTENANCE.md` section 6.
