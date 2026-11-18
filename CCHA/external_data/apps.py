"""External humanitarian data: what the MCP servers and the Excel workbooks supply.

Three apps now divide this project's data. `data_track` holds what the UNHCR PDFs
said. `boundaries` holds the geography those statements are placed on. This one
holds what the humanitarian data providers publish directly - IPC phases, FEWS NET
seasons, IOM-DTM displacement, UNHCR refugee stocks - together with the bookkeeping
that says how fresh each of them is.

The tables are named for their subject rather than their source, because a seasonal
calendar is a seasonal calendar whether FEWS NET or ACAPS published it. Which
provider a row came from is a column, not a table name.
"""
from django.apps import AppConfig


class ExternalDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "external_data"
