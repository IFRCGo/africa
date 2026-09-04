"""Serves the interactive map dashboard.

Everything the dashboard needs now lives inside this app:

    dashboard/templates/dashboard/index.html   the page itself
    dashboard/static/dashboard/css/app.css     its styling
    dashboard/static/dashboard/js/app.js       its behaviour
    dashboard/data/                            the JSON + GeoJSON it fetches

Two views do all the work:

  index()      renders the page for the address "/"
  data_file()  sends one file out of dashboard/data/, e.g. data/events.json

The stylesheet and script are ordinary Django static files: the template
addresses them with {% static %} and WhiteNoise serves them.

The data files are deliberately NOT static files. The pipeline rewrites them
every time it runs, and static files are collected once at start-up; serving
them through this view instead means a browser refresh shows the new numbers
immediately, with no collectstatic and no restart.
"""
import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render

# GeoJSON is not in Python's built-in table of file types, so register it.
# Without this the browser would receive the boundary files as plain text.
mimetypes.add_type("application/geo+json", ".geojson")


def index(request):
    """Return the dashboard page itself."""
    return render(request, "dashboard/index.html")


def data_file(request, path: str):
    """Return one file from dashboard/data/, e.g. data/boundaries/aoi.geojson."""
    base = settings.DASHBOARD_DATA_DIR.resolve()
    target = (base / path).resolve()

    # Safety check: refuse addresses like ../../secret that try to climb out
    # of the data folder.
    if not target.is_relative_to(base) or not target.is_file():
        raise Http404("file not found")

    content_type, _ = mimetypes.guess_type(target.name)
    response = FileResponse(
        target.open("rb"), content_type=content_type or "application/octet-stream"
    )
    # The pipeline rewrites these files, so never let a browser cache them.
    response["Cache-Control"] = "no-store"
    return response
