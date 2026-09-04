"""Django settings - the single place where the whole project is configured.

Read this file top-to-bottom to understand how the platform is wired:
  * where the code lives (BASE_DIR / REPO_DIR)
  * where the *data* lives (the UNHCR PDFs, the dashboard JSON, the caches)
  * which database to use (PostgreSQL, credentials come from the .env file)
  * which apps are installed (data_track / data_pipeline / dashboard / updater)

Nothing secret is written here. Every password or key is read from the
environment with os.environ.get("NAME", "fallback"), and docker compose loads
those names out of the .env file in the project root.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# --------------------------------------------------------------------------
# 1. Folders
# --------------------------------------------------------------------------
# BASE_DIR  = .../Community Centered Humanitarian Analysis/Community Centered Humanitarian Analysis Platform   (this Django project)
# REPO_DIR  = .../Community Centered Humanitarian Analysis              (the git repository root)
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def env_path(name: str, default: Path) -> Path:
    """Read a folder path from an environment variable, or use the default.

    Inside Docker the folders live under /work; on a laptop they sit next to
    the repository. Using environment variables means the same code works in
    both places without editing anything.
    """
    value = os.environ.get(name)
    return Path(value) if value else default


# Where the source PDFs live. They are NOT in the repository: they sit in the
# parent "SUDAN Ops" folder, in two collections (see SOURCE_COLLECTIONS below).
SOURCE_ROOT = env_path("SOURCE_ROOT", REPO_DIR.parent)

# The dashboard is part of this Django project, not a folder beside it:
#   dashboard/templates/dashboard/index.html   the page
#   dashboard/static/dashboard/css|js          stylesheet and script
#   dashboard/data/                            the files below
# Only the data folder needs a setting, because data_pipeline writes into it and
# a view reads back out of it. Templates and static files are found by Django's
# own app loaders and need no path here.
DASHBOARD_DATA_DIR = env_path("DASHBOARD_DATA_DIR", BASE_DIR / "dashboard" / "data")

# Raw pulls from the humanitarian MCP servers (HDX, IPC, FEWS NET, UNHCR).
# These are fetched by an analyst in Claude Code, NOT by this app; the
# pipeline only re-reads whatever sits in the folder. See data_pipeline/README.md.
MCP_CACHE_DIR = env_path("MCP_CACHE_DIR", BASE_DIR / "data_pipeline" / "mcp_cache")

# The two folders of UNHCR situation reports that the pipeline reads.
SOURCE_COLLECTIONS = {
    "regional": SOURCE_ROOT / "UNHCR Regional Population Movement pdfs",
    "sudan_only": SOURCE_ROOT / "UNHCR Sudan only pdfs",
}

# Excel workbook (kept beside the PDFs) used by data_pipeline step 7.
POP_MOVEMENT_XLSX = env_path(
    "POP_MOVEMENT_XLSX", SOURCE_ROOT / "neighbouring countries Pop movement data.xlsx"
)

# --------------------------------------------------------------------------
# 2. Core Django security / debug switches
# --------------------------------------------------------------------------
# The secret key signs cookies and sessions. The fallback below is fine for a
# local install; set DJANGO_SECRET_KEY in .env before putting this on a server.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")

# DEBUG=True shows full error pages. Turn it off (DJANGO_DEBUG=0) in production.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Which host names this site answers to. "*" = any, which is fine locally.
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Browsers refuse cross-origin POSTs unless the origin is trusted. Needed when
# the dashboard is opened through a hostname other than localhost.
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# --------------------------------------------------------------------------
# 3. Applications and middleware
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",          # the built-in database admin site at /admin/
    "django.contrib.auth",           # users and permissions (the admin login)
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",    # collects CSS/JS for serving
    "data_track",                    # the seven database tables + the JSON API
    "data_pipeline",                 # the ETL steps, as manage.py commands
    "dashboard",                     # serves the MapLibre dashboard
    "updater",                       # the one-click "Update now" page
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files straight from Django, so no nginx container.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Every template lives in its app's own templates/ folder, which
        # APP_DIRS finds by itself. Nothing outside the project is searched.
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# 4. The database - PostgreSQL, connection details from the environment
# --------------------------------------------------------------------------
# NOTHING about the database is hard-coded here. All five values come from the
# environment, which docker compose fills in from the .env file beside
# docker-compose.yml. .env is git-ignored and never published, so a copy of
# this repository carries no database and no credentials: whoever clones it
# copies env.example to .env, points it at their own PostgreSQL, and starts.
#
# The name, user, host and port fall back to the values of the PostgreSQL
# container that ships with this project, so the bundled stack works with no
# configuration. The password has no fallback on purpose - see below.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "sudan_neighbouring_pop_movement"),
        "USER": os.environ.get("POSTGRES_USER", "sudan"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        # "db" is the service name of the PostgreSQL container in docker-compose.
        # Set POSTGRES_HOST in .env to use a database somewhere else instead.
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Keep one connection open for a minute instead of reconnecting per request.
        "CONN_MAX_AGE": 60,
    }
}

# A default password would be worse than none: a fresh clone would appear to
# work while quietly using a password that is printed in a public repository.
# Better to stop immediately and say what is missing.
if not DATABASES["default"]["PASSWORD"]:
    raise ImproperlyConfigured(
        "POSTGRES_PASSWORD is not set, so there is nothing to connect to the "
        "database with.\n"
        "Copy env.example to .env next to docker-compose.yml, set "
        "POSTGRES_PASSWORD in it, and start again.\n"
        "To use a PostgreSQL server you already have, set POSTGRES_HOST, "
        "POSTGRES_PORT, POSTGRES_DB and POSTGRES_USER in the same file."
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# 5. Language, time and static files
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = os.environ.get("TZ", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # collectstatic writes here (used in Docker)

# WhiteNoise normally serves the copies made by collectstatic at start-up, which
# would mean restarting the web container after every tweak to the dashboard's
# app.js or app.css. With DEBUG on it re-reads the originals on each request
# instead, so a browser refresh is enough - the same as before the dashboard
# moved into Django. Turn DEBUG off and the fast, cached behaviour returns.
WHITENOISE_AUTOREFRESH = DEBUG
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compress static files so browsers download less.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# 6. Project-specific settings used by the pipeline and the updater page
# --------------------------------------------------------------------------
# Link shown on the updater page ("open the dashboard").
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "/")

# The crisis clock starts the day fighting broke out in Khartoum.
CRISIS_START = "2023-04-15"

# Send log lines to the container console so "docker compose logs" shows them.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
