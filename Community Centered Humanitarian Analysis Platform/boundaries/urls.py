"""Addresses for the boundary library, mounted at /api/boundaries/.

    layers/     the catalogue - what maps do we hold, from whom, valid when
    layer/      one whole administrative level as GeoJSON
    features/   exactly these p-codes, which is what the map highlighting asks

See boundaries/views.py for why the third one is the interesting one.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("layers/", views.layers, name="boundary-layers"),
    path("layer/", views.layer, name="boundary-layer"),
    path("features/", views.features, name="boundary-features"),
]
