"""App registration for the one-click updater."""
from django.apps import AppConfig


class UpdaterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "updater"
    verbose_name = "Updater (one-click pipeline runner)"
