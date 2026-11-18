#!/usr/bin/env python
"""Command-line entry point for everything you do to this project.

Examples:
    python manage.py migrate            create/update the PostgreSQL tables
    python manage.py createsuperuser    make a login for the /admin/ site
    python manage.py run_pipeline       ingest new PDFs and rebuild the dashboard
    python manage.py runserver          start a development web server
"""
import os
import sys


def main():
    # Every manage.py command needs to know where the settings live.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # Django is not installed / wrong virtualenv
        raise ImportError(
            "Could not import Django. Is it installed and is your virtual "
            "environment active? Try: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
