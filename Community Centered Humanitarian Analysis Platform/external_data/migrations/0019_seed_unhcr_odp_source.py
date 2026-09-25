"""The source_sync row for UNHCR's ODP situations CSV.

iso3 is NULL on purpose: this row is one file covering every country of asylum,
not a per-country pull, so there is no single country it belongs to. The admin
page renders that as a blank Country cell, which is the truth.
"""
from django.db import migrations

NOTE = ("UNHCR Operational Data Portal: Sudanese refugees and asylum-seekers by "
        "COUNTRY OF ASYLUM, sub-monthly. The other end of the movement IOM DTM "
        "counts arriving back in Sudan - DTM publishes one undifferentiated "
        "'returned from outside Sudan' column and never names a country, so this "
        "is the national-level context for it and is never joined to a Sudanese "
        "locality. Refugees and Asylum-Seekers are COLLAPSED, not summed: UNHCR "
        "publishes both labels on a reclassification date for the same people.")


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.update_or_create(
        source="unhcr-odp", dataset="situations", iso3=None, variant="",
        defaults={"tool": "package_show + csv", "notes": NOTE},
    )


def unseed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.filter(source="unhcr-odp", dataset="situations").delete()


class Migration(migrations.Migration):
    dependencies = [("external_data", "0018_seed_dtm_source")]
    operations = [migrations.RunPython(seed, unseed)]
