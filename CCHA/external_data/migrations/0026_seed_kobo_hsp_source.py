"""The source_sync row that makes the HSP Pull now button appear.

0023 said this row needed no seed because load_hsps had already written it. That
was true of one database. A fresh clone starts empty, so it had no row and no
button, and HSPs could not be fetched from the Data sources page at all.

get_or_create, never update: on a database that already has the row, its pull
history, watermark and params are left exactly as they are.
"""
from django.db import migrations

NOTE = ("Humanitarian Service Points from Kobo (HSPs_FORM_ID). District-level, "
        "not point-level: the form holds no coordinates and no per-site rows. "
        "date_reported is the pull date because Kobo sends no edit timestamp.")


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.get_or_create(
        source="kobo", dataset="humanitarian_service_points", iso3=None,
        variant="hsp-mapping",
        defaults={"tool": "kobo list_submissions", "notes": NOTE},
    )


def unseed(apps, schema_editor):
    # Deliberately a no-op: on a database where load_hsps wrote the row, it
    # holds real pull history, and this migration cannot tell the two apart.
    pass


class Migration(migrations.Migration):
    dependencies = [("external_data", "0025_ccha_primary_data_rename")]
    operations = [migrations.RunPython(seed, unseed)]
