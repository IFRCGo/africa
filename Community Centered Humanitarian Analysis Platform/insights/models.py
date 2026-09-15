"""What a community said, and everything derived from it.

    Insight         one statement, verbatim and whole - THE record
      |- InsightCoding   the hazards, needs and vulnerabilities read out of it
    InsightFolder   a registered folder of source documents
    ExtractionJob   one run: what it read, what it proposed, what it rejected

WHY THIS IS NOT data_track.NarrativeTag. That table records "a UNHCR report
mentioned flooding" - a keyword match on an analyst's prose, rebuilt from scratch
by s03_parse on every pipeline run. This one records "a community in Afar said
this", kept because a person reviewed it and published it. Nothing in
data_pipeline writes here, and nothing here is ever truncated.

The statement and its interpretation are deliberately two tables. Flattening the
codings into one tagged row per theme would lose the statement, which is the only
part no model can reconstruct.
"""
from pathlib import Path

from django.conf import settings
from django.db import models

VOICE_TYPES = [("community", "Community voice"), ("secondary_analysis", "Secondary analysis")]
CHANNELS = [("document_ai", "Document (AI)"), ("manual", "Typed by hand"), ("primary", "Primary collection")]
STATUSES = [("pending", "Pending review"), ("published", "Published"), ("rejected", "Rejected")]
DIMENSIONS = [("hazard", "Hazard"), ("vulnerability", "Vulnerability"), ("need", "Need"),
              ("coping", "Coping"), ("movement_pattern", "Movement pattern")]


class InsightFolder(models.Model):
    """A folder of source documents, registered once and re-read on demand."""

    label = models.TextField(help_text="e.g. 'IOM DTM Chad round 12'")
    path = models.TextField(unique=True, help_text="Must resolve inside the container")
    default_iso3 = models.CharField(max_length=3, null=True, blank=True)
    recursive = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "insight_folders"
        ordering = ["label"]

    def clean(self):
        """Reject an unreachable path at save time rather than inside a job.

        Admin calls this, so a mistyped path is a field error on the form. The
        `reachable` column in the changelist stays, for a folder that was valid
        when registered and has since moved.
        """
        from django.core.exceptions import ValidationError

        from insights import document_roots

        if self.path and not Path(self.path).is_dir():
            raise ValidationError({"path": (
                f"{self.path} is not a directory inside this container. "
                f"{document_roots.sentence()}"
            )})

    def __str__(self):
        return self.label


class InsightUpload(models.Model):
    """One document uploaded through Admin, rather than found in a folder.

    Files land under MEDIA_ROOT, which is inside the app itself, because the
    folder holding the source documents is mounted read-only: an upload cannot
    be written beside the PDFs it will be read with. Saving one catalogues it
    immediately - see InsightUploadAdmin.save_model - and `document` then points
    at the row it produced.
    """

    file = models.FileField(upload_to="insights/")
    label = models.TextField(null=True, blank=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True)
    report_date = models.DateField(null=True, blank=True)
    document = models.ForeignKey(
        "data_track.Document", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Filled in once the upload has been catalogued",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "insight_uploads"
        ordering = ["-id"]

    def __str__(self):
        if self.label:
            return self.label
        return Path(self.file.name).name if self.file else f"upload {self.id}"


class ExtractionJob(models.Model):
    """One extraction run, and what it cost in rejected quotes.

    insights_rejected_unverifiable is the number worth watching: it is a direct
    per-run measurement of how much a given model invents, and it is why pointing
    an unknown local model at this is safe to try.
    """

    folder = models.ForeignKey(InsightFolder, on_delete=models.SET_NULL, null=True, blank=True)
    # What this job extracts, and nothing else. Without this link
    # `extract_insights --job N` had nothing to scope itself to but
    # "every document ever catalogued into the insights collection" - a job
    # for one folder would silently re-extract every other folder's documents
    # too. Additive: this table lives in insights and data_track is untouched.
    # A document already catalogued by an earlier job may be attached to a
    # later one too - re-running the SAME job on purpose (e.g. with a better
    # model) re-extracts its documents; the loader's conflict rule (gate 4)
    # already protects any row a reviewer has touched.
    documents = models.ManyToManyField(
        "data_track.Document", blank=True, related_name="extraction_jobs")
    producer = models.TextField(default="external", help_text="external / anthropic / openai_compatible")
    model_used = models.TextField(null=True, blank=True)
    status = models.TextField(
        default="queued",
        help_text=(
            "queued / running / loaded / failed. A job stuck at 'running' because "
            "its process was killed rather than raising (e.g. docker compose restart "
            "web) can be recovered with the 'Reset stuck job to queued' action below."
        ),
    )
    documents_total = models.IntegerField(default=0)
    documents_done = models.IntegerField(default=0)
    insights_proposed = models.IntegerField(default=0)
    insights_rejected_unverifiable = models.IntegerField(default=0)
    insights_skipped_reviewed = models.IntegerField(default=0)
    log = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "insight_jobs"
        ordering = ["-id"]

    def __str__(self):
        return f"job {self.id} ({self.producer}, {self.status})"


class Insight(models.Model):
    """One thing a community said, kept whole."""

    # ---- the record itself
    quote = models.TextField(help_text="Verbatim, in full. Never summarised or trimmed.")
    quote_language = models.CharField(max_length=8, default="en")
    quote_translated = models.TextField(null=True, blank=True)
    # Fingerprint of the normalised quote. Part of the natural key, which is why
    # editing the quote in Admin has to recompute it.
    quote_sha1 = models.CharField(max_length=40)

    voice_type = models.TextField(choices=VOICE_TYPES, default="community")
    channel = models.TextField(choices=CHANNELS, default="document_ai")

    # ---- where it came from
    document = models.ForeignKey(
        "data_track.Document", on_delete=models.CASCADE, related_name="insights",
        null=True, blank=True, help_text="Null for manual and primary-collected statements",
    )
    page = models.IntegerField(null=True, blank=True)
    stated_on = models.DateField(
        db_index=True, help_text="Report date, or collection date. The dashboard timeline rides on this.",
    )

    # ---- where the people are
    iso3 = models.CharField(max_length=3, db_index=True)
    place_name_as_written = models.TextField(null=True, blank=True)
    admin_pcode = models.TextField(null=True, blank=True)
    admin_level = models.IntegerField(null=True, blank=True)
    match_method = models.TextField(default="unmatched", help_text="pcode / name / unmatched")
    # Copied from AdminArea.center_lat/center_lon - a point guaranteed inside the
    # polygon. A LABEL POSITION, not an address. See the popup note in the spec.
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    # ---- optional, and usually absent
    people_affected = models.BigIntegerField(null=True, blank=True)
    severity = models.IntegerField(null=True, blank=True, help_text="1-5, as Event.severity")

    # ---- provenance
    method = models.TextField(default="llm", help_text="llm / manual")
    model_used = models.TextField(null=True, blank=True)
    confidence = models.TextField(null=True, blank=True, help_text="high / medium / low")

    # ---- review
    status = models.TextField(choices=STATUSES, default="pending", db_index=True)
    rejection_reason = models.TextField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    job = models.ForeignKey(ExtractionJob, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="insights")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "insights"
        ordering = ["-stated_on", "id"]
        constraints = [
            # nulls_distinct=False because a manual insight has a null document and
            # a null page. Under PostgreSQL's default rule two NULLs never collide,
            # so every duplicate hand-typed statement would be accepted silently.
            models.UniqueConstraint(
                fields=["document", "page", "quote_sha1"],
                name="uniq_insight_quote", nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["status", "voice_type", "stated_on"], name="idx_insight_publish"),
            models.Index(fields=["iso3", "stated_on"], name="idx_insight_place"),
        ]

    def save(self, *args, **kwargs):
        # The fingerprint is part of the natural key, so it must follow the quote.
        # Editing a quote in Admin is allowed only to repair an OCR artefact; this
        # keeps the key honest when that happens.
        from insights.verify import quote_sha1 as _sha1
        self.quote_sha1 = _sha1(self.quote)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.iso3} {self.stated_on}: {self.quote[:60]}"


class InsightCoding(models.Model):
    """One theme read out of one statement.

    `tag` is constrained to taxonomy.json at load time rather than by a database
    check, because the vocabulary is a JSON file that changes without a migration.
    See insights/taxonomy.py, which is the single place that enforces it.
    """

    insight = models.ForeignKey(Insight, on_delete=models.CASCADE, related_name="codings")
    dimension = models.TextField(choices=DIMENSIONS)
    tag = models.TextField(help_text="A key in taxonomy.json under this dimension, or 'other'")
    tag_raw = models.TextField(
        null=True, blank=True, help_text="What was proposed, when it fell outside the vocabulary")

    class Meta:
        db_table = "insight_codings"
        ordering = ["dimension", "tag"]
        constraints = [
            models.UniqueConstraint(
                fields=["insight", "dimension", "tag"], name="uniq_insight_coding"),
        ]

    def __str__(self):
        return f"{self.dimension}:{self.tag}"
