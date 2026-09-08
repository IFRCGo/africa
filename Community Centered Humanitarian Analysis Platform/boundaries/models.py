"""The boundary library - the map itself, held in the database.

Until now the dashboard drew borrowed geometry: state outlines downloaded from
the geoBoundaries API and a few files copied out of another IFRC dashboard.
Nobody in this office chose those boundaries and nobody here could vouch for
them. These tables replace that with the office's own authoritative sources -
the OCHA Common Operational Datasets, which carry p-codes, validity dates and
alternate-language names.

Three tables:

    BoundarySource   one row per file we read, so every polygon can name where
                     it came from and the day that file was valid
      |- AdminArea     the polygons themselves: ADM0 down to ADM4, plus the
      |                IFRC Areas of Interest
      |- MapFeature    the physical layers beside them - rivers, lakes,
                       capitals, roads, camps

WHY THE GEOMETRY IS NOT DECLARED HERE
Every column below is an ordinary Django field except the two that hold shapes.
Those are real PostGIS geometry columns, added by migration 0001 with raw SQL
and read and written the same way. Declaring them as Django fields would mean
GeoDjango, and GeoDjango means installing GDAL into this image for no
capability this project needs. Django is perfectly happy managing a table that
has a column it does not know about: it only ever names the columns it does.

The consequence worth knowing: AdminArea.objects.all() gives you every
attribute and no shape. Anything that needs the shape asks for it in SQL - see
boundaries/geo.py and boundaries/views.py.
"""
from django.db import models


class BoundarySource(models.Model):
    """One file we loaded, and everything needed to judge how much to trust it."""

    path = models.TextField(unique=True, help_text="Path of the file, as it was read")
    publisher = models.TextField(
        null=True, blank=True, help_text="OCHA ITOS / IMWG-NBS / SIGCAF-REACH / GADM / IFRC"
    )
    source_label = models.TextField(
        null=True, blank=True, help_text="Short name shown in the layer catalogue"
    )
    schema = models.TextField(
        null=True, blank=True,
        help_text="Which attribute adapter read it: itos_lower / ocha_upper / caf_camel / gadm",
    )
    encoding = models.TextField(
        null=True, blank=True, help_text="Character set the .dbf was read with"
    )
    # A boundary file is a snapshot of a country's own division of itself, and
    # those change. valid_on is the date the publisher stamped on it.
    valid_on = models.DateField(null=True, blank=True)
    version = models.TextField(null=True, blank=True)
    licence = models.TextField(null=True, blank=True)
    feature_count = models.IntegerField(null=True, blank=True)
    sha1 = models.CharField(max_length=40, null=True, blank=True)
    ingested_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boundary_sources"
        ordering = ["path"]

    def __str__(self):
        return f"{self.source_label or self.path} ({self.feature_count} features)"


class AdminArea(models.Model):
    """One polygon: a country, a state, a district, or an IFRC area of interest.

    THE LEVEL IS THE POINT. Every row says which administrative level it is, so
    "give me Ethiopia's zones" is a question the database can answer. That is
    what makes this a library rather than a pile of files.
    """

    KIND_ADMIN = "admin"
    KIND_AOI = "aoi"

    source = models.ForeignKey(
        BoundarySource, on_delete=models.CASCADE, related_name="areas"
    )
    kind = models.TextField(
        default=KIND_ADMIN, db_index=True,
        help_text="admin = a real administrative unit; aoi = an IFRC area of interest",
    )
    # NEVER NULL, and that is load-bearing. The text matcher refuses to place a
    # sentence about one country on a polygon in another, and it can only do
    # that if every polygon knows its country. The 14 Areas of Interest used to
    # have no country, which is exactly how Sudanese reporting ended up
    # highlighting Amhara. See boundaries/README.md.
    iso3 = models.CharField(max_length=3, db_index=True)
    country_name = models.TextField()

    level = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="0 = country, 1 = state/region, 2 = district ... null for an AOI",
    )
    # The identity of a place in humanitarian data. Two agencies spell "Aj
    # Jazirah" three ways between them but agree on SD03.
    pcode = models.TextField(db_index=True)
    name = models.TextField(db_index=True)
    ref_name = models.TextField(null=True, blank=True, help_text="Publisher's own spelling")
    # Arabic and French names, straight from the source's adm*_name1..3 columns.
    # These are free aliases: a report writing the Arabic form still matches.
    name_alt = models.JSONField(default=list, blank=True)

    parent_pcode = models.TextField(null=True, blank=True, db_index=True)
    name_path = models.TextField(
        null=True, blank=True, help_text="Sudan > North Darfur > El Fasher"
    )
    parent_method = models.TextField(
        null=True, blank=True,
        help_text="How the parent was found: 'attribute' from the file, 'spatial' by containment",
    )

    valid_on = models.DateField(null=True, blank=True)
    version = models.TextField(null=True, blank=True)
    area_sqkm = models.FloatField(null=True, blank=True)

    # A point guaranteed to be INSIDE the polygon (not the centroid, which for a
    # crescent-shaped district can fall outside it). Where the symbols go.
    center_lat = models.FloatField(null=True, blank=True)
    center_lon = models.FloatField(null=True, blank=True)
    bbox_w = models.FloatField(null=True, blank=True)
    bbox_s = models.FloatField(null=True, blank=True)
    bbox_e = models.FloatField(null=True, blank=True)
    bbox_n = models.FloatField(null=True, blank=True)

    # geom      geometry(MultiPolygon, 4326)  full resolution - added in migration 0001
    # geom_web  geometry(MultiPolygon, 4326)  simplified for the browser

    class Meta:
        db_table = "admin_areas"
        ordering = ["iso3", "level", "name"]
        constraints = [
            # nulls_distinct=False matters. level is null for every AOI, and
            # under PostgreSQL's default rule two nulls never collide - so
            # duplicate AOIs would slip in unnoticed. This treats them as equal.
            models.UniqueConstraint(
                fields=["source", "kind", "level", "pcode"],
                name="uniq_area_identity",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["iso3", "level"], name="idx_area_country_level"),
            models.Index(fields=["pcode"], name="idx_area_pcode"),
        ]

    def __str__(self):
        return f"{self.pcode} {self.name} (ADM{self.level}, {self.iso3})"


class MapFeature(models.Model):
    """Everything on the map that is not an administrative boundary.

    Rivers and lakes for the water layer, capitals for labels, and the extra
    operational layers the office holds - roads, health districts, camps. They
    share one table because the dashboard treats them the same way: ask for a
    named layer, draw what comes back.
    """

    source = models.ForeignKey(
        BoundarySource, on_delete=models.CASCADE, related_name="features"
    )
    layer = models.TextField(db_index=True, help_text="rivers / lakes / capitals / roads ...")
    name = models.TextField(null=True, blank=True, db_index=True)
    kind = models.TextField(null=True, blank=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    # Whatever else the source carried, kept rather than thrown away: a layer is
    # far more useful later if its own attributes came with it.
    props = models.JSONField(default=dict, blank=True)

    # geom / geom_web  geometry(Geometry, 4326) - mixed types, added in migration 0001

    class Meta:
        db_table = "map_features"
        ordering = ["layer", "name"]
        indexes = [models.Index(fields=["layer", "name"], name="idx_feature_layer")]

    def __str__(self):
        return f"{self.layer}: {self.name or '(unnamed)'}"
