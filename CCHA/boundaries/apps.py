"""Django's registration card for the boundary library app."""
from django.apps import AppConfig


class BoundariesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "boundaries"
    verbose_name = "Boundary library"
