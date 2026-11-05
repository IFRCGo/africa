"""Remove the second source_sync row the UNHCR ODP loader created for itself.

The fetcher's dataset was `situations` and the loader's was `unhcr_situations`.
Loader.sync_key() keys the watermark on the LOADER's dataset, so the first pull
wrote its watermark - and its known_ids and high_water_date - to a row nobody
was looking at, while the seeded row the Pull now button owns stayed at "never
pulled". Both names are now `situations`; this clears the orphan.

The rows it was tracking are untouched: they live in movement_patterns under
source='unhcr-odp' and are found by source, not by this row. The next pull
rewrites the surviving row's watermark from the data itself.
"""
from django.db import migrations


def drop_orphan(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.filter(source="unhcr-odp", dataset="unhcr_situations").delete()


def restore_orphan(apps, schema_editor):
    """Nothing to restore: the row held no data, only a misfiled watermark."""


class Migration(migrations.Migration):
    dependencies = [("external_data", "0019_seed_unhcr_odp_source")]
    operations = [migrations.RunPython(drop_orphan, restore_orphan)]
