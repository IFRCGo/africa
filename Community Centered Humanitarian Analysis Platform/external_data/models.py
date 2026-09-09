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


class SeasonalCalendar(models.Model):
    """When the lean season bites, when the harvest comes in - per country.

    NO COLOUR COLUMN, deliberately. The dashboard's calendar strip needs one, but
    FEWS NET does not publish colours, so a colour column would be null for every
    real row. Colour is derived at build time from `season_type`, which has the
    happy side effect that a lean season is the same colour in every country.
    """

    iso3 = models.CharField(max_length=3, db_index=True)
    country_name = models.TextField()
    admin_pcode = models.TextField(
        null=True, blank=True,
        help_text="Null for a national calendar. ACAPS publishes at admin-1.",
    )
    source = models.TextField(help_text="fewsnet / acaps / curated")
    source_ref = models.TextField(
        null=True, blank=True, help_text="FEWS NET fnid, or the ACAPS record id"
    )
    label = models.TextField(help_text="'Lean', 'Main harvest', 'Post-harvest'")
    season_type = models.TextField(
        null=True, blank=True, help_text="Lean / Harvest / Dry / Rainy"
    )
    purpose = models.TextField(
        null=True, blank=True, help_text="NutritionIndicator / CropProductionIndicator"
    )
    # A season that runs November to February has end_month < start_month. That is
    # the source telling the truth about the calendar, not an error to correct.
    start_month = models.IntegerField()
    end_month = models.IntegerField()
    alignment = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    aliases = models.JSONField(
        default=list, blank=True, help_text="Multilingual synonyms - 'soudure' for lean"
    )
    display_order = models.IntegerField(default=0)

    class Meta:
        db_table = "seasonal_calendar"
        ordering = ["iso3", "purpose", "display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "iso3", "admin_pcode", "purpose", "label"],
                name="uniq_seasonal_band",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        return f"{self.iso3} {self.label} ({self.start_month}-{self.end_month})"


class FoodSecurityArea(models.Model):
    """One IPC or Cadre Harmonise analysis unit, at one phase, in one period.

    IPC ANALYSIS UNITS ARE NOT ADMIN UNITS. IPC redraws them each round, which is
    why the existing ipc_areas_fs.geojson holds a complete snapshot per period
    rather than a series per area. The geometry is stored as IPC published it, and
    `admin_pcode` is a convenience join filled in where a polygon confidently
    matches one in admin_areas, left null otherwise. Nothing depends on it.

    `source` separates products that must never be conflated: 'ipc' is an official
    IPC analysis, 'ch' a Cadre Harmonise one (the same five-phase scale, used across
    the Sahel - Chad's analyses are these), and 'fewsnet' is FEWS NET's own
    IPC-compatible assessment, which is a different organisation's judgement about
    the same places.
    """

    source = models.TextField(db_index=True, help_text="ipc / ch / fewsnet")
    analysis_id = models.TextField(db_index=True, help_text="IPC's anl_id")
    analysis_title = models.TextField(null=True, blank=True)
    condition = models.CharField(
        max_length=1, null=True, blank=True, help_text="A acute, C chronic"
    )
    iso3 = models.CharField(max_length=3, db_index=True)
    period_date = models.DateField(db_index=True, help_text="First day of the period described")
    period_type = models.TextField(
        default="current", help_text="current / projection / second_projection"
    )
    area_id = models.TextField(help_text="IPC's aar_id")
    area_title = models.TextField(null=True, blank=True)
    admin_pcode = models.TextField(null=True, blank=True)

    phase = models.IntegerField(null=True, blank=True, help_text="Overall IPC phase 1-5")
    phase3_pct = models.FloatField(null=True, blank=True)
    phase4_pct = models.FloatField(null=True, blank=True)
    phase5_pct = models.FloatField(null=True, blank=True)
    phase3plus_pct = models.FloatField(null=True, blank=True, help_text="Phases 3+4+5")
    phase5_population = models.BigIntegerField(null=True, blank=True)
    total_population = models.BigIntegerField(null=True, blank=True)
    # IPC's own phase colour, kept so the map never invents one.
    colour = models.TextField(null=True, blank=True)

    # geom / geom_web  geometry(MultiPolygon, 4326) - added in the raw SQL migration

    class Meta:
        db_table = "food_security"
        ordering = ["iso3", "period_date", "area_title"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "analysis_id", "period_type", "area_id"],
                name="uniq_food_security_area",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["iso3", "period_date"], name="idx_fs_country_period"),
        ]

    @property
    def famine(self):
        """Phase 5 present - what the dashboard's 'fam' flag has always meant."""
        return bool(
            (self.phase5_population or 0) > 0
            or (self.phase is not None and self.phase >= 5)
        )

    def __str__(self):
        return f"{self.iso3} {self.area_title} phase {self.phase} ({self.period_date})"


class MovementPattern(models.Model):
    """Displacement figures as the agencies themselves publish them.

    THIS IS NOT data_track.PopulationFigure, and the distinction is deliberate.
    That table holds numbers read out of UNHCR PDFs, each with the sentence that
    produced it. This one holds the same KINDS of quantity from the agencies' own
    APIs and from the office's Excel workbooks. They overlap and they disagree,
    because a situation report and an IOM-DTM round count different things on
    different dates.

    They stay apart. An analyst who wants both writes a UNION and chooses what that
    means. One merged table would produce plausible, wrong totals that nobody could
    trace back - the exact failure this project's evidence trail exists to prevent.
    """

    date = models.DateField(db_index=True)
    iso3 = models.CharField(max_length=3, db_index=True)
    admin_pcode = models.TextField(
        null=True, blank=True, help_text="Null for a national total. Joins admin_areas.pcode."
    )
    admin_level = models.IntegerField(null=True, blank=True)
    place_name = models.TextField(null=True, blank=True)

    metric = models.TextField(
        db_index=True, help_text="idps / refugees / returnees / asylum_seekers"
    )
    population_group = models.TextField(null=True, blank=True)
    value = models.BigIntegerField()
    unit = models.TextField(default="individuals", help_text="individuals / households")

    source = models.TextField(help_text="hdx / unhcr / excel")
    source_dataset = models.TextField(
        null=True, blank=True, help_text="iom-dtm / get_refugees / the workbook name"
    )
    # DTM reports a period, not an instant. Keeping both ends means a later reader
    # can tell a fortnight's round from a single day's count.
    reference_period_start = models.DateField(null=True, blank=True)
    reference_period_end = models.DateField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "movement_patterns"
        ordering = ["iso3", "metric", "date"]
        constraints = [
            # place_name is in the key, and that is not decoration. Sudan's admin1
            # IDP rows carry no p-code, so without it every state sharing a date
            # collided and all but one were silently overwritten - 234 rows
            # collapsing to 6. An observation is identified by WHERE it is, and
            # when a p-code is absent the name is the only "where" there is.
            models.UniqueConstraint(
                fields=["source", "metric", "iso3", "admin_pcode", "place_name",
                        "date", "population_group"],
                name="uniq_movement_observation",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["metric", "iso3", "date"], name="idx_movement_series"),
        ]

    def __str__(self):
        return f"{self.date} {self.iso3} {self.metric} {self.value:,}"


class BorderCrossing(models.Model):
    """The crossings people actually move through, tagged to movement corridors.

    Curated, and permanently so: no humanitarian API publishes "the crossings that
    matter for this operation", because that judgement is the operation's own. The
    coordinates come from UNHCR and OCHA operational geography and the corridor tags
    match the ids in flows.json, which is what lets the map light a crossing only
    when population actually moved along it.
    """

    name = models.TextField(unique=True)
    country = models.TextField(help_text="The country on the far side of the crossing")
    iso3 = models.CharField(max_length=3, db_index=True)
    lon = models.FloatField()
    lat = models.FloatField()
    corridor = models.TextField(
        null=True, blank=True, help_text="Outbound corridor id, e.g. sudan-chad"
    )
    # Null, not empty: several crossings have no observed return movement at all,
    # and that absence is a finding rather than a missing value.
    return_corridor = models.TextField(null=True, blank=True)
    source = models.TextField(default="curated")

    class Meta:
        db_table = "border_crossings"
        ordering = ["country", "name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


class HumanitarianServicePoint(models.Model):
    """Which service a National Society offers, in which district, as reported.

    WHAT THIS TABLE IS NOT. Despite the name the form carries, the Kobo export
    holds no service-point coordinates and no per-site rows: it is six submissions,
    one per country, recording which of eleven services the National Society offers
    and which districts it offers them in. A row here therefore means "this service
    is offered somewhere in this district", NOT "there is a service point at this
    spot". The lat/lon below is the district's own point-on-surface, taken from the
    boundary library, and is a label position rather than an address.

    That is the finest truthful placement the source supports, and saying so here
    is cheaper than someone later reading these dots as building locations.

    South Sudan is the one country that answered "no" to "same services at every
    HSP", so it carries three named locations with their own service lists; those
    rows have scope='named-location'. The other five are country-wide.

    DATE_REPORTED IS THE EXPORT DATE, and there is no better one. The export
    carries no submission timestamp at all - Kobo's _submission__submission_time
    column is present but empty for every row - so the date comes from the export
    filename. It still does the job it is here for: load a later export and its
    rows sit beside these under a new date, so what changed is a query rather than
    a memory.
    """

    date_reported = models.DateField(
        db_index=True, help_text="Export date. See the note above: no submission date exists."
    )
    country = models.TextField()
    iso3 = models.CharField(max_length=3, db_index=True)

    service = models.TextField(db_index=True, help_text="One of the form's eleven services")
    scope = models.TextField(
        default="country-wide", help_text="country-wide / named-location"
    )

    # Where. admin_pcode joins admin_areas on (iso3, level, pcode).
    location_name = models.TextField(help_text="The district as the form labelled it")
    admin_pcode = models.TextField(null=True, blank=True)
    admin_level = models.IntegerField(null=True, blank=True)
    match_method = models.TextField(
        default="unmatched", help_text="pcode / name / unmatched - how the district was placed"
    )
    # Copied from the matched polygon so a map can be drawn from this table alone,
    # with no join and no second source.
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    # Submission-level context, repeated on each row so one query answers everything.
    same_services_everywhere = models.BooleanField(null=True, blank=True)
    hsp_count = models.IntegerField(
        null=True, blank=True, help_text="As reported. NOT max_hsps, which is a form roster size."
    )
    kobo_uuid = models.TextField(null=True, blank=True)
    source_file = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "humanitarian_service_points"
        ordering = ["date_reported", "iso3", "location_name", "service"]
        constraints = [
            # date_reported is IN the key, which is the point: a later export adds
            # rows beside these rather than overwriting them, so the table keeps a
            # history and "did this change?" is answerable.
            models.UniqueConstraint(
                fields=["date_reported", "iso3", "service", "location_name"],
                name="uniq_hsp_service_place_date",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["iso3", "service"], name="idx_hsp_country_service"),
        ]

    def __str__(self):
        return f"{self.service} - {self.location_name} ({self.iso3}, {self.date_reported})"
