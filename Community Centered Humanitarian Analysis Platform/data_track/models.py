"""The database design - one Python class per PostgreSQL table.

Django calls these classes "models". Each class below becomes a real table,
each attribute becomes a column, and `python manage.py migrate` creates them.

The story this database tells:

    Document          one row per UNHCR PDF report we have read
      |- DocumentText   the raw text of every page of that PDF (the archive)
      |- PopulationFigure  numbers found in it (arrivals, IDPs, returns...)
      |- MovementFlow      corridor movements built from those numbers
      |- NarrativeTag      themes mentioned in it (hazards, needs, coping...)
      |- Event             milestones and incidents on the timeline
    Location          the gazetteer: place names with coordinates

Keeping the full page text means the analysis stays reproducible even if the
original PDFs are later deleted - that is the whole point of the archive.
"""
from django.db import models


class Document(models.Model):
    """One source PDF: where it came from, what it is about, and when."""

    # file_name is what a human sees; rel_path is unique so we never ingest twice.
    file_name = models.TextField()
    rel_path = models.TextField(unique=True, help_text="Path relative to the SUDAN Ops folder")
    source_collection = models.TextField(
        null=True, blank=True, help_text="'regional' or 'sudan_only'"
    )
    year_folder = models.IntegerField(null=True, blank=True)
    family = models.TextField(
        null=True, blank=True, help_text="Report series, e.g. weekly_mapping, chad_core"
    )
    country_focus = models.TextField(null=True, blank=True)
    report_date = models.DateField(null=True, blank=True, db_index=True)
    date_source = models.TextField(
        null=True, blank=True, help_text="How we found the date: filename / text / mtime"
    )
    pages = models.IntegerField(null=True, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    # sha1 is a fingerprint of the file contents, used to spot changed documents.
    sha1 = models.CharField(max_length=40, null=True, blank=True)
    extracted_at = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "documents"
        ordering = ["report_date"]

    def __str__(self):
        return f"{self.file_name} ({self.report_date})"


class DocumentText(models.Model):
    """The raw text of a single page of a single PDF."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="texts")
    page = models.IntegerField()
    text = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "document_text"
        # The old SQLite table used (document_id, page) as its primary key.
        # PostgreSQL/Django prefer a plain id column, so we keep the pair unique instead.
        constraints = [
            models.UniqueConstraint(fields=["document", "page"], name="uniq_document_page")
        ]
        ordering = ["document_id", "page"]

    def __str__(self):
        return f"doc {self.document_id} page {self.page}"


class PopulationFigure(models.Model):
    """One number extracted from a report, with proof of where it came from.

    Every figure keeps `method`, `confidence` and `snippet`, so any number shown
    on the dashboard can be traced back to the sentence that produced it.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="figures", null=True, blank=True
    )
    report_date = models.DateField(null=True, blank=True, db_index=True)
    country = models.TextField(null=True, blank=True, help_text="Where the population is")
    location = models.TextField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    metric = models.TextField(
        null=True, blank=True,
        help_text="cumulative_arrivals / idps / total_displaced / returnees / ...",
    )
    population_group = models.TextField(
        null=True, blank=True, help_text="sudanese_refugees / refugee_returnees / idps / mixed"
    )
    value = models.BigIntegerField(null=True, blank=True)
    method = models.TextField(null=True, blank=True, help_text="Which parser produced it")
    confidence = models.TextField(null=True, blank=True, help_text="high / medium / low")
    snippet = models.TextField(null=True, blank=True, help_text="The text it was read from")

    class Meta:
        db_table = "population_figures"
        indexes = [
            models.Index(fields=["report_date"], name="idx_figures_date"),
            models.Index(fields=["metric", "country"], name="idx_figures_metric"),
        ]

    def __str__(self):
        return f"{self.metric} {self.country} {self.value:,}" if self.value else str(self.metric)


class MovementFlow(models.Model):
    """A movement corridor at a point in time - what draws the arrows on the map."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="flows", null=True, blank=True
    )
    report_date = models.DateField(null=True, blank=True)
    corridor = models.TextField(null=True, blank=True, help_text="e.g. sudan-chad")
    origin = models.TextField(null=True, blank=True)
    origin_lat = models.FloatField(null=True, blank=True)
    origin_lon = models.FloatField(null=True, blank=True)
    destination = models.TextField(null=True, blank=True)
    dest_lat = models.FloatField(null=True, blank=True)
    dest_lon = models.FloatField(null=True, blank=True)
    flow_type = models.TextField(
        null=True, blank=True, help_text="cross_border / internal / return"
    )
    value = models.BigIntegerField(
        null=True, blank=True, help_text="Cumulative people as of report_date"
    )
    snippet = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "movement_flows"
        indexes = [models.Index(fields=["report_date", "corridor"], name="idx_flows_date")]

    def __str__(self):
        return f"{self.corridor} {self.report_date}"


class Event(models.Model):
    """A dated milestone or incident shown on the timeline."""

    event_date = models.DateField(db_index=True)
    title = models.TextField()
    description = models.TextField(null=True, blank=True)
    category = models.TextField(
        null=True, blank=True,
        help_text="conflict / displacement / access / disease / flood / famine / policy / return",
    )
    location = models.TextField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    severity = models.IntegerField(
        null=True, blank=True, help_text="1-5, where 5 is a defining moment of the crisis"
    )
    source = models.TextField(
        null=True, blank=True, help_text="'curated' (hand-checked) or 'extracted' (from a report)"
    )
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, related_name="events", null=True, blank=True
    )

    class Meta:
        db_table = "events"
        ordering = ["event_date"]

    def __str__(self):
        return f"{self.event_date} {self.title[:60]}"


class NarrativeTag(models.Model):
    """One mention of a theme in a report - this is what the dashboard toggles show."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="tags", null=True, blank=True
    )
    report_date = models.DateField(null=True, blank=True)
    dimension = models.TextField(
        null=True, blank=True,
        help_text="hazard / vulnerability / coping / need / movement_pattern",
    )
    tag = models.TextField(null=True, blank=True, help_text="Normalised tag, e.g. flooding, food")
    country = models.TextField(null=True, blank=True)
    # WHERE INSIDE THE COUNTRY, when the report says. About a third of tagged
    # sentences name a state, a locality or a town; those are the ones the map
    # can highlight. The rest stay country-level and are left null.
    area_id = models.TextField(
        null=True, blank=True,
        help_text="Polygon this belongs to, e.g. 'SDN:Northern'. Matches "
                  "boundaries/admin1.geojson properties.id. Null when the "
                  "report named no place.",
    )
    area_name = models.TextField(
        null=True, blank=True, help_text="The place as the report wrote it, e.g. 'El Bauga'",
    )
    # How far down the matcher got. A country's states are level 1, its
    # districts level 2, and so on. Worth recording because it says how precise
    # a highlight is: "somewhere in North Darfur" and "in El Fasher locality"
    # are different findings, and only this column tells them apart afterwards.
    area_level = models.IntegerField(
        null=True, blank=True,
        help_text="Admin level of area_id: 0 country, 1 state, 2 district, ...",
    )
    snippet = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "narrative_tags"
        indexes = [
            models.Index(fields=["dimension", "tag", "report_date"], name="idx_tags_dim"),
        ]

    def __str__(self):
        return f"{self.dimension}:{self.tag}"


class Location(models.Model):
    """The gazetteer: place names, their coordinates and their alternate spellings."""

    # The place name is the primary key, exactly as in the original design.
    name = models.TextField(primary_key=True)
    country = models.TextField(null=True, blank=True)
    admin1 = models.TextField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    kind = models.TextField(
        null=True, blank=True,
        help_text="capital / town / camp / border_crossing / state / country_anchor",
    )
    aliases = models.TextField(null=True, blank=True, help_text="Alternate spellings, pipe-separated")

    class Meta:
        db_table = "locations"
        ordering = ["name"]

    def __str__(self):
        return self.name
