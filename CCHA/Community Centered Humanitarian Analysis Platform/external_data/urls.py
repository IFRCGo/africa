"""Addresses for the external data API, mounted at /api/ by config/urls.py.

Listed BEFORE data_track's "api/" include there, for the same reason
api/boundaries/ already is: Django takes the first pattern that matches, and
data_track's include would otherwise swallow these paths.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("external/", views.index, name="external-index"),
    path("seasonal/", views.seasonal, name="external-seasonal"),
    path("food-security/", views.food_security, name="external-food-security"),
    path("movement/", views.movement, name="external-movement"),
    path("community-insights/", views.community_insights, name="external-insights"),
    path("hsps/", views.hsps, name="external-hsps"),
    path("crossings/", views.crossings, name="external-crossings"),
    path("sync/", views.sync, name="external-sync"),
]
