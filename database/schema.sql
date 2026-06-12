-- Sudan Crisis Story Database
-- Master store: survives source-document deletion. SQLite 3.
-- Rebuild: python pipeline/run_all.py

PRAGMA journal_mode = WAL;

-- Every source PDF, catalogued with family classification and report date
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    file_name       TEXT NOT NULL,
    rel_path        TEXT NOT NULL UNIQUE,   -- relative to SUDAN Ops root
    source_collection TEXT,                 -- 'regional' | 'sudan_only'
    year_folder     INTEGER,
    family          TEXT,                   -- document series, e.g. 'weekly_mapping', 'chad_core'
    country_focus   TEXT,                   -- ISO-ish country name the doc reports on
    report_date     TEXT,                   -- ISO yyyy-mm-dd
    date_source     TEXT,                   -- 'filename' | 'text' | 'mtime'
    pages           INTEGER,
    file_size       INTEGER,
    sha1            TEXT,
    extracted_at    TEXT
);

-- Full raw text per page (the corpus archive: the story survives even if PDFs are deleted)
CREATE TABLE IF NOT EXISTS document_text (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page        INTEGER NOT NULL,
    text        TEXT,
    PRIMARY KEY (document_id, page)
);

-- Structured population observations (stocks and cumulative arrival counts)
CREATE TABLE IF NOT EXISTS population_figures (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER REFERENCES documents(id),
    report_date   TEXT,
    country       TEXT,        -- where the population is
    location      TEXT,        -- finer location if known
    lat           REAL, lon REAL,
    metric        TEXT,        -- 'cumulative_arrivals','idps','total_displaced','refugees_in_country',
                               -- 'returnees','returns_to_sudan','self_relocated', etc.
    population_group TEXT,     -- 'sudanese_refugees','refugee_returnees','tcn','mixed','idps'
    value         INTEGER,
    method        TEXT,        -- parser that produced it
    confidence    TEXT,        -- 'high','medium','low'
    snippet       TEXT
);

-- Directional movement corridors over time (drives the flow arrows + time slider)
CREATE TABLE IF NOT EXISTS movement_flows (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER REFERENCES documents(id),
    report_date  TEXT,
    corridor     TEXT,       -- e.g. 'sudan-chad', 'egypt-sudan-return'
    origin       TEXT, origin_lat REAL, origin_lon REAL,
    destination  TEXT, dest_lat REAL, dest_lon REAL,
    flow_type    TEXT,       -- 'cross_border' | 'internal' | 'return'
    value        INTEGER,    -- cumulative persons as of report_date
    snippet      TEXT
);

-- Key events timeline (curated milestones + extracted from narrative docs)
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    event_date  TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    category    TEXT,        -- 'conflict','displacement','access','disease','flood','famine','policy','return'
    location    TEXT,
    lat         REAL, lon REAL,
    severity    INTEGER,     -- 1..5 (5 = defining moment of the crisis)
    source      TEXT,        -- 'curated' or document family
    document_id INTEGER REFERENCES documents(id)
);

-- Thematic tags: hazards, vulnerabilities, coping mechanisms, needs, movement patterns
-- (drives the platform toggles)
CREATE TABLE IF NOT EXISTS narrative_tags (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    report_date TEXT,
    dimension   TEXT,        -- 'hazard','vulnerability','coping','need','movement_pattern'
    tag         TEXT,        -- normalized tag, e.g. 'flooding','gbv_risk','food'
    country     TEXT,
    snippet     TEXT
);

-- Gazetteer used for geocoding
CREATE TABLE IF NOT EXISTS locations (
    name    TEXT PRIMARY KEY,
    country TEXT,
    admin1  TEXT,
    lat     REAL, lon REAL,
    kind    TEXT,            -- 'capital','town','camp','border_crossing','state','country_anchor'
    aliases TEXT             -- pipe-separated alternates
);

CREATE INDEX IF NOT EXISTS idx_figures_date   ON population_figures(report_date);
CREATE INDEX IF NOT EXISTS idx_figures_metric ON population_figures(metric, country);
CREATE INDEX IF NOT EXISTS idx_flows_date     ON movement_flows(report_date, corridor);
CREATE INDEX IF NOT EXISTS idx_tags_dim       ON narrative_tags(dimension, tag, report_date);
CREATE INDEX IF NOT EXISTS idx_events_date    ON events(event_date);
