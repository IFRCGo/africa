"""The subject tables, and the one table that says how fresh they are.

    SourceSync        one row per thing that can be pulled, and its watermark
    SeasonalCalendar  lean / harvest / dry bands, per country
    FoodSecurityArea  IPC and Cadre Harmonise phases, per area
    MovementPattern   IDP and refugee series, long format
    BorderCrossing    curated crossings, no API behind them

The tables are named for their subject, not their source. A seasonal calendar is a
seasonal calendar whether FEWS NET or ACAPS published it, so which provider a row
came from is a column here rather than a table name.

Geometry is not declared in this file. `FoodSecurityArea` gains two PostGIS columns
in a later migration, added with raw SQL, exactly as `admin_areas` does and for the
same reason: GeoDjango would mean putting GDAL into the web image for no capability
this project needs. Django is perfectly happy managing a table that has a column it
does not know about - it only ever names the columns it does.
"""
from django.db import models


class SourceSync(models.Model):
    """What has already been fetched, so the next pull asks only for the rest.

    IDENTITY EXCLUDES THE CALL'S ARGUMENTS, and that is the point of this table.
    `params` records the last call made, for reproducibility, but it is not part of
    the unique key - `start_date` lives in there, so keying on it would give every
    incremental pull its own row and the watermark would never accumulate.

    `variant` is what legitimately separates two rows for one country: IDPs at
    admin1 and IDPs at admin2 are different things to fetch. Date windows, page
    offsets and result limits are never part of identity.
    """

    source = models.TextField(help_text="fewsnet / ipc / hdx / unhcr / acaps / excel")
    dataset = models.TextField(help_text="seasonal_calendar / food_security / idps / refugees")
    iso3 = models.CharField(
        max_length=3, null=True, blank=True, help_text="Null for a global pull"
    )
    variant = models.TextField(
        default="", blank=True, help_text="Which slice: 'admin2-overview' vs 'admin1'"
    )
    tool = models.TextField(null=True, blank=True, help_text="The MCP tool called")
    params = models.JSONField(
        default=dict, blank=True, help_text="The last call made. NOT part of identity."
    )

    # last_pulled_at moves on every attempt; high_water_date moves only when data
    # genuinely newer than what we held came back. Keeping them apart is what stops
    # a no-op refresh from looking like fresh data.
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    high_water_date = models.DateField(
        null=True, blank=True, help_text="Latest DATA date held - not the pull date"
    )
    known_ids = models.JSONField(
        default=list, blank=True,
        help_text="Identities already held, for sources with no date filter (IPC analysis ids)",
    )
    row_count = models.IntegerField(default=0)
    notes = models.TextField(
        null=True, blank=True,
        help_text="e.g. 'publishes annually, latest 2024' - so a no-op refresh explains itself",
    )

    class Meta:
        db_table = "source_sync"
        ordering = ["source", "dataset", "iso3", "variant"]
        constraints = [
            # nulls_distinct=False because iso3 is null for global pulls, and under
            # PostgreSQL's default rule two nulls never collide - so duplicate
            # global rows would accumulate silently. Same trap admin_areas
            # documents on uniq_area_identity.
            models.UniqueConstraint(
                fields=["source", "dataset", "iso3", "variant"],
                name="uniq_source_sync_identity",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        where = self.iso3 or "global"
        return f"{self.source}/{self.dataset} {where} {self.variant}".strip()
