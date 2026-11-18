"""Addresses that serve the dashboard, mounted at the site root by config/urls.py.

Only two are needed now that the dashboard is a normal Django app:

    /            the page, rendered from dashboard/templates/dashboard/
    /data/...    the JSON + GeoJSON files, read from dashboard/data/

The stylesheet and script are no longer listed here: they are static files,
addressed in the template with {% static %} and served from /static/dashboard/.
"""
from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.index, name="dashboard"),
    # ".+" rather than a plain segment, so nested paths such as
    # data/boundaries/admin0.geojson also match.
    re_path(r"^data/(?P<path>.+)$", views.data_file, name="dashboard-data"),
]
