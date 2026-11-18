"""App registration for the ETL pipeline (the manage.py commands live here)."""
from django.apps import AppConfig


class DataPipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "data_pipeline"
    verbose_name = "Data pipeline (PDF -> database -> dashboard files)"
