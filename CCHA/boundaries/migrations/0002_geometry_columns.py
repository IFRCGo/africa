"""The geometry columns, added with raw SQL because Django cannot describe them.

Django has no field type for a PostGIS geometry unless you install GeoDjango,
and GeoDjango means putting GDAL into the web image. This project does not need
Django to understand the shapes - only to store rows beside them - so the two
geometry columns are created here, in SQL, and everything that reads or writes a
shape does so in SQL too (see boundaries/geo.py).

Each table gets two:

    geom      the polygon exactly as the publisher drew it. This is what QGIS
              opens and what any spatial question is answered from.
    geom_web  the same polygon with detail removed, for sending to a browser.

Both are indexed with GiST, which is what makes "which district contains this
point?" fast enough to run over ten thousand polygons.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("boundaries", "0001_initial")]

    operations = [
        # Idempotent: the extension is already present on the running database,
        # but a fresh install needs this or the ALTER TABLEs below fail.
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS postgis;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # MultiPolygon rather than Polygon: several of these areas are genuinely
        # more than one piece of land - islands, exclaves, the Nile's braids -
        # and a column typed Polygon would reject them.
        migrations.RunSQL(
            """
            ALTER TABLE admin_areas
                ADD COLUMN IF NOT EXISTS geom     geometry(MultiPolygon, 4326),
                ADD COLUMN IF NOT EXISTS geom_web geometry(MultiPolygon, 4326);
            CREATE INDEX IF NOT EXISTS idx_admin_areas_geom
                ON admin_areas USING GIST (geom);
            CREATE INDEX IF NOT EXISTS idx_admin_areas_geom_web
                ON admin_areas USING GIST (geom_web);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_admin_areas_geom_web;
            DROP INDEX IF EXISTS idx_admin_areas_geom;
            ALTER TABLE admin_areas
                DROP COLUMN IF EXISTS geom_web,
                DROP COLUMN IF EXISTS geom;
            """,
        ),
        # Untyped Geometry here, because this table deliberately mixes them:
        # rivers are lines, lakes are polygons, capitals are points.
        migrations.RunSQL(
            """
            ALTER TABLE map_features
                ADD COLUMN IF NOT EXISTS geom     geometry(Geometry, 4326),
                ADD COLUMN IF NOT EXISTS geom_web geometry(Geometry, 4326);
            CREATE INDEX IF NOT EXISTS idx_map_features_geom
                ON map_features USING GIST (geom);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_map_features_geom;
            ALTER TABLE map_features
                DROP COLUMN IF EXISTS geom_web,
                DROP COLUMN IF EXISTS geom;
            """,
        ),
    ]
