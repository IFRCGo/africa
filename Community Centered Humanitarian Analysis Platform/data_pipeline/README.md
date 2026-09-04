# `data_pipeline/` — how raw sources become the dashboard

This app has **no web address**. It is the machinery that fills the database and
writes the files the dashboard draws. You run it either from the Update now page
at <http://localhost:2026/updater/> or on the command line:

```powershell
docker compose exec web python manage.py run_pipeline          # everything
docker compose exec web python manage.py run_pipeline --list   # show the steps
```

## The one thing to understand first

The pipeline has **two halves, and only one of them is automatic.**

| | Where the data comes from | Who fetches it |
|---|---|---|
| **Steps 1–5** | the UNHCR PDFs in the source folders | fully automatic — the pipeline reads the PDFs itself |
| **Step 6** | the humanitarian MCP servers (HDX, IPC, FEWS NET, UNHCR) | **a person**, not this app |

**The MCP calls are not made by this application.** MCP tools can only be called
by the assistant at runtime, so they cannot run inside a web container. An
analyst runs them in Claude Code, saves the results into `mcp_cache/`, and the
pipeline only ever *re-reads that folder*. Pressing "Rebuild external layers" on
the updater page rebuilds the map layers from whatever is already cached — it
does **not** go and fetch anything new.

To actually refresh the numbers, follow "Refreshing the MCP layers" in
`MAINTENANCE.md`, then run step 6 again.

## What is in here

```
data_pipeline/
├── steps/                    the seven steps, in the order they must run
│   ├── s01_catalog.py        find new PDFs and record them
│   ├── s02_extract_text.py   read their text into the database (the slow one)
│   ├── s03_parse.py          pull out figures, corridors and themes
│   ├── s04_events.py         rebuild the timeline
│   ├── s05_export.py         write the dashboard's JSON files
│   ├── s06_mcp_layers.py     rebuild the map layers from mcp_cache/  ← the MCP half
│   ├── s07_xlsx.py           merge in the Excel workbook
│   └── _build_aoi_ipc.py     helper for s06: match IFRC Areas of Interest to IPC phases
│
├── mcp_cache/                THE RAW MCP PULLS - refreshed by an analyst, not by this app
├── gazetteer.json            ~90 place names, coordinates and the corridors between them
├── taxonomy.json             the keyword lists behind the dashboard's theme toggles
├── common.py                 shared folder paths, report families, date/number parsing
└── management/commands/      what `manage.py` exposes:
    ├── run_pipeline.py       run the steps
    └── build_aoi_ipc.py      recompute Area-of-Interest IPC phases (helper, not a step)
```

## Where each step writes

Steps 1–4 write into the database (see `data_track/README.md`). Steps 5–7 write
JSON and GeoJSON into `dashboard/data/`, which is what the map actually loads.

Steps 1 and 2 only ever *add*, so re-running them is safe. Steps 3–7 rebuild
what they own from scratch — which is why `--reparse` (steps 3–7) is the right
choice after editing a parser, `gazetteer.json` or `taxonomy.json`.
