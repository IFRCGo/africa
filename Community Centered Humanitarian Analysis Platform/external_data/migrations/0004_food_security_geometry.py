"""The two PostGIS columns on food_security, added with raw SQL.

Same reasoning as boundaries/migrations/0002_geometry_columns.py: Django has no
field type for a geometry without GeoDjango, GeoDjango means GDAL in the web image,
and this project only needs Django to store rows beside the shapes.

    geom      the polygon as IPC published it
    geom_web  the same polygon simplified, for sending to a browser

MultiPolygon rather than Polygon: an IPC analysis unit is frequently more than one
piece of land, and a column typed Polygon would reject it.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("external_data", "0003_foodsecurityarea_and_more")]

    operations = [
        # Idempotent: already present on the running database, but a fresh install
        # (and every test database) needs this before the ALTER TABLE below.
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS postgis;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            """
            ALTER TABLE food_security
                ADD COLUMN IF NOT EXISTS geom     geometry(MultiPolygon, 4326),
                ADD COLUMN IF NOT EXISTS geom_web geometry(MultiPolygon, 4326);
            CREATE INDEX IF NOT EXISTS idx_food_security_geom
                ON food_security USING GIST (geom);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_food_security_geom;
            ALTER TABLE food_security
                DROP COLUMN IF EXISTS geom_web,
                DROP COLUMN IF EXISTS geom;
            """,
        ),
    ]
