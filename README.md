# Sudan Crisis — Population Movement Tracker (PoP MVT)

An automated information-management workflow that turns the UNHCR situation-report
archive (the `UNHCR Regional Population Movement pdfs` and `UNHCR Sudan only pdfs`
folders) into:

1. **A structured story database** (`database/sudan_story.db`, SQLite) that preserves
   the full text and the extracted figures, flows, events and thematic tags of every
   document — the story survives even if the source PDFs are deleted.
2. **An interactive web platform** (`platform/`) with a draggable timeline that
   replays the crisis from 15 April 2023 to today: movement routes and direction,
   cumulative numbers, key events, and toggles for hazards, vulnerabilities,
   coping mechanisms, needs and movement patterns.

```
PoP MVT Tracker/
├── pipeline/            Python ETL (catalog → extract → parse → events → export)
│   ├── common.py        shared helpers: family classification, date parsing
│   ├── gazetteer.json   ~90 locations + movement corridors with coordinates
│   ├── taxonomy.json    keyword taxonomy behind the thematic toggles
│   ├── s01_catalog.py   inventory all PDFs (family, country, report date, sha1)
│   ├── s02_extract_text.py  full text of every page → database
│   ├── s03_parse.py     population figures, corridor flows, thematic tags
│   ├── s04_events.py    curated milestones + events extracted from narratives
│   ├── s05_export.py    database → platform/data/*.json
│   └── run_all.py       run everything
├── database/
│   ├── schema.sql       the database design (documented)
│   └── sudan_story.db   THE story database (SQLite — portable, serverless)
└── platform/            static site → deploy to GitHub Pages as-is
    ├── index.html
    ├── css/app.css
    ├── js/app.js
    └── data/*.json      exported snapshots the platform reads
```

## Why SQLite?

A single portable file, no server to maintain, queryable with any SQL tool
(DB Browser for SQLite, Python, Power BI via ODBC). It is the archival master:
`document_text` stores every page of every PDF, so analyses remain reproducible
after documents are deleted. The platform itself reads lightweight JSON exports,
so GitHub Pages (static hosting) works with no backend.

## Updating with new documents

Drop new PDFs into the year folders of the two UNHCR collections, then:

```powershell
cd "PoP MVT Tracker\pipeline"
python run_all.py          # incremental — only new files are processed
```

Re-tune parsers/taxonomy without re-reading PDFs:

```powershell
python run_all.py --reparse
```

Requirements: Python 3.10+ with `pymupdf` (`pip install pymupdf`).

## Viewing the platform locally

Static hosting is required for `fetch()` of the JSON files:

```powershell
cd "PoP MVT Tracker\platform"
python -m http.server 8080
# open http://localhost:8080
```

## Deploying to GitHub Pages

A Pages workflow (`.github/workflows/pages.yml`) publishes the `platform/`
folder on every push. One-time setup:

```powershell
cd "PoP MVT Tracker"
gh repo create sudan-pop-mvt-tracker --public --source . --push
```

then in the repository UI: **Settings → Pages → Source: GitHub Actions**
(or `gh api -X POST repos/{owner}/sudan-pop-mvt-tracker/pages -f build_type=workflow`).
Everything under `platform/` is self-contained (MapLibre GL is loaded from a
CDN; the basemap is the free CARTO dark style).

## Data model (database/schema.sql)

| table              | what it holds                                                        |
|--------------------|----------------------------------------------------------------------|
| documents          | every PDF: family/series, country focus, report date, hash           |
| document_text      | full raw text per page (archival copy of the corpus)                 |
| population_figures | extracted observations: arrivals, IDPs, returns, displaced totals    |
| movement_flows     | corridor time series (origin/destination, direction, cumulative)     |
| events             | timeline: curated milestones + extracted incident sentences          |
| narrative_tags     | hazard / vulnerability / coping / need / movement-pattern mentions   |
| locations          | gazetteer used for geocoding                                         |

Every extracted figure keeps its `method`, `confidence` and source `snippet`, and
links back to `documents` — so any number on the platform can be audited to the
sentence it came from.

## Known limitations

- Power BI map exports scatter text, so per-country figures are matched to the
  nearest country label geometrically; implausible values are rejected by bounds
  and a monotonicity filter at export. Always check `method`/`confidence` before
  citing a figure.
- Narrative-regex figures (`narrative_regex`) are indicative; the weekly-mapping
  and CORE-series parsers are the authoritative time series.
- Events with `source='extracted'` are verbatim sentences from the reports;
  curated milestones (`source='curated'`) were cross-checked against the corpus.
