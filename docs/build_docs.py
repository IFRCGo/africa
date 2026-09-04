"""Builds the Word manual for Sudan & Neighbouring countries.

Run it whenever the project changes, so the manual never goes stale:

    docker compose exec web python /docs/build_docs.py
    # or, outside Docker, with python-docx installed:
    python docs/build_docs.py

It writes docs/Community_Centered_Humanitarian_Analysis_Documentation.docx
next to this script.

The document is assembled from the small helper functions at the top
(heading, para, bullets, table) and the CONTENT section further down. To add a
chapter, add a function and call it from build().
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

OUT_PATH = (
    Path(__file__).resolve().parent
    / "Community_Centered_Humanitarian_Analysis_Documentation.docx"
)

IFRC_RED = RGBColor(0xCC, 0x00, 0x00)
GREY = RGBColor(0x60, 0x60, 0x60)


# --------------------------------------------------------------------------
# Small helpers: one function per kind of thing we put on the page.
# --------------------------------------------------------------------------
def heading(doc, text, level=1):
    """Add a heading and colour it IFRC red."""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = IFRC_RED
    return h


def para(doc, text, bold=False, italic=False, size=10.5, color=None):
    """Add a normal paragraph."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = color
    return p


def bullets(doc, items):
    """Add a bulleted list. An item may be a plain string, or a
    (bold lead-in, rest of the sentence) pair."""
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        if isinstance(item, tuple):
            lead, rest = item
            run = p.add_run(lead)
            run.bold = True
            run.font.size = Pt(10.5)
            run2 = p.add_run(rest)
            run2.font.size = Pt(10.5)
        else:
            run = p.add_run(item)
            run.font.size = Pt(10.5)


def code(doc, lines):
    """Add a block of commands or code in a monospaced font."""
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.3)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(9)
    doc.add_paragraph()


def table(doc, headers, rows, widths=None):
    """Add a table with a bold header row."""
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, text in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(9.5)
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(value))
            run.font.size = Pt(9)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph()
    return t


# ==========================================================================
# CONTENT - one function per chapter of the manual.
# ==========================================================================
def cover(doc):
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Sudan & Neighbouring Countries")
    run.bold = True
    run.font.size = Pt(30)
    run.font.color.rgb = IFRC_RED

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("Community Centered Humanitarian Analysis")
    run.font.size = Pt(15)
    run.font.color.rgb = GREY

    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub2.add_run("Full functional documentation\nDjango - PostgreSQL - Docker")
    run.font.size = Pt(12)
    run.font.color.rgb = GREY

    doc.add_paragraph()
    para(doc,
         "This document describes every part of the system: what it does, how to run "
         "it, what each container and each file is for, every table in the database, "
         "every step of the data pipeline, every layer and control on the dashboard, "
         "and every setting you can change. It is written to be readable by someone "
         "who has never opened the code.",
         size=11)
    doc.add_page_break()


def chapter_overview(doc):
    heading(doc, "1. What this system is", 1)
    para(doc,
         "The platform turns a folder of UNHCR situation reports "
         "into a living picture of the Sudan displacement crisis. It reads the PDFs, "
         "pulls the numbers and the narrative out of them, stores everything in a "
         "database, and publishes an interactive map you can drag through time from "
         "15 April 2023 to today.")

    heading(doc, "1.1 The three things it produces", 2)
    bullets(doc, [
        ("A story database. ",
         "Every report, every page of its text, every figure, every movement "
         "corridor, every event and every theme mentioned. Because the full page "
         "text is stored, the analysis stays reproducible even if the original PDFs "
         "are deleted."),
        ("An interactive dashboard. ",
         "A map with a timeline slider that replays the crisis: movement arrows and "
         "their direction, cumulative numbers, key events, and toggles for hazards, "
         "vulnerabilities, coping mechanisms, needs and movement patterns."),
        ("Open-data map layers. ",
         "Food insecurity, IDP counts, refugee totals, border crossings, the "
         "seasonal calendar and the IFRC Areas of Interest, all animated on the "
         "same timeline."),
    ])

    heading(doc, "1.2 Who does what", 2)
    table(doc,
          ["Person", "What they use", "Where"],
          [["Analyst / reporting officer", "Reads the dashboard, drags the timeline",
            "http://localhost:2026/"],
           ["Information manager", "Drops new PDFs in, presses Update now",
            "http://localhost:2026/updater/"],
           ["Data officer", "Browses and corrects rows in the database",
            "http://localhost:2026/admin/"],
           ["Analyst with SQL / Power BI", "Queries PostgreSQL directly",
            "localhost:5432, or pgAdmin at :5050"],
           ["Developer", "Changes parsers, layers or the site",
            "Community Centered Humanitarian Analysis Platform/ in this repository"]],
          widths=[1.9, 2.7, 2.0])
    doc.add_page_break()


def chapter_architecture(doc):
    heading(doc, "2. How it is put together", 1)
    para(doc,
         "Everything runs in Docker. Three containers start together and talk to "
         "each other on a private network that Docker creates for them.")

    table(doc,
          ["Container", "Image", "What it does", "Your address"],
          [["db", "postgres:16-alpine",
            "Stores every table. Its files live in a Docker volume called pgdata.",
            "localhost:5432"],
           ["web", "built from Community Centered Humanitarian Analysis Platform/Dockerfile",
            "Runs Django: the dashboard, the updater, the admin site, the JSON API "
            "and the data pipeline.",
            "http://localhost:2026"],
           ["pgadmin", "dpage/pgadmin4",
            "A web interface for looking inside PostgreSQL: run SQL, browse tables, "
            "export CSV.",
            "http://localhost:5050"]],
          widths=[1.0, 1.7, 3.2, 1.3])

    heading(doc, "2.1 The path a number takes", 2)
    para(doc,
         "A figure printed in a UNHCR PDF reaches the dashboard like this:")
    code(doc, [
        "UNHCR PDF in the SUDAN Ops folder",
        "   |  step 1  catalogue it        -> documents table",
        "   |  step 2  read its text       -> document_text table",
        "   |  step 3  parse the numbers   -> population_figures, movement_flows,",
        "   |                                 narrative_tags tables",
        "   |  step 4  build the timeline  -> events table",
        "   |  step 5  export              -> dashboard/data/*.json",
        "   |  steps 6-7  external layers  -> dashboard/data/*.geojson",
        "   v",
        "the map at http://localhost:2026/",
    ])
    para(doc,
         "The dashboard reads the exported files rather than querying the database "
         "directly. That keeps the map fast: the browser fetches a handful of small "
         "files instead of waiting on SQL. For live database access there is a "
         "separate JSON API, described in chapter 8.")

    heading(doc, "2.2 Why PostgreSQL", 2)
    bullets(doc, [
        "Several people can read and write at the same time, which a single file "
        "database cannot do safely.",
        "It is a real server, so Power BI, Excel, DBeaver, QGIS and Python can all "
        "connect to it over the network.",
        "Django manages the table structure through migrations, so a change to "
        "models.py is applied to the database in a controlled, repeatable way.",
        "It backs up to a single portable file with pg_dump, which is also how a "
        "second instance is seeded (see 12.4).",
    ])
    doc.add_page_break()


def chapter_quickstart(doc):
    heading(doc, "3. Getting it running", 1)
    para(doc, "You need Docker Desktop, and nothing else.", bold=True)

    heading(doc, "3.1 First time", 2)
    code(doc, [
        "# 1. Create your settings file from the template",
        "Copy-Item env.example .env        # PowerShell",
        "cp env.example .env               # macOS / Linux",
        "",
        "# 2. Open .env and change the three passwords",
        "",
        "# 3. Start everything",
        "docker compose up -d --build",
        "",
        "# 4. Fill the empty database (once only) - pick one:",
        "#    a) restore a dump taken from an existing instance (minutes)",
        "docker compose exec -T db psql -U sudan sudan_neighbouring_pop_movement < backup.sql",
        "#    b) or rebuild from the source PDFs (hours, needs no dump)",
        "docker compose exec web python manage.py run_pipeline",
    ])
    para(doc,
         "The web container waits for the database, creates the tables and starts "
         "the site by itself, but the tables start out empty. Option (a) is the "
         "normal route: take backup.sql from a running instance with the pg_dump "
         "command in 12.4. Option (b) is the fallback when no dump is at hand - "
         "run_pipeline re-reads every PDF and rebuilds all seven tables from "
         "scratch (locations is regenerated from data_pipeline/gazetteer.json by "
         "step 3), slowly but completely.")

    heading(doc, "3.2 Every day", 2)
    table(doc,
          ["To do this", "Go here"],
          [["Look at the dashboard", "http://localhost:2026/"],
           ["Ingest new PDFs", "http://localhost:2026/updater/"],
           ["Browse or fix the data", "http://localhost:2026/admin/"],
           ["Run SQL against the database", "http://localhost:5050/ (pgAdmin)"],
           ["Read live JSON", "http://localhost:2026/api/"]],
          widths=[3.0, 3.6])

    heading(doc, "3.3 Useful commands", 2)
    code(doc, [
        "docker compose up -d              start everything",
        "docker compose down               stop everything (data is kept)",
        "docker compose logs -f web        watch what Django is doing",
        "docker compose restart web        restart just Django",
        "",
        "docker compose exec web python manage.py run_pipeline",
        "docker compose exec web python manage.py run_pipeline --reparse",
        "docker compose exec web python manage.py run_pipeline --list",
        "docker compose exec web python manage.py createsuperuser",
        "",
        "docker compose down -v            DELETE the database as well - careful",
    ])
    doc.add_page_break()


def chapter_env(doc):
    heading(doc, "4. The .env file - every setting explained", 1)
    para(doc,
         "All credentials and ports live in one file called .env in the project "
         "root. Docker Compose reads it automatically. It is listed in .gitignore, "
         "so it is never committed; the template env.example is committed instead. "
         "If a value is missing, the defaults shown below are used.")

    table(doc,
          ["Setting", "What it controls", "Default"],
          [["POSTGRES_DB", "Name of the database", "sudan_neighbouring_pop_movement"],
           ["POSTGRES_USER", "Database user Django logs in as", "sudan"],
           ["POSTGRES_PASSWORD", "That user's password. Change it.", "sudan"],
           ["POSTGRES_HOST", "Where the database is. Inside Docker always 'db'.", "db"],
           ["POSTGRES_PORT", "Database port inside Docker", "5432"],
           ["POSTGRES_HOST_PORT", "Port on your machine for psql / Power BI", "5432"],
           ["DJANGO_SECRET_KEY", "Long random string that signs cookies. Change it.",
            "insecure dev key"],
           ["DJANGO_DEBUG", "1 shows detailed error pages; use 0 on a server", "1"],
           ["DJANGO_ALLOWED_HOSTS", "Host names the site answers to", "*"],
           ["DJANGO_CSRF_TRUSTED_ORIGINS", "Needed for https on a real domain", "(empty)"],
           ["WEB_HOST_PORT", "Port on your machine for the dashboard", "2026"],
           ["PGADMIN_DEFAULT_EMAIL", "pgAdmin login", "admin@example.org"],
           ["PGADMIN_DEFAULT_PASSWORD", "pgAdmin password. Change it.", "pgadmin"],
           ["PGADMIN_HOST_PORT", "Port on your machine for pgAdmin", "5050"],
           ["DJANGO_SUPERUSER_USERNAME", "Admin login created on first start", "admin"],
           ["DJANGO_SUPERUSER_EMAIL", "Admin email", "admin@example.org"],
           ["DJANGO_SUPERUSER_PASSWORD", "Set this to auto-create the admin login",
            "(empty = skip)"],
           ["SOURCE_ROOT", "Folder holding the UNHCR PDF collections", "/work"],
           ["DASHBOARD_DATA_DIR", "Where the pipeline writes the dashboard files",
            "/app/dashboard/data"],
           ["MCP_CACHE_DIR", "Cached pulls from the MCP servers",
            "/app/data_pipeline/mcp_cache"],
           ["POP_MOVEMENT_XLSX", "The neighbouring-countries Excel workbook",
            "(in /work)"],
           ["DASHBOARD_URL", "Link the updater page uses", "/"],
           ["TZ", "Time zone for timestamps", "UTC"]],
          widths=[2.2, 3.4, 1.4])

    para(doc,
         "Note: changing POSTGRES_USER or POSTGRES_PASSWORD after the first start "
         "has no effect on its own, because the database was already created with "
         "the old values. To apply new ones you must remove the data volume "
         "(docker compose down -v) and import again.",
         italic=True)
    doc.add_page_break()


def chapter_layout(doc):
    heading(doc, "5. What is in each folder", 1)
    code(doc, [
        "Community Centered Humanitarian Analysis/",
        "|- docker-compose.yml        the three containers, ports and volumes",
        "|- .env                     YOUR credentials and ports (never committed)",
        "|- env.example              the template to copy it from",
        "|",
        "|- Community Centered Humanitarian Analysis Platform/               THE APPLICATION",
        "|   |- manage.py             the command you run everything with",
        "|   |- Dockerfile            how the web image is built",
        "|   |- entrypoint.sh         waits for the DB, migrates, starts gunicorn",
        "|   |- requirements.txt      the Python packages, with reasons",
        "|   |",
        "|   |- dashboard/       -- serves  http://localhost:2026/     THE MAP",
        "|   |   |- templates/dashboard/index.html   the page skeleton",
        "|   |   |- static/dashboard/css/app.css     all styling",
        "|   |   |- static/dashboard/js/app.js       all behaviour",
        "|   |   |- data/             the JSON and GeoJSON the map fetches",
        "|   |   |- urls.py  views.py",
        "|   |",
        "|   |- updater/         -- serves  /updater/        THE UPDATE NOW PAGE",
        "|   |   |- templates/updater/index.html     the page skeleton",
        "|   |   |- static/updater/css/app.css       all styling",
        "|   |   |- static/updater/js/app.js         all behaviour",
        "|   |   |- urls.py  views.py   runs the pipeline, streams the progress",
        "|   |",
        "|   |- data_track/      -- serves  /api/ and /admin/   THE DATA TABLES",
        "|   |   |- README.md         what each of the seven tables holds",
        "|   |   |- models.py         one class per table - the only definition",
        "|   |   |- admin.py          how each table looks at /admin/",
        "|   |   |- views.py  urls.py the read-only JSON API",
        "|   |",
        "|   |- data_pipeline/   -- no web address        HOW THE DATA IS BUILT",
        "|   |   |- README.md         the steps, and which half is NOT automatic",
        "|   |   |- steps/s01..s07    the seven pipeline steps",
        "|   |   |- mcp_cache/        raw MCP pulls, refreshed by an analyst",
        "|   |   |- gazetteer.json    ~90 places and the corridors between them",
        "|   |   |- taxonomy.json     the keyword lists behind the theme toggles",
        "|   |   |- common.py         paths, report families, date/number parsing",
        "|   |   |- management/commands/run_pipeline.py",
        "|   |",
        "|   |- config/          -- no web address   settings.py, urls.py, wsgi.py",
        "|",
        "|- docs/                     this document and the script that builds it",
    ])
    doc.add_page_break()


def chapter_database(doc):
    heading(doc, "6. The database", 1)
    para(doc,
         "Seven tables. Every one of them is defined in "
         "Community Centered Humanitarian Analysis Platform/data_track/models.py, and every one is browsable at /admin/.")

    table(doc,
          ["Table", "One row is", "Rough size"],
          [["documents", "One source PDF", "~930"],
           ["document_text", "One page of one PDF, as raw text", "~4,800"],
           ["population_figures", "One number found in a report, with its evidence",
            "~2,100"],
           ["movement_flows", "One corridor observation at one date", "~1,100"],
           ["events", "One dated milestone or incident", "~80"],
           ["narrative_tags", "One mention of a theme in a report", "~21,000"],
           ["locations", "One place, with its coordinates and alternate spellings",
            "~95"]],
          widths=[1.8, 3.7, 1.4])

    heading(doc, "6.1 documents", 2)
    table(doc, ["Column", "Meaning"],
          [["file_name", "The PDF file name"],
           ["rel_path", "Its path relative to the SUDAN Ops folder. Unique - this is "
            "how we know a file has already been ingested."],
           ["source_collection", "'regional' or 'sudan_only'"],
           ["year_folder", "The year folder it sits in, used to sanity-check dates"],
           ["family", "Which report series it belongs to (weekly_mapping, chad_core, "
            "flash_update, ...). Decides which parser reads it."],
           ["country_focus", "The country the series reports on"],
           ["report_date", "The date of the report"],
           ["date_source", "How we got that date: filename, text or mtime"],
           ["pages, file_size, sha1", "Size and a fingerprint of the file contents"],
           ["extracted_at", "When we last read the text out of it"]],
          widths=[1.9, 4.9])

    heading(doc, "6.2 population_figures", 2)
    para(doc,
         "The heart of the audit trail. Every row keeps the parser that produced it, "
         "a confidence level and the sentence it came from, so any number on the "
         "dashboard can be traced to its source.")
    table(doc, ["Column", "Meaning"],
          [["report_date, country, location, lat, lon", "When and where"],
           ["metric", "What was counted: cumulative_arrivals, idps, total_displaced, "
            "returnees, returns_to_sudan_total, self_relocated, "
            "arrivals_from_south_sudan"],
           ["population_group", "sudanese_refugees, refugee_returnees, idps, mixed"],
           ["value", "The number itself"],
           ["method", "Which parser found it - for example weekly_mapping_headline, "
            "weekly_mapping_positional, narrative_regex, return_v3_row"],
           ["confidence", "high, medium or low"],
           ["snippet", "The text it was read from"],
           ["document_id", "Link back to the PDF"]],
          widths=[1.9, 4.9])

    heading(doc, "6.3 The other tables", 2)
    bullets(doc, [
        ("movement_flows: ",
         "corridor, origin and destination with coordinates, flow_type "
         "(cross_border, internal or return) and the cumulative value at that date. "
         "This is what draws the arrows."),
        ("events: ",
         "event_date, title, description, category, location, severity 1-5, and "
         "source. source='curated' means a hand-checked milestone; "
         "source='extracted' means a sentence lifted from a report."),
        ("narrative_tags: ",
         "dimension (hazard, vulnerability, coping, need, movement_pattern), tag, "
         "country and a sample sentence. Counted by month, this is what the theme "
         "toggles show."),
        ("locations: ",
         "the gazetteer, loaded from gazetteer.json, used to place figures and "
         "events on the map."),
        ("document_text: ",
         "the archive. One row per page. This is why the story survives even if the "
         "PDFs are deleted."),
    ])
    doc.add_page_break()


def chapter_pipeline(doc):
    heading(doc, "7. The data pipeline", 1)
    para(doc,
         "Seven steps, run by one command. Each step is a file in "
         "Community Centered Humanitarian Analysis Platform/data_pipeline/steps/ with a single run() function.")
    code(doc, [
        "docker compose exec web python manage.py run_pipeline",
        "docker compose exec web python manage.py run_pipeline --reparse",
        "docker compose exec web python manage.py run_pipeline --only s06,s07",
        "docker compose exec web python manage.py run_pipeline --list",
    ])

    table(doc,
          ["Step", "File", "What it does"],
          [["1", "s01_catalog.py",
            "Walks the two UNHCR folders, records every PDF it has not seen before, "
            "works out its report series, country and date, and stores a fingerprint "
            "of the file."],
           ["2", "s02_extract_text.py",
            "Opens each new PDF and stores the text of its first 40 pages. Fills in "
            "any missing date from the page text, or from the file date as a last "
            "resort. This is the slow step."],
           ["3", "s03_parse.py",
            "Extracts the numbers. Three kinds of parser: positional (for Power BI "
            "map exports, matching each number to the nearest country label), "
            "narrative regular expressions (for written reports), and taxonomy "
            "tagging (counts theme mentions). Then builds the corridor rows."],
           ["4", "s04_events.py",
            "Rebuilds the timeline: 27 hand-checked milestones, plus event sentences "
            "extracted from flash and external updates (at most three per document, "
            "one per verb per month)."],
           ["5", "s05_export.py",
            "Writes the dashboard files. This is where extracted numbers are cleaned "
            "before publication - see 7.2."],
           ["6", "s06_mcp_layers.py",
            "Rebuilds the external map layers from the cached MCP pulls: border "
            "crossings, IDP localities, refugee totals and camps, IPC food "
            "insecurity, the seasonal calendar and the Areas of Interest."],
           ["7", "s07_xlsx.py",
            "Merges in the two Excel workbooks: the biweekly neighbouring-country "
            "refugee series, and Sudan IDPs by state."]],
          widths=[0.5, 1.6, 4.7])

    heading(doc, "7.1 Which steps to run when", 2)
    table(doc, ["Situation", "Command"],
          [["New PDFs have been added", "run_pipeline"],
           ["You changed a parser or taxonomy.json", "run_pipeline --reparse"],
           ["You refreshed the MCP caches or the Excel files",
            "run_pipeline --only s06,s07"],
           ["You only want to rebuild the dashboard files",
            "run_pipeline --only s05"]],
          widths=[3.6, 3.0])
    para(doc,
         "Steps 1 and 2 only ever add to the database, so running them again is "
         "always safe. Steps 3 to 7 delete and rebuild what they own, which is why "
         "re-tuning a parser never requires re-reading a single PDF.",
         italic=True)

    heading(doc, "7.2 How numbers are cleaned before publication", 2)
    para(doc,
         "Extracted figures always contain some misreads. The clean_series function "
         "in s05_export.py filters them:")
    bullets(doc, [
        ("Same-date readings ", "are collapsed to their median."),
        ("Cumulative metrics ", "(arrivals, returns) can never fall, so any drop is "
         "rejected. A sudden jump is accepted only if the next reports stay near the "
         "new level - a genuine revision persists, a parser glitch does not."),
        ("Counts that can genuinely fall ", "(IDPs, total displaced - people do "
         "return home) are filtered differently: a value is dropped only when it is "
         "more than double or less than half the median of its neighbours."),
    ])
    doc.add_page_break()


def chapter_dashboard(doc):
    heading(doc, "8. The dashboard", 1)
    para(doc, "http://localhost:2026/", bold=True)
    para(doc,
         "One idea explains the whole page: the timeline slider sets a date, and "
         "every panel answers the question 'what was true on that date?'. Dragging "
         "the slider redraws everything.")

    heading(doc, "8.1 Top bar", 2)
    bullets(doc, [
        "Total forcibly displaced",
        "IDPs inside Sudan",
        "Fled to neighbouring countries",
        "Returns to Sudan",
    ])
    para(doc,
         "Each figure carries a small arrow comparing it with 30 days earlier: green "
         "when the direction is good news, red when it is not.")

    heading(doc, "8.2 Map layers (left sidebar)", 2)
    table(doc,
          ["Layer", "What it shows", "Where the data comes from"],
          [["Movement out of Sudan", "Red arrows, thickness by volume, with the "
            "cumulative figure on the arrow", "UNHCR reports"],
           ["Movement back into Sudan", "Green arrows: returns, and the 2025 influx "
            "from South Sudan", "UNHCR reports"],
           ["Key events", "Dots on the map; recent ones large and bright, older "
            "minor ones fade away", "Curated + extracted"],
           ["IDP localities (admin2)", "One bubble per locality, growing over time",
            "IOM-DTM via HDX"],
           ["IDP by state (admin1)", "One bubble per Sudanese state",
            "Excel workbook (Sudan IDPs.xlsx)"],
           ["Refugee totals by country", "One bubble per host country, plus camp "
            "markers that appear from the month they opened",
            "UNHCR via HDX + Excel"],
           ["Food insecurity (IPC phase)", "Area-level IPC choropleth across six "
            "analysis periods, with famine areas outlined", "IPC"],
           ["Border crossings", "Crossings, highlighted when their corridor is "
            "active", "Curated"],
           ["IFRC Areas of Interest", "14 cross-border host regions, filled by their "
            "current IPC phase", "HSP boundaries + IPC"]],
          widths=[1.7, 3.1, 2.0])

    heading(doc, "8.3 The theme toggles", 2)
    para(doc,
         "Under 'What the documents tell us' there are five expandable groups: "
         "hazards, vulnerabilities, coping mechanisms, needs and movement patterns. "
         "Tick a tag and a bubble appears over each country that mentioned it that "
         "month, sized by how often. The panel below lists the counts and a real "
         "sentence from a report; click a row to expand the quote.")
    para(doc,
         "These toggles are built from the data, not hard-coded. Add a keyword group "
         "to taxonomy.json, re-run the pipeline with --reparse, and a new toggle "
         "appears by itself.",
         italic=True)

    heading(doc, "8.4 Right-hand panels", 2)
    bullets(doc, [
        ("Key insights: ", "written automatically for the current date - the "
         "fastest-growing outflow corridor over the last 90 days, whether returns "
         "and internal displacement are rising or falling, and the most-reported "
         "hazard and need this month."),
        ("Voices from the reports: ", "up to three verbatim sentences from the "
         "reporting for that month."),
        ("Top reported hazards: ", "a bar chart of the six most-mentioned hazards."),
    ])

    heading(doc, "8.5 The timeline", 2)
    bullets(doc, [
        "Drag the slider to any date from 15 April 2023 onwards.",
        "Press play to animate the whole crisis; it advances four days at a time.",
        "The small chart behind the slider shows three series on one scale: total "
        "displaced, cross-border movement and returns.",
        "The seasonal calendar in the sidebar highlights the month you are in.",
    ])
    doc.add_page_break()


def chapter_updater(doc):
    heading(doc, "9. The updater page", 1)
    para(doc, "http://localhost:2026/updater/", bold=True)
    para(doc,
         "This page exists so that adding new reports needs no command line at all.")

    heading(doc, "9.1 What is on it", 2)
    table(doc, ["Element", "What it does"],
          [["The big number", "How many PDFs are sitting in the source folders that "
            "the database has never seen, with their file names listed below."],
           ["Update now", "Runs the whole pipeline and streams its progress live. "
            "The bar follows the real steps; the black box shows the log. When there "
            "are no new files the button says 'Rebuild anyway', which re-exports "
            "everything from the stored text."],
           ["Re-check folders", "Looks again without running anything."],
           ["External data layers table", "For each external layer: where it comes "
            "from, when it was last pulled, and when the map layer was last built."],
           ["Rebuild external layers", "Runs steps 6 and 7 only, re-applying the "
            "caches already on disk."],
           ["Dashboard preview", "The live dashboard in a frame, reloaded "
            "automatically when an update finishes."]],
          widths=[2.0, 4.8])

    heading(doc, "9.2 An important limit", 2)
    para(doc,
         "Fetching brand-new data from the humanitarian MCP servers (HDX, IPC, "
         "FEWS NET, UNHCR) cannot happen inside the container. It needs the Claude "
         "Code client and API keys, so an analyst runs it on the host; that step "
         "refreshes the files in data_pipeline/mcp_cache/. The button on this page "
         "only re-applies whatever is already cached. The dates in the freshness "
         "table tell you when each cache was last refreshed.",
         bold=True)
    doc.add_page_break()


def chapter_admin_api(doc):
    heading(doc, "10. The admin site and the JSON API", 1)

    heading(doc, "10.1 Admin", 2)
    para(doc, "http://localhost:2026/admin/", bold=True)
    para(doc,
         "A ready-made interface onto every table: search, filter, drill down by "
         "date, and edit. The most common use is auditing a number: search for a "
         "figure, open the row, read the snippet it was taken from, and follow the "
         "link to the source document.")
    para(doc,
         "Log in with the user created from DJANGO_SUPERUSER_PASSWORD in .env, or "
         "create one with:")
    code(doc, ["docker compose exec web python manage.py createsuperuser"])

    heading(doc, "10.2 JSON API", 2)
    para(doc,
         "Read-only, always live from PostgreSQL. Useful for feeding another tool "
         "without exporting files.")
    table(doc, ["Address", "Returns"],
          [["/api/", "The list of endpoints"],
           ["/api/meta/", "Corpus counts and the date range"],
           ["/api/documents/", "The catalogue of PDFs. Filters: ?family= &country="],
           ["/api/events/", "The timeline. Filters: ?category= &source="],
           ["/api/flows/", "Corridors with their raw series"],
           ["/api/headline/", "Every headline metric as date/value pairs"],
           ["/api/figures/", "Individual figures with their evidence. Filters: "
            "?metric= &country= &method= &confidence= &limit="],
           ["/api/tags/", "Monthly theme counts. Filter: ?dimension="]],
          widths=[1.9, 4.9])
    para(doc,
         "Note the difference between /api/headline/ (raw rows, exactly as stored) "
         "and data/headline.json (the same series after the cleaning described in "
         "7.2). The dashboard uses the cleaned version.",
         italic=True)

    heading(doc, "10.3 Connecting other tools to the database", 2)
    table(doc, ["Setting", "Value"],
          [["Host", "localhost"],
           ["Port", "5432 (or POSTGRES_HOST_PORT from .env)"],
           ["Database", "sudan_neighbouring_pop_movement"],
           ["User", "sudan"],
           ["Password", "whatever you set in .env"]],
          widths=[2.0, 4.6])
    doc.add_page_break()


def chapter_sources(doc):
    heading(doc, "11. Where the data comes from", 1)

    heading(doc, "11.1 The UNHCR corpus", 2)
    para(doc,
         "Two folders of situation reports, kept beside the repository in the "
         "SUDAN Ops folder:")
    bullets(doc, [
        "UNHCR Regional Population Movement pdfs",
        "UNHCR Sudan only pdfs",
    ])
    para(doc,
         "They are not in the repository, and they do not need to be: the whole "
         "point of storing the page text is that the analysis survives without them.")

    heading(doc, "11.2 The external layers", 2)
    table(doc, ["Layer", "Source", "What is genuinely per-location"],
          [["IDP localities", "IOM-DTM via HDX",
            "Real per-locality (admin2) series"],
           ["IDP by state", "Excel workbook", "Real per-state (admin1) series"],
           ["Refugee totals", "UNHCR via HDX + Excel",
            "Real, but per host COUNTRY only - the servers do not publish per-camp "
            "series. Camp dots mark locations, not counts."],
           ["Food insecurity", "IPC",
            "Real per analysis area, across six analysis periods"],
           ["Areas of Interest", "IPC + HSP boundaries",
            "The worst IPC phase of the sub-areas inside each region. 9 of 14 areas "
            "have IPC coverage."],
           ["Seasonal calendar", "FEWS NET", "National bands"],
           ["Border crossings", "Curated", "Hand-checked operational geography"]],
          widths=[1.5, 1.7, 3.6])
    doc.add_page_break()


def chapter_maintenance(doc):
    heading(doc, "12. Routine maintenance", 1)

    heading(doc, "12.1 Adding new reports", 2)
    bullets(doc, [
        "Drop the PDFs into the right year folder of one of the two UNHCR "
        "collections.",
        "Open http://localhost:2026/updater/ and press Re-check folders.",
        "Press Update now and watch the progress bar.",
        "The dashboard preview reloads by itself when it finishes.",
    ])

    heading(doc, "12.2 Refreshing the external layers", 2)
    bullets(doc, [
        "New numbers from the MCP servers are pulled by an analyst in Claude Code "
        "and written into Community Centered Humanitarian Analysis Platform/data_pipeline/mcp_cache/.",
        "Then press Rebuild external layers on the updater page, or run "
        "run_pipeline --only s06,s07.",
        "Updating the Excel workbooks needs only step 7.",
    ])

    heading(doc, "12.3 Changing what is extracted", 2)
    table(doc, ["To change...", "Edit...", "Then run"],
          [["Which theme toggles exist", "data_pipeline/taxonomy.json", "--reparse"],
           ["Places and corridors", "data_pipeline/gazetteer.json", "--reparse"],
           ["How figures are read", "data_pipeline/steps/s03_parse.py", "--reparse"],
           ["The curated milestones", "data_pipeline/steps/s04_events.py", "--reparse"],
           ["How numbers are cleaned", "data_pipeline/steps/s05_export.py",
            "--only s05"],
           ["The map itself",
            "dashboard/static/dashboard/js/app.js, css/app.css, "
            "dashboard/templates/dashboard/index.html",
            "nothing - just refresh"]],
          widths=[2.2, 3.0, 1.6])

    heading(doc, "12.4 Backing up", 2)
    code(doc, [
        "# Save the whole database to a file",
        "docker compose exec db pg_dump -U sudan sudan_neighbouring_pop_movement > backup.sql",
        "",
        "# Restore it into an empty database",
        "docker compose exec -T db psql -U sudan sudan_neighbouring_pop_movement < backup.sql",
    ])
    para(doc,
         "This dump is the only backup of the database and the normal way to seed "
         "a second instance. Take one before any migration or bulk edit.")

    heading(doc, "12.5 Changing the database structure", 2)
    code(doc, [
        "# 1. edit Community Centered Humanitarian Analysis Platform/data_track/models.py",
        "# 2. create the migration",
        "docker compose exec web python manage.py makemigrations data_track",
        "# 3. apply it",
        "docker compose exec web python manage.py migrate",
    ])
    doc.add_page_break()


def chapter_limits(doc):
    heading(doc, "13. Known limitations", 1)
    para(doc,
         "These matter when citing a figure and should not be forgotten.", bold=True)
    bullets(doc, [
        ("Power BI map exports scatter their text. ",
         "Per-country figures are matched to the nearest country label on the page, "
         "geometrically. Implausible values are rejected by per-country bounds and "
         "by the monotonicity filter at export. Always check method and confidence "
         "before citing."),
        ("Narrative-regex figures are indicative only. ",
         "The weekly-mapping and CORE-series parsers are the authoritative time "
         "series."),
        ("Extracted events are verbatim sentences. ",
         "Events with source='extracted' are lifted from reports as written. Only "
         "curated milestones have been cross-checked against the corpus."),
        ("Refugee magnitude is per host country, not per camp. ",
         "The camp markers show where camps are, not how many people are in them."),
        ("Egypt figures are UNHCR-registered only. ",
         "Actual Sudanese presence in Egypt is far larger than the registered "
         "figure; government estimates exceed one million."),
        ("Areas of Interest take the worst phase inside them. ",
         "Uganda, CAR, Egypt and Abyei have no current IPC analysis and are shown "
         "as such."),
        ("New MCP data cannot be fetched inside Docker. ",
         "See section 9.2."),
    ])
    doc.add_page_break()


def chapter_troubleshooting(doc):
    heading(doc, "14. Troubleshooting", 1)
    table(doc, ["Symptom", "Likely cause and fix"],
          [["Nothing at localhost:2026",
            "The web container is still starting, or crashed. Run "
            "docker compose logs -f web and read the last lines."],
           ["'env file .env not found'",
            "Copy env.example to .env."],
           ["Port already in use",
            "Something else uses 2026, 5432 or 5050. Change WEB_HOST_PORT, "
            "POSTGRES_HOST_PORT or PGADMIN_HOST_PORT in .env and restart."],
           ["Dashboard loads but everything is empty",
            "The database has no data yet. Restore a pg_dump backup, or run "
            "run_pipeline."],
           ["The updater says 0 new files but you added some",
            "The PDFs are outside SOURCE_ROOT, or not in one of the two named "
            "collection folders. Check the volume mount in docker-compose.yml."],
           ["Password change had no effect",
            "PostgreSQL keeps the credentials it was created with. See the note at "
            "the end of chapter 4."],
           ["pgAdmin asks for a password",
            "That is the database password from .env, not the pgAdmin login."],
           ["An update seems stuck",
            "Step 2 is genuinely slow on a large batch. The log box keeps printing; "
            "if it has stopped, check docker compose logs web."],
           ["Changed the code but nothing happened",
            "Python changes need docker compose restart web. Changes to "
            "requirements.txt need docker compose up -d --build."]],
          widths=[2.4, 4.4])


def build():
    doc = Document()
    # Set a readable default font for the whole document.
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)

    cover(doc)
    chapter_overview(doc)
    chapter_architecture(doc)
    chapter_quickstart(doc)
    chapter_env(doc)
    chapter_layout(doc)
    chapter_database(doc)
    chapter_pipeline(doc)
    chapter_dashboard(doc)
    chapter_updater(doc)
    chapter_admin_api(doc)
    chapter_sources(doc)
    chapter_maintenance(doc)
    chapter_limits(doc)
    chapter_troubleshooting(doc)

    doc.save(OUT_PATH)
    print(f"written: {OUT_PATH}")


if __name__ == "__main__":
    build()
