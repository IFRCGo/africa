"""Addresses for the updater, mounted under /updater/ by config/urls.py."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="updater"),
    # The page calls these three in the background.
    path("api/status", views.status, name="updater-status"),
    path("api/external", views.external, name="updater-external"),
    path("api/update", views.update, name="updater-update"),
    path("api/rebuild-external", views.rebuild_external, name="updater-rebuild-external"),
]
