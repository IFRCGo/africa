"""Addresses for the read-only JSON API. Mounted under /api/ by config/urls.py."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="api-index"),
    path("meta/", views.meta, name="api-meta"),
    path("documents/", views.documents, name="api-documents"),
    path("events/", views.events, name="api-events"),
    path("flows/", views.flows, name="api-flows"),
    path("headline/", views.headline, name="api-headline"),
    path("figures/", views.figures, name="api-figures"),
    path("tags/", views.tags, name="api-tags"),
]
