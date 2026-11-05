from django.apps import AppConfig


class ApiCallsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Package, app label and heading all say the same thing: this section
    # refreshes data over the sources' own HTTPS APIs. It was called `mcp` until
    # 2026-09-24, after the caveat that §15 of the design spec had carried from
    # the start - nothing here speaks the Model Context Protocol - won. The table
    # (`api_pull_job`) and the cache (`api_cache/`) were renamed with it.
    #
    # `label` is left to default off `name`, so /admin/api_calls/ follows the
    # package. Setting it by hand is what makes django_migrations.app and
    # django_content_type.app_label disagree with the tree; MAINTENANCE.md §6
    # has the two statements that repair that, and why no migration can.
    name = "api_calls"
    verbose_name = "Data Refresh via API"
