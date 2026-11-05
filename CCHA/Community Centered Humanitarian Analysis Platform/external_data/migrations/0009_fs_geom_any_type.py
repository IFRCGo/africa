"""Widen food_security's geometry columns from MultiPolygon to Geometry.

IPC DOES NOT PUBLISH ONLY POLYGONS. Camps and urban areas come back as Points -
seven of them in the February 2026 Sudan analysis alone, including Zamzam IDP Camp,
where famine was declared. A MultiPolygon column cannot hold a Point, so those
areas were being dropped: 70 of them across Sudan and South Sudan, silently,
because the loader extracted the polygonal part of each shape and a Point has none.

The boundary library already had this problem and solved it the same way -
map_features is typed `geometry(Geometry, 4326)` precisely because it mixes rivers,
lakes and capitals. Food-security areas mix polygons and points for the same
reason: an analysis unit is sometimes a district and sometimes a camp.

Widening a column keeps every row that is already in it, so this is not
destructive; the points still have to be re-loaded, since they never made it in.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("external_data", "0008_hsp")]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE food_security
                ALTER COLUMN geom     TYPE geometry(Geometry, 4326),
                ALTER COLUMN geom_web TYPE geometry(Geometry, 4326);
            """,
            reverse_sql="""
            ALTER TABLE food_security
                ALTER COLUMN geom     TYPE geometry(MultiPolygon, 4326)
                    USING ST_Multi(ST_CollectionExtract(geom, 3)),
                ALTER COLUMN geom_web TYPE geometry(MultiPolygon, 4326)
                    USING ST_Multi(ST_CollectionExtract(geom_web, 3));
            """,
        ),
    ]
