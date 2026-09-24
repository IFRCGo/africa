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

Two files quote a chapter number of this manual and have to follow it if the
numbering moves: env.example points at chapter 4 for the settings, and
README.md points at chapter 16 for troubleshooting.
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

IFRC_RED = RGBColor(0xEE, 0x24, 0x35)      # the brand red, brand.ifrc.org
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


def steps(doc, items):
    """Add a numbered list, for a procedure someone follows in order."""
    for item in items:
        p = doc.add_paragraph(style="List Number")
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
    run = sub2.add_run(
        "Full functional documentation\nDjango - PostgreSQL/PostGIS - Docker")
    run.font.size = Pt(12)
    run.font.color.rgb = GREY

    doc.add_paragraph()
    para(doc,
         "This document describes every part of the system: what it does, how to run "
         "it, what each container and each file is for, every table in the database, "
         "every step of the data pipeline, every layer and control on the dashboard, "
         "how new figures are pulled from the humanitarian data servers, how "
         "community statements are read out of documents and published, and every "
         "setting you can change. It is written to be readable by someone who has "
         "never opened the code.",
         size=11)

    doc.add_paragraph()
    para(doc, "How to read it", bold=True)
    bullets(doc, [
        ("If you only look at the map: ",
         "chapter 8 explains every control on it, and chapter 15 lists what the "
         "numbers can and cannot be used for."),
        ("If you keep the data current: ",
         "chapter 9 (new documents), chapter 10 (refreshing the open-data layers) "
         "and chapter 11 (community statements) are the three jobs."),
        ("If you are installing it: ",
         "chapters 3 to 5, then chapter 14."),
        ("If something is broken: ",
         "chapter 16."),
    ])
    doc.add_page_break()


def chapter_overview(doc):
    heading(doc, "1. What this system is", 1)
    para(doc,
         "The platform turns secondary data sources and situation reports into a "
         "living picture of the Sudan displacement crisis. It reads documents, "
         "pulls the numbers and the narrative out of them, fetches figures from the "
         "humanitarian open-data servers, stores everything in one database, and "
         "publishes an interactive map you can drag through time from 15 April 2023 "
         "to today.")

    heading(doc, "1.1 The five things it produces", 2)
    bullets(doc, [
        ("A story database. ",
         "Every report, every page of its text, every figure, every movement "
         "corridor, every event and every theme mentioned. Because the full page "
         "text is stored, the analysis stays reproducible even if the original PDFs "
         "are deleted."),
        ("An interactive dashboard. ",
         "A map with a timeline slider that replays the crisis: movement arrows and "
         "their direction, cumulative numbers, key events, and filters for hazards, "
         "vulnerabilities, coping mechanisms, needs and movement patterns."),
        ("Open-data map layers. ",
         "Food insecurity, IDP counts, refugee totals, border crossings, "
         "humanitarian service points, the seasonal calendar and the IFRC Areas of "
         "Operation, all animated on the same timeline, and all refreshable from a "
         "button in the admin site."),
        ("Community insights. ",
         "Statements said by affected people, lifted verbatim out of assessment "
         "documents, checked word-for-word against the page they came from, coded "
         "against the same taxonomy as everything else, and published only after a "
         "person reviewed them."),
        ("A boundary library. ",
         "The office's own authoritative administrative boundaries - with p-codes, "
         "validity dates and alternate spellings - held as real geometry in the "
         "database, so QGIS, Power BI and the database itself can use them."),
    ])

    heading(doc, "1.2 Who does what", 2)
    table(doc,
          ["Person", "What they use", "Where"],
          [["Analyst / reporting officer", "Reads the dashboard, drags the timeline",
            "http://localhost:2026/"],
           ["Information manager", "Drops new PDFs in, presses Update now",
            "http://localhost:2026/updater/"],
           ["Information manager", "Refreshes the open-data layers (Pull now)",
            "/admin/api_calls/datasource/"],
           ["Community engagement / PGI", "Reads documents in, reviews and "
            "publishes statements", "/admin/ - Community insights"],
           ["Data officer", "Browses and corrects rows in the database",
            "http://localhost:2026/admin/"],
           ["Analyst with SQL / Power BI", "Queries PostgreSQL directly",
            "localhost:5432, or pgAdmin at :5050"],
           ["Developer", "Changes parsers, layers or the site",
            "Community Centered Humanitarian Analysis Platform/ in this repository"]],
          widths=[1.9, 2.7, 2.0])

    heading(doc, "1.3 The three ways data gets in", 2)
    para(doc,
         "Everything in the database arrived by one of three routes. Knowing which "
         "route a number took tells you where to go to refresh it.")
    table(doc,
          ["Route", "What comes in", "Who starts it", "Chapter"],
          [["The pipeline", "UNHCR situation reports: figures, corridors, events, "
            "theme counts", "Update now, on the updater page", "7 and 9"],
           ["API pulls", "IPC, FEWS NET, HDX, UNHCR, ACAPS, Montandon, Kobo, and "
            "the two Excel workbooks", "Pull now, in the admin site", "10"],
           ["Community insights", "Verbatim statements out of assessment and "
            "feedback documents", "The insights wizard, in the admin site", "11"]],
          widths=[1.4, 3.0, 1.7, 0.8])
    doc.add_page_break()


def chapter_architecture(doc):
    heading(doc, "2. How it is put together", 1)
    para(doc,
         "Everything runs in Docker. Three containers start together and talk to "
         "each other on a private network that Docker creates for them.")

    table(doc,
          ["Container", "Image", "What it does", "Your address"],
          [["db", "postgis/postgis:16-3.4-alpine",
            "Stores every table. Its files live in a Docker volume called pgdata.",
            "localhost:5432"],
           ["web", "built from Community Centered Humanitarian Analysis Platform/Dockerfile",
            "Runs Django: the dashboard, the updater, the admin site, the JSON API, "
            "the data pipeline, the API pulls and the document reading.",
            "http://localhost:2026"],
           ["pgadmin", "dpage/pgadmin4",
            "A web interface for looking inside PostgreSQL: run SQL, browse tables, "
            "export CSV.",
            "http://localhost:5050"]],
          widths=[1.0, 1.7, 3.2, 1.3])

    para(doc,
         "It is PostGIS, not plain PostgreSQL. The boundary library stores real "
         "geometry, so QGIS, DBeaver and Power BI open admin_areas as a map layer "
         "and the database can answer spatial questions itself. The image is "
         "postgres:16 with the PostGIS extension added, so the on-disk layout is "
         "identical - but going back to a plain server is not just a tag change "
         "once geometry columns exist.",
         italic=True)

    heading(doc, "2.1 The path a number takes", 2)
    para(doc,
         "A figure printed in a UNHCR PDF reaches the dashboard like this:")
    code(doc, [
        "UNHCR PDF in the source folder",
        "   |  step 1  catalogue it        -> documents table",
        "   |  step 2  read its text       -> document_text table",
        "   |  step 3  parse the numbers   -> population_figures, movement_flows,",
        "   |                                 narrative_tags tables",
        "   |  step 4  build the timeline  -> events table",
        "   |  step 5  export              -> dashboard/data/*.json",
        "   v",
        "the map at http://localhost:2026/",
    ])
    para(doc, "A figure from a humanitarian data server takes a different road:")
    code(doc, [
        "IPC / FEWS NET / HDX / UNHCR / ACAPS / Montandon / Kobo / Excel",
        "   |  fetch  (Pull now)  -> the raw response saved in api_cache/",
        "   |  load               -> food_security, movement_patterns,",
        "   |                        seasonal_calendar, hazard_events ... tables",
        "   |  steps 6-7  (Rebuild dashboard layers)",
        "   |                     -> dashboard/data/*.json and *.geojson",
        "   v",
        "the map at http://localhost:2026/",
    ])
    para(doc,
         "Fetching and rebuilding are two separate buttons on purpose. A pull "
         "changes the database only; the map changes when you rebuild. That way the "
         "published map never moves under a reader's feet while somebody is still "
         "pulling.",
         bold=True)

    heading(doc, "2.2 Why the dashboard reads files, not the database", 2)
    para(doc,
         "The map fetches a handful of small pre-built files rather than waiting on "
         "SQL, which is what keeps it fast. Two things are the exception and are "
         "read live from PostgreSQL: the community insights panel (so Publish means "
         "published - refresh the page and the statement is there) and the JSON API "
         "described in chapter 12.")

    heading(doc, "2.3 What is mounted where", 2)
    para(doc,
         "The web container sees six folders from your machine. You put documents "
         "into the first; the application writes only to /app and /docs.")
    table(doc,
          ["Inside the container", "Is really", "Mode"],
          [["/work", "SOURCE_HOST_DIR - the folder holding the source documents "
            "and the two Excel workbooks. Defaults to the parent of this "
            "repository.", "read-only"],
           ["/app", "the Community Centered Humanitarian Analysis Platform folder: "
            "code, templates, static files, and the dashboard's data/ output",
            "read/write"],
           ["/docs", "this docs folder, so the Word manual can be rebuilt from "
            "inside the container", "read/write"],
           ["/boundary-src/chad-maps", "the Chad Maps share: administrative "
            "boundaries and the HSP workbook", "read-only"],
           ["/boundary-src/layers", "the QGIS template layers: rivers, lakes, "
            "roads, capitals", "read-only"],
           ["/boundary-src/icons", "the icon set used when drawing map features",
            "read-only"]],
          widths=[1.7, 4.1, 0.9])
    para(doc,
         "/work is read-only deliberately. Anything the application writes goes "
         "under /app. The three boundary mounts are read once, by "
         "manage.py load_boundaries, and never at runtime.",
         italic=True)

    heading(doc, "2.4 Why PostgreSQL", 2)
    bullets(doc, [
        "Several people can read and write at the same time, which a single file "
        "database cannot do safely.",
        "It is a real server, so Power BI, Excel, DBeaver, QGIS and Python can all "
        "connect to it over the network.",
        "Django manages the table structure through migrations, so a change to a "
        "models.py file is applied to the database in a controlled, repeatable way.",
        "With PostGIS it holds the boundaries as geometry, so the map lives in the "
        "same place as the numbers.",
        "It backs up to a single portable file with pg_dump, which is also how a "
        "second instance is seeded (see 14.5).",
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
        "#    b) or rebuild from the source documents (hours, needs no dump)",
        "docker compose exec web python manage.py run_pipeline",
    ])
    para(doc,
         "The web container waits for the database, creates the tables and starts "
         "the site by itself, but the tables start out empty. Option (a) is the "
         "normal route: take backup.sql from a running instance with the pg_dump "
         "command in 14.5. Option (b) is the fallback when no dump is at hand - "
         "run_pipeline re-reads every PDF and rebuilds the report tables from "
         "scratch (locations is regenerated from data_pipeline/gazetteer.json by "
         "step 3), slowly but completely.")
    para(doc,
         "Option (b) rebuilds the report tables only. The external data, the "
         "boundary library and the community insights are not in the pipeline. On a "
         "genuinely fresh database the curated rows come from "
         "manage.py seed_external, the boundaries from manage.py load_boundaries, "
         "the rest of the external data from the pulls in chapter 10, and the "
         "statements from the wizard in chapter 11 - which is a lot of work, and "
         "the main reason a pg_dump restore is the normal route.",
         italic=True)

    heading(doc, "3.2 Every day", 2)
    table(doc,
          ["To do this", "Go here"],
          [["Look at the dashboard", "http://localhost:2026/"],
           ["Ingest new PDFs", "http://localhost:2026/updater/"],
           ["Refresh the open-data layers",
            "http://localhost:2026/admin/api_calls/datasource/"],
           ["Read documents into community statements",
            "http://localhost:2026/admin/ - Community insights"],
           ["Browse or fix the data", "http://localhost:2026/admin/"],
           ["Run SQL against the database", "http://localhost:5050/ (pgAdmin)"],
           ["Read live JSON", "http://localhost:2026/api/"]],
          widths=[3.0, 3.6])

    heading(doc, "3.3 Useful commands", 2)
    para(doc,
         "Every command is run inside the web container, so they all start the same "
         "way. That prefix is written out once here and shortened afterwards.")
    code(doc, [
        "docker compose up -d              start everything",
        "docker compose down               stop everything (data is kept)",
        "docker compose logs -f web        watch what Django is doing",
        "docker compose restart web        restart just Django (after a code change)",
        "docker compose up -d web          recreate it (after changing .env)",
        "",
        "docker compose exec web python manage.py run_pipeline",
        "docker compose exec web python manage.py run_pipeline --reparse",
        "docker compose exec web python manage.py run_pipeline --list",
        "docker compose exec web python manage.py external_status",
        "docker compose exec web python manage.py createsuperuser",
        "docker compose exec web python manage.py test -v 2",
        "",
        "docker compose down -v            DELETE the database as well - careful",
    ])
    para(doc,
         "docker compose down -v is never the answer to a password problem. See "
         "4.6.",
         bold=True)
    doc.add_page_break()


def chapter_env(doc):
    heading(doc, "4. The .env file - every setting explained", 1)
    para(doc,
         "All credentials, keys and ports live in one file called .env in the "
         "project root. Docker Compose reads it automatically. It is listed in "
         ".gitignore, so it is never committed; the template env.example is "
         "committed instead. Almost every setting has a working default, so a "
         "minimal .env is the three passwords and nothing else.")

    heading(doc, "4.1 The database, Django and the ports", 2)
    table(doc,
          ["Setting", "What it controls", "Default"],
          [["POSTGRES_DB", "Name of the database", "sudan_neighbouring_pop_movement"],
           ["POSTGRES_USER", "Database user Django logs in as", "sudan"],
           ["POSTGRES_PASSWORD", "That user's password. No default - you must set it.",
            "(none)"],
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
           ["DJANGO_SUPERUSER_PASSWORD", "Read only when no superuser exists yet",
            "(empty = skip)"],
           ["DASHBOARD_URL", "Link the updater page uses", "/"],
           ["TZ", "Time zone for timestamps", "UTC"]],
          widths=[2.2, 3.4, 1.4])
    para(doc,
         "POSTGRES_PASSWORD deliberately has no fallback. A default password in a "
         "repository is not a password, and a fallback would let a fresh clone "
         "appear to work while quietly using one. Both Docker Compose and Django "
         "stop straight away and say what to set.",
         italic=True)

    heading(doc, "4.2 Keys for the data pulls", 2)
    para(doc,
         "Without a key, the affected rows on the Data Refresh page still show "
         "their freshness; their button is greyed out and reads \"needs X in "
         ".env\". Nothing is called.")
    table(doc,
          ["Setting", "Covers", "Where to get it"],
          [["IPC_API_KEY", "the ipc and ch (Cadre Harmonise) rows",
            "request one from ipcinfo.org"],
           ["HDX_API_TOKEN", "the hdx AND unhcr rows - the UNHCR figures are served "
            "through HDX HAPI, so there is no separate UNHCR key",
            "encode yours at hapi.humdata.org/docs, under Util > encode_identifier"],
           ["IFRC_API_TOKEN", "the montandon rows - IFRC's disaster-event registry, "
            "which is not an open API", "the same token the monty MCP server uses"],
           ["MONTANDON_STAC_URL", "which Montandon deployment is called. Production "
            "wants IFRC GO OIDC credentials, so the default is staging.",
            "leave empty unless you have been told otherwise"],
           ["(none needed)", "FEWS NET", "-"]],
          widths=[1.7, 3.3, 2.0])

    heading(doc, "4.3 The basemap", 2)
    table(doc,
          ["Setting", "What it controls", "Default"],
          [["MAPBOX_STYLE_URL", "The basemap style drawn under everything else",
            "the shared IFRC GO style"],
           ["MAPBOX_ACCESS_TOKEN", "The public 'pk.' token that style is fetched "
            "with", "the public GO token"]],
          widths=[2.2, 3.4, 1.4])
    para(doc,
         "The working defaults live in config/settings.py, not in "
         "docker-compose.yml, and they are the public values GO itself publishes, "
         "so the map works untouched. Set these in .env only to point at a "
         "different style or a rotated token. Note that docker compose restart does "
         "NOT re-read .env - a changed value needs docker compose up -d web.",
         italic=True)

    heading(doc, "4.4 Reading documents, and the model that extracts from them", 2)
    para(doc,
         "These govern chapter 11. Every one has a working default; an empty value "
         "falls back to the default, so blanking a line and commenting it out do "
         "the same thing.")
    table(doc,
          ["Setting", "What it controls", "Default"],
          [["DOCLING_ENABLED", "Whether documents are converted with Docling before "
            "the model reads them", "true"],
           ["DOCLING_OCR_LANGS", "OCR languages, ISO 639-1. See the warning below.",
            "en,ar"],
           ["DOCLING_MAX_PAGES", "Pages per document, matching the pipeline's own "
            "ceiling", "40"],
           ["DOCLING_TIMEOUT_SECONDS", "How long one document may take", "900"],
           ["DOCLING_ARTIFACTS_PATH", "Where the model weights live in the image",
            "/opt/docling/models"],
           ["LLM_PROVIDER", "Which kind of model does the extraction: anthropic, or "
            "openai_compatible for a local model", "anthropic"],
           ["LLM_MODEL", "Which model", "claude-opus-5"],
           ["LLM_BASE_URL", "For a local model, e.g. "
            "http://host.docker.internal:11434/v1", "(empty)"],
           ["LLM_API_KEY", "The key for that provider", "(empty)"],
           ["INSIGHT_DOCUMENT_ROOTS", "Which folders the folder browser may offer, "
            "and the only folders a registered folder may point at. Separated by ':' "
            "on Linux/macOS, ';' on Windows.", "SOURCE_ROOT and MEDIA_ROOT"],
           ["INSIGHT_UPLOAD_RETENTION_MINUTES", "How long an uploaded document stays "
            "on disk. See 11.6.", "30"]],
          widths=[2.3, 3.3, 1.4])
    para(doc,
         "OCR languages are not a free combination. EasyOCR refuses to load Arabic "
         "beside any other non-English language (\"Arabic is only compatible with "
         "English\"), and one conversion pass has one language list. So "
         "DOCLING_OCR_LANGS is en,ar or en,fr - never both. The weights for both "
         "are already in the image, so switching is this one line plus "
         "docker compose restart web, not a rebuild.",
         bold=True)

    heading(doc, "4.5 Paths", 2)
    table(doc,
          ["Setting", "What it controls", "Default"],
          [["SOURCE_HOST_DIR", "The folder ON YOUR MACHINE mounted read-only at "
            "/work. Change it when deploying somewhere the documents live "
            "elsewhere; /work stays /work.", ".. (the parent of this repository)"],
           ["SOURCE_ROOT", "Where the pipeline looks for the source PDFs, inside the "
            "container", "/work"],
           ["DASHBOARD_DATA_DIR", "Where the pipeline writes the dashboard files",
            "/app/dashboard/data"],
           ["API_CACHE_DIR", "Where raw API responses and job logs are staged",
            "/app/data_pipeline/api_cache"],
           ["MEDIA_ROOT", "Where uploaded documents are held, briefly",
            "/app/media"],
           ["POP_MOVEMENT_XLSX", "The neighbouring-countries Excel workbook",
            "/work/neighbouring countries Pop movement data.xlsx"],
           ["BOUNDARY_ADMIN_DIR", "Administrative boundary files, read by "
            "load_boundaries", "/boundary-src/chad-maps/Countries Maps"],
           ["BOUNDARY_LAYERS_DIR", "Rivers, lakes, roads, capitals",
            "/boundary-src/layers"],
           ["BOUNDARY_ICONS_DIR", "Icons for map features", "/boundary-src/icons"],
           ["HSP_XLSX", "The Humanitarian Service Points workbook",
            "under /boundary-src/chad-maps"]],
          widths=[2.2, 3.4, 1.4])
    para(doc,
         "Moving API_CACHE_DIR is never just a folder move. Three columns hold "
         "absolute paths into it - PullJob.log_path, PullJob.payload_path and "
         "Conversion.markdown_path - and a path that no longer resolves raises "
         "nothing: the job page shows an empty log, and a conversion is silently "
         "redone. Migrations rewrote those rows the last time it moved, and must be "
         "extended the same way if it moves again.",
         italic=True)

    heading(doc, "4.6 Changing a password", 2)
    para(doc,
         "Editing .env is not enough on its own, and deleting the database is never "
         "the fix.", bold=True)
    para(doc,
         "PostgreSQL and pgAdmin each store the credentials they were first created "
         "with inside their own volume, so a new value in .env only changes what "
         "the containers offer, not what the servers expect. The two then disagree "
         "and the dashboard stops connecting. docker compose down -v does make them "
         "agree again - by deleting every row you have. Rotate in place instead:")
    code(doc, [
        "# 1. Back up first",
        "docker compose exec -T db pg_dump -U sudan sudan_neighbouring_pop_movement > backup.sql",
        "",
        "# 2. Put the new values in .env (letters, digits, - and _ only)",
        "",
        "# 3. Tell PostgreSQL its new password",
        "docker compose exec -T db psql -U sudan -d sudan_neighbouring_pop_movement \\",
        "  -c \"ALTER USER sudan WITH PASSWORD 'THE-NEW-PASSWORD';\"",
        "",
        "# 4. Tell pgAdmin its new password, keeping its saved servers",
        "docker compose exec -T pgadmin /venv/bin/python /pgadmin4/setup.py \\",
        "  update-user admin@example.org --password THE-NEW-PASSWORD --role Administrator",
        "",
        "# 5. Recreate the containers so they pick up .env. NOT 'down -v'.",
        "docker compose up -d",
    ])
    para(doc,
         "Then check it worked - and check through the service name db, not "
         "localhost. pg_hba.conf trusts loopback, so a 127.0.0.1 connection accepts "
         "any password and would look like success even if nothing changed.")
    code(doc, [
        "# must succeed",
        "docker compose exec -T db psql \\",
        "  \"postgresql://sudan:THE-NEW-PASSWORD@db:5432/sudan_neighbouring_pop_movement\" -c \"SELECT 1;\"",
        "",
        "# must FAIL with 'password authentication failed'",
        "docker compose exec -T db psql \\",
        "  \"postgresql://sudan:THE-OLD-PASSWORD@db:5432/sudan_neighbouring_pop_movement\" -c \"SELECT 1;\"",
    ])
    para(doc,
         "The /admin/ password is not part of this: Django keeps its own hash. "
         "DJANGO_SUPERUSER_PASSWORD is read only when no superuser exists yet. "
         "Afterwards use manage.py changepassword admin. Changing "
         "DJANGO_SECRET_KEY is safe at any time - it only signs out whoever is "
         "currently logged in.")
    doc.add_page_break()


def chapter_layout(doc):
    heading(doc, "5. What is in each folder", 1)
    para(doc,
         "Every folder in the application is named after the job it does. The "
         "three you open in a browser are dashboard/, updater/ and the admin site; "
         "the rest are what sits behind them.")
    code(doc, [
        "Community Centered Humanitarian Analysis/",
        "|- docker-compose.yml       the three containers, ports and volumes",
        "|- .env                     YOUR credentials and ports (never committed)",
        "|- env.example              the template to copy it from",
        "|- README.md                the short version of this document",
        "|- MAINTENANCE.md           the operational runbook",
        "|",
        "|- Community Centered Humanitarian Analysis Platform/    THE APPLICATION",
        "|   |- manage.py            the command you run everything with",
        "|   |- Dockerfile           how the web image is built",
        "|   |- entrypoint.sh        waits for the DB, migrates, starts gunicorn",
        "|   |- requirements.txt     the Python packages, with reasons",
        "|   |",
        "|   |- dashboard/      -- serves  http://localhost:2026/     THE MAP",
        "|   |   |- templates/dashboard/index.html   the page skeleton",
        "|   |   |- static/dashboard/css/app.css     all styling",
        "|   |   |- static/dashboard/js/app.js       all behaviour",
        "|   |   |- data/            the JSON and GeoJSON the map fetches",
        "|   |",
        "|   |- updater/        -- serves  /updater/       THE UPDATE NOW PAGE",
        "|   |   |- urls.py  views.py   runs the pipeline, streams the progress",
        "|   |",
        "|   |- data_track/     -- serves  /api/ and /admin/   THE REPORT TABLES",
        "|   |   |- README.md        what each of the seven tables holds",
        "|   |   |- models.py        one class per table - the only definition",
        "|   |   |- admin.py  views.py  urls.py",
        "|   |",
        "|   |- data_pipeline/  -- no web address        HOW THE DATA IS BUILT",
        "|   |   |- README.md        the steps, and what each one owns",
        "|   |   |- steps/s01..s07   the seven pipeline steps",
        "|   |   |- api_cache/       raw API responses and job logs (staging)",
        "|   |   |- gazetteer.json   ~95 places and the corridors between them",
        "|   |   |- taxonomy.json    the keyword lists behind the theme filters",
        "|   |   |- common.py        paths, report families, date/number parsing",
        "|   |",
        "|   |- external_data/  -- serves  /api/external/ ...   THE OPEN DATA",
        "|   |   |- fetchers/        one file per API: where a payload COMES FROM",
        "|   |   |- loaders/         one file per dataset: what a payload MEANS",
        "|   |   |- models.py        food security, movement, seasonal, hazards ...",
        "|   |",
        "|   |- api_calls/      -- serves  /admin/api_calls/   THE PULL BUTTONS",
        "|   |   |- views.py         starts a pull, and watches it",
        "|   |   |- models.py        DataSource (the list) and PullJob (the log)",
        "|   |",
        "|   |- insights/       -- serves  /admin/ + /api/insights/   THE VOICES",
        "|   |   |- wizard.py        the four-step route from documents to review",
        "|   |   |- docling_reader.py  converts a document to per-page markdown",
        "|   |   |- extractors/      the model that proposes statements",
        "|   |   |- verify.py        re-matches every quote against the page text",
        "|   |   |- retention.py     deletes the uploaded file, keeps the text",
        "|   |   |- prompts/extract_insights.md   the extraction contract",
        "|   |",
        "|   |- boundaries/     -- serves  /api/boundaries/   THE MAP ITSELF",
        "|   |   |- models.py        BoundarySource, AdminArea, MapFeature",
        "|   |",
        "|   |- media/               uploaded documents, held briefly",
        "|   |- staticfiles/         what collectstatic writes; never edited",
        "|   |- config/         -- no web address   settings.py, urls.py, wsgi.py",
        "|",
        "|- docs/                    this document and the script that builds it",
    ])
    doc.add_page_break()


def chapter_database(doc):
    heading(doc, "6. The database", 1)
    para(doc,
         "Twenty-seven tables, in five groups. Each group is one Django app, each "
         "table is one class in that app's models.py, and every one is browsable at "
         "/admin/. The table name is the real name in PostgreSQL - that is what you "
         "type in pgAdmin, psql, Power BI or QGIS.")
    para(doc,
         "The row counts below are from the reference instance in September 2026 - "
         "they show the order of magnitude, not a target.",
         italic=True)

    heading(doc, "6.1 The report tables - what the documents said", 2)
    para(doc, "Filled by the pipeline, chapter 7. App: data_track.")
    table(doc,
          ["Table", "One row is", "Filled by", "Rough size"],
          [["documents", "One source PDF", "step 1", "~950"],
           ["document_text", "One page of one PDF, as raw text", "step 2", "~5,200"],
           ["population_figures", "One number found in a report, with its evidence",
            "step 3", "~2,100"],
           ["movement_flows", "One corridor observation at one date", "step 3",
            "~1,100"],
           ["narrative_tags", "One mention of a theme in a report", "step 3",
            "~67,000"],
           ["events", "One dated milestone or incident", "step 4", "~80"],
           ["locations", "One place, with coordinates and alternate spellings",
            "step 3, from gazetteer.json", "~95"]],
          widths=[1.6, 2.9, 1.5, 0.8])
    para(doc,
         "documents is the parent of all of them: every other table except "
         "locations points back at a document, so any figure on the dashboard can "
         "be traced to the PDF and page it came from.")

    heading(doc, "6.2 documents, column by column", 2)
    table(doc, ["Column", "Meaning"],
          [["file_name", "The PDF file name"],
           ["rel_path", "Its path relative to the source folder. Unique - this is "
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

    heading(doc, "6.3 population_figures, column by column", 2)
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

    heading(doc, "6.4 The other report tables", 2)
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
         "filters show."),
        ("locations: ",
         "the gazetteer, loaded from gazetteer.json, used to place figures and "
         "events on the map."),
        ("document_text: ",
         "the archive. One row per page. This is why the story survives even if the "
         "PDFs are deleted."),
    ])

    heading(doc, "6.5 The open-data tables - what the servers publish", 2)
    para(doc, "Filled by the pulls in chapter 10. App: external_data.")
    table(doc,
          ["Table", "One row is", "From"],
          [["source_sync", "One data source the platform tracks: when it was last "
            "pulled, the newest DATA date it holds, how many rows. This is the list "
            "on the Data Refresh page.", "every pull"],
           ["food_security", "One area's IPC/CH/FEWS NET phase for one analysis "
            "period", "IPC, Cadre Harmonise, FEWS NET"],
           ["movement_patterns", "One population count at one place and date: idps, "
            "refugees, returnees, asylum_seekers", "HDX/IOM-DTM, UNHCR, Excel"],
           ["seasonal_calendar", "One season or seasonal event in one country",
            "ACAPS, FEWS NET"],
           ["hazard_events", "One disaster event, as one publisher reported it",
            "IFRC Montandon"],
           ["hazard_impacts", "One impact figure published against one hazard event",
            "IFRC Montandon"],
           ["border_crossings", "One crossing, tagged to the corridors it serves",
            "curated - no API publishes this"],
           ["humanitarian_service_points", "One service a National Society offers, "
            "in one district", "Kobo"]],
          widths=[1.9, 3.3, 1.8])
    para(doc,
         "Two of these are worth a caution. hazard_events and hazard_impacts join "
         "on corr_id rather than by a foreign key, because the two arrive in "
         "separate calls and three publishers can report the same flood. And "
         "humanitarian_service_points is not what its name suggests: the Kobo "
         "export holds no per-site rows, so a row means \"this service is offered "
         "somewhere in this district\", not \"there is a service point at this "
         "spot\". The coordinate is the district's own label position.",
         italic=True)

    heading(doc, "6.6 The boundary library - the map itself", 2)
    para(doc,
         "Filled once by manage.py load_boundaries. App: boundaries. This replaced "
         "borrowed geometry downloaded from public APIs with the office's own "
         "authoritative sources - the OCHA Common Operational Datasets and their "
         "equivalents - which carry p-codes, validity dates and alternate-language "
         "names.")
    table(doc,
          ["Table", "One row is", "Rough size"],
          [["boundary_sources", "One file that was read, so every polygon can name "
            "where it came from and the day that file was valid", "~47"],
           ["admin_areas", "One administrative unit, ADM0 to ADM4, plus the IFRC "
            "Areas of Operation. Carries pcode, name, alternate spellings, parent, "
            "centroid and bounding box.", "~10,800"],
           ["map_features", "One physical feature beside them - rivers, lakes, "
            "capitals, roads, camps", "~17,400"]],
          widths=[1.7, 4.3, 0.9])
    para(doc,
         "The shapes are real PostGIS geometry columns, added by raw SQL rather "
         "than declared as Django fields - which means AdminArea.objects.all() "
         "gives you every attribute and no shape. Anything that needs the shape "
         "asks for it in SQL. Check the library with "
         "manage.py check_boundaries.",
         italic=True)

    heading(doc, "6.7 The community insight tables - what people said", 2)
    para(doc, "Filled by the wizard in chapter 11. App: insights.")
    table(doc,
          ["Table", "One row is"],
          [["insights", "ONE STATEMENT, verbatim and whole. The record. Never "
            "truncated, never summarised."],
           ["insight_codings", "One theme read out of a statement: its dimension, "
            "its tag, and its role (subject, driver or barrier)"],
           ["insight_figures", "One number stated in a statement - people, percent "
            "or households"],
           ["insight_movements", "One corridor described in a statement - "
            "cross-border, internal, return or transit"],
           ["insight_folders", "A registered folder of source documents on a "
            "mounted share"],
           ["insight_uploads", "One document brought in through the wizard. Its "
            "file is released once nothing is pending against it."],
           ["insight_jobs", "One extraction run: what it read, what it proposed, "
            "what it rejected"],
           ["insight_conversions", "One document's reading: which engine read it, "
            "how many pages, and where the markdown went"]],
          widths=[1.9, 5.0])
    para(doc,
         "Why this is not narrative_tags. That table records \"a UNHCR report "
         "mentioned flooding\" - a keyword match on an analyst's prose, rebuilt "
         "from scratch on every pipeline run. This one records \"a community in "
         "Afar said this\", kept because a person reviewed it and published it. "
         "Nothing in the pipeline ever writes here.",
         bold=True)

    heading(doc, "6.8 The job record", 2)
    para(doc,
         "api_pull_job (app: api_calls) is one row per attempt to refresh a data "
         "source - including the attempts that failed. It exists because "
         "source_sync records what is HELD and says nothing about an attempt that "
         "did not land. It is never edited; it is the audit trail, and the \"last "
         "attempt\" column on the Data Refresh page reads from it.")
    doc.add_page_break()


def chapter_pipeline(doc):
    heading(doc, "7. The data pipeline", 1)
    para(doc,
         "Seven steps, run by one command. Each step is a file in "
         "data_pipeline/steps/ with a single run() function.")
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
            "Rebuilds the timeline: hand-checked milestones, plus event sentences "
            "extracted from flash and external updates (at most three per document, "
            "one per verb per month)."],
           ["5", "s05_export.py",
            "Writes the dashboard files from the report tables. This is where "
            "extracted numbers are cleaned before publication - see 7.3."],
           ["6", "s06_mcp_layers.py",
            "Writes the external map layers FROM THE DATABASE: border crossings, "
            "IDP localities, refugee totals and camps, IPC food insecurity per "
            "country, humanitarian service points, the seasonal calendar and the "
            "Areas of Operation."],
           ["7", "s07_xlsx.py",
            "Writes the one layer step 6 does not touch: Sudan IDP bubbles per "
            "state (admin1), also from the database."]],
          widths=[0.5, 1.6, 4.7])

    para(doc,
         "Steps 6 and 7 no longer read files. They used to flatten JSON straight "
         "out of api_cache/ into the dashboard folder. Everything they need now "
         "lives in the external_data tables, and the cache is only the staging area "
         "a pull lands in before it is loaded. What that changes in practice: the "
         "numbers on the dashboard and the numbers an analyst queries in SQL are "
         "the same numbers, from the same rows.",
         bold=True)

    heading(doc, "7.1 What step 6 writes", 2)
    table(doc,
          ["File in dashboard/data/", "Holds", "From"],
          [["crossings.json", "border crossings tagged to corridors", "curated"],
           ["idp_localities.json", "IDP locality bubbles and their monthly series",
            "IOM-DTM"],
           ["refugee_camps.json", "host-country refugee totals and camp markers",
            "UNHCR + Excel"],
           ["ipc_areas_fs.geojson", "Sudan's IPC snapshots over time", "IPC"],
           ["ipc_fs/<ISO3>.geojson", "the same, per country, for the rest",
            "IPC / Cadre Harmonise"],
           ["hsps.geojson", "humanitarian service points, by district", "Kobo"],
           ["seasonal.json", "seasonal calendars, one per country", "ACAPS"],
           ["aoi_ipc.geojson", "IFRC Areas of Operation and their IPC phase",
            "IPC + boundary library"],
           ["idp_states.json", "Sudan admin1 IDP bubbles (written by step 7)",
            "Excel workbook"]],
          widths=[1.9, 3.1, 1.8])
    para(doc,
         "Food security is split per country because one file carrying every "
         "country at every period would be about 14 MB. ipc_areas_fs.geojson keeps "
         "its Sudan-only shape; the per-country files beside it are loaded on "
         "demand.",
         italic=True)

    heading(doc, "7.2 Which steps to run when", 2)
    table(doc, ["Situation", "Command"],
          [["New PDFs have been added", "run_pipeline"],
           ["You changed a parser or taxonomy.json", "run_pipeline --reparse"],
           ["You pulled new external data or reloaded a workbook",
            "run_pipeline --only s06,s07 (or the Rebuild button - see chapter 10)"],
           ["You only want to rebuild the report layers",
            "run_pipeline --only s05"]],
          widths=[3.6, 3.0])
    para(doc,
         "Steps 1 and 2 only ever add to the database, so running them again is "
         "always safe. Steps 3 to 7 delete and rebuild what they own, which is why "
         "re-tuning a parser never requires re-reading a single PDF - and why "
         "hand-curated data must never be put in population_figures, movement_flows, "
         "narrative_tags or events.",
         italic=True)

    heading(doc, "7.3 How numbers are cleaned before publication", 2)
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
         "the slider redraws everything. The country filter is the second idea: it "
         "narrows every panel at once, not only the map.")

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

    heading(doc, "8.2 Country filter (top of the left sidebar)", 2)
    para(doc,
         "A searchable multi-select, with a chip for each country you have chosen. "
         "It governs everything below it, and it also moves the map:")
    bullets(doc, [
        ("One country ", "zooms to it."),
        ("Exactly two ", "split the map into two panes side by side, one country in "
         "each, both fed with identical data - only the viewports differ."),
        ("Three or more ", "zoom out to fit them all in one pane."),
    ])

    heading(doc, "8.3 Map layers", 2)
    para(doc,
         "The first three come from the UNHCR reports. Everything under the \"Data "
         "Layers\" divider comes from the open-data servers and is refreshed as in "
         "chapter 10.")
    table(doc,
          ["Layer", "What it shows", "Where the data comes from"],
          [["Movement out of Sudan", "Red arrows, thickness by volume, with the "
            "cumulative figure on the arrow", "UNHCR reports"],
           ["Movement back into Sudan", "Green arrows: returns, and the influx "
            "from South Sudan", "UNHCR reports"],
           ["Key events", "Dots on the map; recent ones large and bright, older "
            "minor ones fade away", "Curated + extracted"],
           ["IDP by admin2 localities", "One bubble per locality, growing over time",
            "IOM-DTM via HDX"],
           ["IDP by admin1 State", "One bubble per Sudanese state",
            "IOM-DTM, plus Sudan IDPs.xlsx"],
           ["Refugee totals by country", "One bubble per host country",
            "UNHCR via HDX + Excel"],
           ["Settlements and camps", "Camp markers, which appear from the month "
            "they opened", "UNHCR RRP (curated)"],
           ["Food insecurity - IPC phase, by area", "Area-level IPC choropleth "
            "across the analysis periods, with famine areas outlined",
            "IPC and Cadre Harmonise"],
           ["Border crossings", "Crossings, highlighted when their corridor is "
            "active", "Curated"],
           ["Areas of Operation (IFRC)", "The cross-border host regions, filled by "
            "their current IPC phase", "Boundary library + IPC"],
           ["Humanitarian Service Points (IFRC)", "Which services a National "
            "Society offers, by district", "Kobo"]],
          widths=[1.7, 3.1, 2.0])
    para(doc,
         "Hazard events from IFRC Montandon are held in hazard_events and "
         "hazard_impacts, but are not yet drawn on the map or exposed through the "
         "JSON API. Query them in SQL for now.",
         italic=True)

    heading(doc, "8.4 The theme filters", 2)
    para(doc,
         "Under 'What the documents tell us' there is one searchable dropdown per "
         "dimension: hazards, vulnerabilities, coping mechanisms, needs and "
         "movement patterns. Inside a dropdown, ticking a box adds a tag and "
         "clicking a tag's name selects only that one. A selected theme is drawn as "
         "a coloured fill on the area it was reported in - the highest-precedence "
         "one takes the colour and the rest are named in that area's popup. The "
         "panel below lists the counts and a real sentence from a report.")
    para(doc,
         "These filters are built from the data, not hard-coded. Add a keyword group "
         "to taxonomy.json, re-run the pipeline with --reparse, and a new filter "
         "appears by itself.",
         italic=True)

    heading(doc, "8.5 The right-hand panels", 2)
    bullets(doc, [
        ("Trends: ", "written automatically for the current date - the "
         "fastest-growing outflow corridor over the last 90 days, whether returns "
         "and internal displacement are rising or falling, and the most-reported "
         "hazard and need this month."),
        ("Community Insights: ", "the published statements, with three tabs over "
         "one list - Community, Analyst, Both. With the search box empty it shows "
         "the quotes for the month the timeline is on; type in it and it searches "
         "every quote in that tab across the whole archive instead, because any one "
         "month holds only a handful. Clicking a result moves the timeline to that "
         "month. This is the one panel read live from PostgreSQL."),
        ("Top reported hazards: ", "a bar chart of the most-mentioned hazards."),
        ("Movement trends: ", "the three headline series over the whole war, with "
         "ticks on the baseline marking the defining events, and a key underneath "
         "carrying each line's figure for the current date. Click the graph to move "
         "the whole dashboard to that date."),
    ])

    heading(doc, "8.6 The timeline", 2)
    bullets(doc, [
        "Drag the slider to any date from 15 April 2023 onwards.",
        "Press play to animate the whole crisis.",
        "The From and To date pickers either side of the slider set how much of the "
        "war the timeline covers. Narrowing the window narrows the slider itself, "
        "not only the play loop - dragging cannot leave the window either.",
        "The seasonal calendar in the sidebar highlights the month you are in.",
    ])

    heading(doc, "8.7 The legend", 2)
    para(doc,
         "Along the bottom edge of the map, so it covers nothing. It carries the "
         "two arrow directions, key events, the four theme colours, the tint used "
         "for something reported with no place named, rivers and lakes beside flood "
         "reporting, every bubble type, and the IPC scale: phases 1 to 5 plus the "
         "famine outline.")
    doc.add_page_break()


def chapter_updater(doc):
    heading(doc, "9. The updater page - new documents in", 1)
    para(doc, "http://localhost:2026/updater/", bold=True)
    para(doc,
         "This page exists so that adding new UNHCR reports needs no command line "
         "at all.")

    heading(doc, "9.1 The routine", 2)
    steps(doc, [
        "Drop the PDFs into the right year folder of one of the two UNHCR "
        "collections under the source folder.",
        "Open the updater page and press Re-check folders.",
        "Press Update now and watch the progress bar.",
        "The dashboard preview reloads by itself when it finishes.",
    ])

    heading(doc, "9.2 What is on the page", 2)
    table(doc, ["Element", "What it does"],
          [["The big number", "How many PDFs are sitting in the source folders that "
            "the database has never seen, with their file names listed below."],
           ["Update now", "Runs the whole pipeline and streams its progress live. "
            "The bar follows the real steps; the black box shows the log. When there "
            "are no new files the button says 'Rebuild anyway', which re-exports "
            "everything from the stored text - useful after changing a parser."],
           ["Re-check folders", "Looks again without running anything."],
           ["External data layers table", "For each external layer: where it comes "
            "from, when it was last pulled, and when the map layer was last built."],
           ["Rebuild external layers from latest cache", "Runs steps 6 and 7 only. "
            "The same thing the Rebuild dashboard layers button in chapter 10 does."],
           ["Dashboard preview", "The live dashboard in a frame, reloaded "
            "automatically when an update finishes."]],
          widths=[2.0, 4.8])

    heading(doc, "9.3 An update that seems stuck", 2)
    para(doc,
         "Step 2 is genuinely slow on a large batch - it is opening and reading "
         "every new PDF. The log box keeps printing while it works. If it has "
         "stopped printing, check docker compose logs web.")
    doc.add_page_break()


def chapter_refresh(doc):
    heading(doc, "10. Refreshing the open-data layers", 1)
    para(doc, "Admin -> Data Refresh via API -> Data sources", bold=True)
    para(doc, "http://localhost:2026/admin/api_calls/datasource/", bold=True)
    para(doc,
         "This page is the list of every external data source the platform tracks. "
         "One row per source, dataset and country. Each row shows when it was last "
         "pulled, the newest DATA date it holds (which is not the same thing), how "
         "many rows it has, what the last attempt did - and, on the right, its "
         "button.")
    para(doc,
         "The rows are read-only. Every one is written by a loader, so a row "
         "hand-edited in the browser is a row the next refresh silently overwrites.",
         italic=True)

    heading(doc, "10.1 The two buttons at the top of the page", 2)
    table(doc, ["Button", "What it does"],
          [["Pull everything out of date", "Pulls every row that has an API, a key "
            "and something newer to fetch - one at a time, never in parallel. The "
            "note beside it says how many are out of date."],
           ["Rebuild dashboard layers", "Runs pipeline steps 6 and 7, which is what "
            "moves the new figures onto the map. The note beside it says how many "
            "pulls have happened since the last rebuild."]],
          widths=[2.2, 4.6])
    para(doc,
         "These are two buttons on purpose. A pull updates the database only; the "
         "map changes when you rebuild. So the ordinary routine is: pull what you "
         "need, check it looks right, then rebuild once.",
         bold=True)

    heading(doc, "10.2 Pull now, and Reload file", 2)
    para(doc,
         "Most rows carry a Pull now button. It calls the upstream API directly, "
         "saves the raw response under data_pipeline/api_cache/, and loads it into "
         "the database. Pressing it opens a confirmation page first - the refresh "
         "itself is never a plain link, because an IPC pull moves 8-15 MB per "
         "analysis and nothing should be able to start one by prefetching.")
    para(doc,
         "The two Excel rows say Reload file instead, and the different wording is "
         "deliberate: nothing is fetched. That button re-reads whatever has been "
         "SAVED into the workbook under /work and loads it. A row that said \"Pull "
         "now\" would invite the reading that the platform goes looking for figures "
         "the file does not yet contain.")
    table(doc, ["Workbook", "Feeds", "Its --only name"],
          [["neighbouring countries Pop movement data.xlsx",
            "the biweekly refugee series per host country", "neighbours-workbook"],
           ["Sudan IDPs.xlsx", "IDP bubbles per Sudanese state (admin1)",
            "sudan-idps-workbook"]],
          widths=[2.6, 2.4, 1.6])
    para(doc,
         "A workbook's staleness is its fingerprint, not its date. \"Pull "
         "everything out of date\" skips anything already pulled today, which is "
         "right for an API and wrong for a file: an analyst who saves a corrected "
         "figure an hour after the morning load would otherwise be told there is "
         "nothing to do. The file rows compare the sha1 of the workbook instead.",
         italic=True)

    heading(doc, "10.3 A row whose button is greyed out", 2)
    table(doc, ["What it says", "What it means"],
          [["needs IPC_API_KEY in .env", "Add the key (4.2), then "
            "docker compose up -d web. A restart alone does not re-read .env."],
           ["source busy", "Another job for that same source is still running. One "
            "job per source at a time is enforced deliberately - both workbook rows "
            "share source='excel', so they queue behind each other, which is "
            "correct because one command reads them both in one transaction."],
           ["file-based - manage.py load_hsps", "The Kobo service-point rows are "
            "loaded from a workbook by that command."],
           ["CSV export - manage.py load_external acaps_seasonal", "The ACAPS "
            "seasonal rows come from a CSV export, not an API."],
           ["no API behind this source", "Nothing fetches this row automatically."]],
          widths=[2.4, 4.4])

    heading(doc, "10.4 Watching a job", 2)
    para(doc,
         "The \"last attempt\" column on each row is a coloured word - running, "
         "succeeded, failed, or stuck - plus what it did, and it links to that "
         "job's own page with the full log. \"succeeded, already up to date\" is the "
         "ordinary result of an incremental pull and is not a failure. \"stuck\" "
         "means the row claims to be running but no process is behind it.")
    para(doc,
         "Every attempt, including the ones that failed, is kept in the api_pull_job "
         "table. That is the point of it: source_sync records only what is held.")

    heading(doc, "10.5 The same thing from a terminal", 2)
    code(doc, [
        "# what is held, and how fresh",
        "docker compose exec web python manage.py external_status",
        "",
        "# fetch, save and load one source - this is what Pull now runs",
        "docker compose exec web python manage.py refresh_external <source> <dataset> --iso3 <ISO3>",
        "",
        "# re-read a workbook - this is what Reload file runs",
        "docker compose exec web python manage.py load_workbooks --only <variant>",
        "",
        "# put it on the map",
        "docker compose exec web python manage.py run_pipeline --only s06,s07",
    ])
    para(doc,
         "One function decides which command refreshes a row: refresh_argv() in "
         "api_calls/views.py. The button, the confirmation page and the batch pull "
         "all ask it. A second rule written anywhere else is how a row that the "
         "batch accepts starts failing inside every batch while its own button "
         "still works.",
         italic=True)

    heading(doc, "10.6 Three rules that are not guessable", 2)
    bullets(doc, [
        ("Never pull two IPC countries at the same time. ",
         "This is a recorded incident, not a caution: the connection closed and the "
         "server stayed down for the rest of the session. Every pull path in the "
         "platform is strictly serial for this reason."),
        ("IPC pulls are filtered by two lists, not one. ",
         "known_ids says what loaded; skipped_ids says what a person deliberately "
         "excluded, plus anything that came back empty. Without the second list a "
         "refresh re-pulls every exclusion and retries the known-empty analyses "
         "forever."),
        ("The pulls are plain HTTPS, not MCP. ",
         "The container cannot run the MCP servers - they are Node scripts on a "
         "host share that is not mounted into it - so each fetcher calls the "
         "upstream API directly and records the MCP tool it reproduces. The "
         "payloads are identical, because every MCP tool this project uses is a "
         "pass-through wrapper. The distinction matters the day a fetcher and its "
         "tool disagree."),
    ])
    para(doc,
         "The app is called api_calls throughout - package, label, URL and heading. "
         "It was called mcp until 24 September 2026 and was renamed because nothing "
         "here speaks the Model Context Protocol. Specs and plans under "
         "docs/superpowers/ written before that date still say mcp; they are dated "
         "records and were deliberately not rewritten.",
         italic=True)
    doc.add_page_break()


def chapter_insights(doc):
    heading(doc, "11. Community insights - documents in, statements out", 1)
    para(doc, "Admin -> Community insights", bold=True)
    para(doc,
         "This is how what affected people actually said gets onto the dashboard. A "
         "statement is lifted verbatim out of an assessment, feedback or protection "
         "document, checked word-for-word against the page it came from, coded "
         "against the same taxonomy as everything else, and published only after a "
         "person has read it and agreed.")
    para(doc,
         "Two entries in the admin sidebar:")
    bullets(doc, [
        ("Part 1 - Documents to insights. ",
         "The four-step wizard below. This is the route in."),
        ("Part 2 - Insights. ",
         "The statement table itself: for typing one in by hand, for correcting "
         "one, and for auditing anything ever published."),
    ])

    heading(doc, "11.1 The four steps", 2)
    table(doc, ["Step", "What happens"],
          [["1. Bring documents in", "Pick files or a folder from a native window "
            "on your own machine. Nothing is typed as a container path."],
           ["2. Read these documents", "Each PDF or Word file is converted to "
            "per-page markdown - reading order, tables and headings kept, scanned "
            "pages OCR'd. See 11.2."],
           ["3. Extract", "The model proposes statements. This is watchable, and it "
            "survives the tab closing."],
           ["4. Review and publish", "Every proposed statement is read by a person "
            "and published, edited or rejected."]],
          widths=[1.8, 5.0])
    para(doc,
         "Nothing is kept in your browser session. Every step reads its state off "
         "one job row, so closing the tab loses nothing and reopening the wizard "
         "rejoins the batch wherever it got to.",
         italic=True)
    para(doc, "A batch's status reads:")
    code(doc, [
        "collecting -> collected -> converting -> converted -> queued -> running -> loaded",
    ])
    para(doc,
         "'queued' means converted and ready to extract - NOT \"the files are in\". "
         "That is the one word on the page that is easy to read backwards.",
         bold=True)

    heading(doc, "11.2 Step 2: the documents are read before the model sees them", 2)
    para(doc,
         "Docling converts each document to per-page markdown, and that text "
         "REPLACES whatever the pipeline's own PDF text extraction had stored. The "
         "replacement is the point: every quote is later re-matched against the same "
         "page rows the model read, so the two must never diverge.")
    para(doc, "The terminal equivalent, and what the button runs:")
    code(doc, [
        "docker compose exec web python manage.py convert_documents --job <N>",
    ])
    para(doc, "Three things about it that are not guessable:")
    bullets(doc, [
        ("A document Docling cannot read keeps its pipeline text ",
         "and is badged \"Docling failed\" on the preview. A re-read always tries "
         "Docling again first - the fallback is never sticky."),
        ("A document that already has a non-rejected statement is refused. ",
         "Moving the page text under a quote that was verified against it would "
         "invalidate that check with nothing left to say so. The practical cost: a "
         "batch already extracted from the weaker text cannot be upgraded without "
         "rejecting its pending queue first."),
        ("A batch whose files have been swept refuses to be read, ",
         "rather than badging every document \"Docling failed\" and quietly "
         "extracting from the weaker text. The page says the files were released "
         "and links to a new import. A document already read successfully is not "
         "affected."),
    ])
    para(doc,
         "OCR languages: see the warning in 4.4. en,ar or en,fr, never both.",
         italic=True)

    heading(doc, "11.3 Step 3: what the model may and may not write", 2)
    para(doc,
         "The extraction contract lives in insights/prompts/extract_insights.md and "
         "is the single source of truth for it. The two rules worth knowing without "
         "opening that file:")
    bullets(doc, [
        ("The quote is verbatim and whole. ",
         "Never summarised, never trimmed. Every proposed quote is re-matched "
         "against the stored page text, and one that does not match exactly is "
         "rejected before anybody sees it. The job page counts those rejections."),
        ("Interpretation is separate from the statement. ",
         "The themes read out of a statement are rows of their own, each with a "
         "dimension (hazard, vulnerability, need, coping, movement pattern), a tag "
         "from taxonomy.json, and a role: subject, driver or barrier. 'driver' is "
         "what makes \"why are they returning\" a query rather than a reading "
         "exercise. Numbers and corridors mentioned in a statement are separate "
         "rows again."),
    ])

    heading(doc, "11.4 Step 4: review and publish", 2)
    para(doc,
         "Nothing reaches the dashboard until a person publishes it. A statement is "
         "pending, published or rejected; the row keeps who reviewed it and when. "
         "The Community Insights panel on the dashboard reads published rows only, "
         "live from PostgreSQL, and there is no query parameter anywhere that will "
         "return a pending or rejected one.")

    heading(doc, "11.5 A statement's own fields", 2)
    table(doc, ["Field", "Meaning"],
          [["quote", "Verbatim, in full. Plus its language, and a translation when "
            "there is one."],
           ["voice_type", "Community voice, or secondary analysis"],
           ["channel", "Document (AI), typed by hand, or primary collection"],
           ["document, page", "Which document and page it came from. Null for a "
            "statement typed in by hand."],
           ["stated_on", "The report or collection date. The dashboard timeline "
            "rides on this."],
           ["place_name_as_written, admin_pcode, admin_level, match_method",
            "Where it is about, and how confidently that place was matched: by "
            "p-code, by name, or unmatched."],
           ["people_affected, severity", "When the statement carries them"],
           ["method, model_used, confidence", "How it was produced"],
           ["status, reviewed_by, reviewed_at, rejection_reason", "The review trail"]],
          widths=[2.4, 4.4])

    heading(doc, "11.6 The uploaded document is not kept", 2)
    para(doc,
         "What the platform keeps is the text read out of a document and the "
         "statements published from it - not the document. The file under media/ is "
         "deleted as soon as that document has no pending statement left, and swept "
         "after INSIGHT_UPLOAD_RETENTION_MINUTES (default 30) whether anybody "
         "reviewed it or not.")
    bullets(doc, [
        "Releasing a file blanks one column and touches nothing else. The document, "
        "its page text and every statement stay.",
        "There is no scheduler here, so the sweep runs on wizard page loads and "
        "from manage.py prune_uploads - which is what you would put on a cron.",
        "A batch that is still converting is skipped until Docling finishes with it.",
        "Re-importing a released file stores the bytes again and MOVES that "
        "document's still-pending statements to the new batch, so the review queue "
        "follows the person rather than being extracted a second time.",
    ])
    para(doc,
         "Retention follows rows, never the folder. Nothing deletes a file because "
         "the database does not mention it - a file left behind by deleting an "
         "upload in the admin site stays until a person removes it. \"No row claims "
         "it\" is only as true as the database being asked, and asked against an "
         "empty one - a test run, a restored dump - the answer is every file in the "
         "folder. An earlier version swept unclaimed files from the wizard's page "
         "load, and manage.py test emptied this deployment's upload folder.",
         bold=True)

    heading(doc, "11.7 An archive already on a mounted share", 2)
    para(doc,
         "Do not upload it. Register it as a folder instead - nothing is copied that "
         "way. Which folders may be browsed is INSIGHT_DOCUMENT_ROOTS (4.4); there "
         "is no hardcoded path.")

    heading(doc, "11.8 Reading the statements back out", 2)
    code(doc, [
        "/api/insights/     published statements, live from PostgreSQL",
        "",
        "Filters: ?voice_type= &iso3= &dimension= &tag= &role= &flow_type=",
        "         &admin_pcode= &from= &to= &q= &limit=",
    ])
    doc.add_page_break()


def chapter_admin_api(doc):
    heading(doc, "12. The admin site and the JSON API", 1)

    heading(doc, "12.1 Admin", 2)
    para(doc, "http://localhost:2026/admin/", bold=True)
    para(doc,
         "A ready-made interface onto every table: search, filter, drill down by "
         "date, and edit. The sidebar groups it by app:")
    table(doc, ["Section", "What is in it"],
          [["Data tables", "The seven report tables (6.1)"],
           ["Data Refresh via API", "Data sources, and the pull job log (chapter 10)"],
           ["External data", "Food security, movement, seasonal, hazards, "
            "crossings, service points"],
           ["Boundary library", "Sources, admin areas, map features"],
           ["Community insights", "Part 1 (the wizard) and Part 2 (the statements)"]],
          widths=[2.0, 4.6])
    para(doc,
         "The most common use is auditing a number: search for a figure, open the "
         "row, read the snippet it was taken from, and follow the link to the source "
         "document.")
    para(doc,
         "Log in with the user created from DJANGO_SUPERUSER_PASSWORD in .env, or "
         "create one with:")
    code(doc, ["docker compose exec web python manage.py createsuperuser"])

    heading(doc, "12.2 JSON API", 2)
    para(doc,
         "Read-only, always live from PostgreSQL. Useful for feeding another tool "
         "without exporting files.")
    para(doc, "The report tables:")
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
    para(doc, "The open data, the statements and the boundaries:")
    table(doc, ["Address", "Returns"],
          [["/api/external/", "The index of the external endpoints"],
           ["/api/seasonal/", "Seasonal calendars"],
           ["/api/food-security/", "IPC / Cadre Harmonise / FEWS NET area phases"],
           ["/api/movement/", "IDP, refugee, returnee and asylum-seeker counts"],
           ["/api/hsps/", "Humanitarian service points"],
           ["/api/crossings/", "Border crossings"],
           ["/api/sync/", "The freshness of every data source"],
           ["/api/community-insights/", "Sentences from the UNHCR reports, by theme "
            "- read straight from narrative_tags. NOT the published statements; "
            "those are the endpoint below."],
           ["/api/insights/", "Published statements, with their codings, figures "
            "and corridors (11.8)"],
           ["/api/boundaries/layers/", "The boundary catalogue: what is held, from "
            "whom, valid when"],
           ["/api/boundaries/layer/", "One whole administrative level as GeoJSON"],
           ["/api/boundaries/features/", "Exactly these p-codes - what the map's "
            "highlighting asks for"]],
          widths=[2.2, 4.6])
    para(doc,
         "Note the difference between /api/headline/ (raw rows, exactly as stored) "
         "and dashboard/data/headline.json (the same series after the cleaning "
         "described in 7.3). The dashboard uses the cleaned version.",
         italic=True)

    heading(doc, "12.3 Connecting other tools to the database", 2)
    table(doc, ["Setting", "Value"],
          [["Host", "localhost"],
           ["Port", "5432 (or POSTGRES_HOST_PORT from .env)"],
           ["Database", "sudan_neighbouring_pop_movement"],
           ["User", "sudan"],
           ["Password", "whatever you set in .env"]],
          widths=[2.0, 4.6])
    para(doc,
         "Because the database is PostGIS, QGIS and Power BI can open admin_areas "
         "and map_features directly as map layers.",
         italic=True)
    doc.add_page_break()


def chapter_sources(doc):
    heading(doc, "13. Where the data comes from", 1)

    heading(doc, "13.1 The UNHCR corpus", 2)
    para(doc,
         "Two folders of situation reports, kept beside the repository under the "
         "source folder:")
    bullets(doc, [
        "UNHCR Regional Population Movement pdfs",
        "UNHCR Sudan only pdfs",
    ])
    para(doc,
         "They are not in the repository, and they do not need to be: the whole "
         "point of storing the page text is that the analysis survives without them.")

    heading(doc, "13.2 The open-data sources", 2)
    table(doc, ["Source", "What it gives", "Key needed"],
          [["IPC", "Area-level food-security phases, per analysis period",
            "IPC_API_KEY"],
           ["Cadre Harmonise", "The same for West and Central Africa",
            "IPC_API_KEY"],
           ["FEWS NET", "Food-security phases and seasonal calendars", "none"],
           ["HDX HAPI", "IOM-DTM IDP counts by locality", "HDX_API_TOKEN"],
           ["UNHCR", "Refugee, returnee and asylum-seeker counts - served through "
            "HDX HAPI, so it uses the same token", "HDX_API_TOKEN"],
           ["ACAPS", "Seasonal calendars, at admin-1, from a CSV export", "none"],
           ["IFRC Montandon", "Disaster events and their impacts, as GDACS, PDC and "
            "IDMC published them", "IFRC_API_TOKEN"],
           ["Kobo", "Which services a National Society offers, by district - from a "
            "workbook", "none"],
           ["Excel workbooks", "The biweekly refugee series, and Sudan IDPs by "
            "state", "none"]],
          widths=[1.5, 3.7, 1.6])

    heading(doc, "13.3 What is genuinely per-location", 2)
    table(doc, ["Layer", "Source", "The honest resolution"],
          [["IDP localities", "IOM-DTM via HDX",
            "Real per-locality (admin2) series"],
           ["IDP by state", "Excel workbook", "Real per-state (admin1) series"],
           ["Refugee totals", "UNHCR via HDX + Excel",
            "Real, but per host COUNTRY only - the servers do not publish per-camp "
            "series. Camp dots mark locations, not counts."],
           ["Food insecurity", "IPC / Cadre Harmonise",
            "Real per analysis area, per period"],
           ["Areas of Operation", "IPC + boundary library",
            "The worst IPC phase of the sub-areas inside each region. Not every "
            "area has IPC coverage; those are shown as such."],
           ["Seasonal calendar", "ACAPS, FEWS NET", "National, and admin-1 where "
            "ACAPS publishes it"],
           ["Service points", "Kobo", "District-level only: 'this service is offered "
            "somewhere in this district'. The dot is a label position."],
           ["Border crossings", "Curated", "Hand-checked operational geography"],
           ["Boundaries", "OCHA COD and equivalents",
            "Authoritative, with p-codes and a validity date on every polygon"]],
          widths=[1.5, 1.7, 3.6])
    doc.add_page_break()


def chapter_maintenance(doc):
    heading(doc, "14. Routine maintenance", 1)

    heading(doc, "14.1 The three refresh routines, side by side", 2)
    table(doc, ["When", "Where you go", "What you press"],
          [["New UNHCR reports have arrived", "The updater page",
            "Re-check folders, then Update now"],
           ["The open data is out of date", "Admin -> Data Refresh via API",
            "Pull now (or Pull everything out of date), then Rebuild dashboard "
            "layers"],
           ["A workbook has been corrected", "Admin -> Data Refresh via API",
            "Reload file on that row, then Rebuild dashboard layers"],
           ["New assessment documents to read",
            "Admin -> Community insights -> Part 1",
            "The four steps, ending in Review and publish"]],
          widths=[2.2, 2.4, 2.2])

    heading(doc, "14.2 Changing what is extracted from the documents", 2)
    table(doc, ["To change...", "Edit...", "Then run"],
          [["Which theme filters exist", "data_pipeline/taxonomy.json", "--reparse"],
           ["Places and corridors", "data_pipeline/gazetteer.json", "--reparse"],
           ["How figures are read", "data_pipeline/steps/s03_parse.py", "--reparse"],
           ["The curated milestones", "data_pipeline/steps/s04_events.py", "--reparse"],
           ["How numbers are cleaned", "data_pipeline/steps/s05_export.py",
            "--only s05"],
           ["What the model extracts", "insights/prompts/extract_insights.md",
            "a new extraction batch"],
           ["The map itself",
            "dashboard/static/dashboard/js/app.js, css/app.css, "
            "dashboard/templates/dashboard/index.html",
            "nothing - just refresh"]],
          widths=[2.2, 3.0, 1.6])

    heading(doc, "14.3 After a code change", 2)
    para(doc,
         "The web container runs gunicorn, which never autoreloads.", bold=True)
    bullets(doc, [
        "Python changes: docker compose restart web.",
        "A change to .env or the compose file: docker compose up -d web. A restart "
        "reuses the environment the container was created with.",
        "A change to requirements.txt: docker compose up -d --build.",
        "The dashboard's own app.js or app.css: nothing at all - just refresh.",
    ])
    para(doc,
         "After a model change, migrating alone is not enough. The symptom is not a "
         "stale page: adding a field sets a database default only to backfill it and "
         "then drops it, so a worker that booted before the field existed omits the "
         "column from its INSERT and the next request raises NotNullViolation. "
         "manage.py test forks a fresh process, so the whole test suite stays green "
         "while the running site is broken. Restart the web container.",
         bold=True)
    para(doc,
         "A restart takes about 90 seconds, almost all of it the collectstatic line "
         "in entrypoint.sh, which is slow over a synced folder.",
         italic=True)

    heading(doc, "14.4 Auditing a number", 2)
    para(doc,
         "Every figure keeps the parser that produced it (method), a confidence "
         "level and the snippet it was read from.")
    bullets(doc, [
        ("The easy way: ", "/admin/ -> Population figures. Filter by metric, country "
         "or confidence, open a row, read the snippet, follow the link to the "
         "source document."),
        ("With SQL: ", "pgAdmin at :5050, or any client on localhost:5432."),
        ("Over HTTP: ", "/api/figures/?metric=idps&country=Sudan"),
    ])
    code(doc, [
        "-- where did a number come from?",
        "SELECT d.file_name, f.value, f.method, f.snippet",
        "FROM population_figures f JOIN documents d ON d.id = f.document_id",
        "WHERE f.country = 'Chad' AND f.metric = 'cumulative_arrivals'",
        "ORDER BY f.report_date DESC LIMIT 10;",
        "",
        "-- documents dated only by file-modified time (the weakest evidence)",
        "SELECT file_name, report_date FROM documents WHERE date_source = 'mtime';",
    ])
    para(doc,
         "If a wrong value reaches the dashboard, fix the PARSER in s03_parse.py. "
         "Deleting the row alone will not last, because --reparse rebuilds it.",
         bold=True)

    heading(doc, "14.5 Backing up", 2)
    code(doc, [
        "# Save the whole database to a file",
        "docker compose exec db pg_dump -U sudan sudan_neighbouring_pop_movement > backup.sql",
        "",
        "# Restore it into an empty database",
        "docker compose exec -T db psql -U sudan sudan_neighbouring_pop_movement < backup.sql",
    ])
    para(doc,
         "This dump is the only backup of the database and the normal way to seed "
         "a second instance. Take one before any migration or bulk edit. The data "
         "lives in the Docker volume pgdata, which survives docker compose down; "
         "only docker compose down -v destroys it. The volume is deliberately not a "
         "folder inside this repository, because the repository sits in a synced "
         "directory and letting a sync client touch live database files corrupts "
         "them.")

    heading(doc, "14.6 Changing the database structure", 2)
    code(doc, [
        "# 1. edit the models.py of the app that owns the table",
        "# 2. create the migration",
        "docker compose exec web python manage.py makemigrations <app>",
        "# 3. apply it",
        "docker compose exec web python manage.py migrate",
        "# 4. restart, or the running workers will not know about the new column",
        "docker compose restart web",
    ])

    heading(doc, "14.7 Rebuilding this document", 2)
    para(doc,
         "This manual is generated from a script, so it can be regenerated whenever "
         "the project changes. Edit docs/build_docs.py, then:")
    code(doc, ["docker compose exec web python /docs/build_docs.py"])

    heading(doc, "14.8 Things that still need a human", 2)
    bullets(doc, [
        ("Curated events. ", "The extractor catches incident sentences "
         "automatically, but defining milestones - a city falling, a famine "
         "declaration - deserve a hand-written entry in s04_events.py with a "
         "severity rating."),
        ("New document layouts. ", "If a series is redesigned, spot-check the new "
         "files and extend the matching parser in s03_parse.py. Detection is "
         "content-based, so old layouts keep working."),
        ("Estimate revisions. ", "Big jumps are accepted only once later reports "
         "confirm them, so a genuine revision appears after the next one or two "
         "documents. This lag is deliberate."),
        ("Every published statement. ", "Nothing in chapter 11 reaches the "
         "dashboard without a person reading it first."),
    ])
    doc.add_page_break()


def chapter_limits(doc):
    heading(doc, "15. Known limitations", 1)
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
        ("Areas of Operation take the worst phase inside them. ",
         "Areas with no current IPC analysis are shown as having none, rather than "
         "as safe."),
        ("Service points are district-level. ",
         "A dot means a service is offered somewhere in that district, not that "
         "there is a site at that point."),
        ("A pull does not move the map. ",
         "Fresh figures are in the database as soon as a pull succeeds, but the "
         "dashboard shows them only after a rebuild. The page tells you how many "
         "pulls are waiting."),
        ("Community statements are a sample, not a survey. ",
         "They are what was written down in the documents that happened to be read, "
         "and published only where a reviewer agreed. Counts of them measure "
         "reporting, not prevalence."),
        ("Three publishers can report the same disaster. ",
         "Montandon hazard events are one row per source, tied together by corr_id. "
         "Counting rows counts reports, not events."),
    ])
    doc.add_page_break()


def chapter_troubleshooting(doc):
    heading(doc, "16. Troubleshooting", 1)
    table(doc, ["Symptom", "Likely cause and fix"],
          [["Nothing at localhost:2026",
            "The web container is still starting, or crashed. Run "
            "docker compose logs -f web and read the last lines."],
           ["'env file .env not found'",
            "Copy env.example to .env."],
           ["Compose refuses to start, naming POSTGRES_PASSWORD",
            "That variable has no default on purpose. Set one in .env."],
           ["Port already in use",
            "Something else uses 2026, 5432 or 5050. Change WEB_HOST_PORT, "
            "POSTGRES_HOST_PORT or PGADMIN_HOST_PORT in .env and restart."],
           ["Dashboard loads but everything is empty",
            "The database has no data yet. Restore a pg_dump backup, or run "
            "run_pipeline."],
           ["The updater says 0 new files but you added some",
            "The PDFs are outside SOURCE_ROOT, or not in one of the two named "
            "collection folders. Check SOURCE_HOST_DIR and the volume mount."],
           ["Password change had no effect",
            "PostgreSQL keeps the credentials it was created with. See 4.6 - and do "
            "not use down -v, which deletes the database."],
           ["pgAdmin asks for a password",
            "That is the database password from .env, not the pgAdmin login."],
           ["An update seems stuck",
            "Step 2 is genuinely slow on a large batch. The log box keeps printing; "
            "if it has stopped, check docker compose logs web."],
           ["Changed the code but nothing happened",
            "Python changes need docker compose restart web. Changes to "
            "requirements.txt need docker compose up -d --build. The dashboard's "
            "own JS and CSS need neither - just refresh."],
           ["NotNullViolation: null value in column \"...\"",
            "A model gained a field and the running workers pre-date it. "
            "docker compose restart web. The test suite will not show this, because "
            "it forks a fresh process."],
           ["Changed a value in .env and nothing happened",
            "docker compose restart does not re-read .env. Use "
            "docker compose up -d web, which recreates the container."],
           ["A Pull now button is greyed out",
            "It says why: a missing key, or the source is busy with another job. "
            "See 10.3."],
           ["A pull succeeded but the map is unchanged",
            "A pull updates the database only. Press Rebuild dashboard layers."],
           ["A pull job sits at 'queued' and blocks the source",
            "Open the job page from the 'last attempt' column and read the log. A "
            "job shown as 'stuck' has no process behind it."],
           ["A document is badged 'Docling failed'",
            "It kept its pipeline text and can still be extracted from. Re-reading "
            "always tries Docling again first."],
           ["Step 2 says the files were released",
            "The uploads were swept after the retention window. Import them again "
            "from the link on that page; any pending statements move to the new "
            "batch."],
           ["Step 2 refuses a document",
            "It already has a non-rejected statement. Reject that batch's pending "
            "queue first, or leave the document as it is."],
           ["Arabic documents come out as gibberish",
            "DOCLING_OCR_LANGS must be en,ar - and it cannot also contain fr. "
            "Change it in .env, then docker compose restart web."],
           ["The map has no basemap under it",
            "The Mapbox style or token is wrong. The working defaults are in "
            "config/settings.py; an override in .env wins over them."]],
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
    chapter_refresh(doc)
    chapter_insights(doc)
    chapter_admin_api(doc)
    chapter_sources(doc)
    chapter_maintenance(doc)
    chapter_limits(doc)
    chapter_troubleshooting(doc)

    doc.save(OUT_PATH)
    print(f"written: {OUT_PATH}")


if __name__ == "__main__":
    build()
