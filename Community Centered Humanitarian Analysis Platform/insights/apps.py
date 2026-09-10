from django.apps import AppConfig


class InsightsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "insights"
    verbose_name = "Community insights (statements, codings, intake, extraction jobs)"
