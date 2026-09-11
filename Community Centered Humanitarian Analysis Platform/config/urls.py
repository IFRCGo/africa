"""The site map: which web address (URL) runs which piece of code.

Django reads this list from top to bottom and uses the first pattern that
matches the address in the browser.

Four apps, and each one owns everything behind its address:

  /                 -> the MapLibre map                        dashboard app
  /data/...         -> the JSON + GeoJSON the map fetches       dashboard app
  /updater/         -> the one-click "Update now" page          updater app
  /updater/api/...  -> what that page calls in the background   updater app
  /api/insights/    -> published community statements, read live       insights app
  /api/...          -> read-only JSON built live from PostgreSQL data_track app
  /admin/           -> browse and edit every table by hand      data_track tables
  /static/...       -> the CSS and JavaScript of both pages     served by WhiteNoise

The fifth app, data_pipeline, has no address at all: it is run from the updater
page or from manage.py. See data_pipeline/README.md and data_track/README.md.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # The dashboard is the front page, so it is listed first.
    path("", include("dashboard.urls")),
    path("updater/", include("updater.urls")),
    # Listed before data_track's "api/" so that /api/boundaries/... is matched
    # here rather than falling through to the report API.
    path("api/boundaries/", include("boundaries.urls")),
    # Same reason: external_data owns specific paths under api/, so it is matched
    # before data_track's catch-all include.
    path("api/", include("external_data.urls")),
    # Same reason: insights owns a specific path under api/, so it is matched
    # before data_track's catch-all include.
    path("api/", include("insights.urls")),
    path("api/", include("data_track.urls")),
    path("admin/", admin.site.urls),
]
