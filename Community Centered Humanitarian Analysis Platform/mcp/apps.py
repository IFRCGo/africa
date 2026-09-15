from django.apps import AppConfig


class McpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp"
    # The sidebar heading. The office calls these sources "the MCPs", and this
    # section is where they are pulled from, so it is named for them - with the
    # caveat that the pulls themselves are plain HTTPS. See §15 of the spec.
    verbose_name = "Model Context Protocol (MCP)"
