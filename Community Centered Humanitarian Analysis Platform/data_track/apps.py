"""App registration. Django reads this to learn the app is called "data_track"."""
from django.apps import AppConfig


class DataTrackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "data_track"
    # What the /admin/ sidebar calls this group of tables. Without it Django
    # would show the folder name, "Data_Track". See data_track/README.md for
    # what each table holds.
    verbose_name = "Data tables (documents, text, figures, flows, tags, events, locations)"
