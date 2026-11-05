"""One source_sync row per country of focus, so each gets its own button.

Eight rows rather than one regional row, because the office asked for the
countries of focus and because a per-country button is what the rest of that
page already offers. They also join the "pull everything out of date" batch for
free - views.stale_rows() picks up anything with a fetcher and a key, with no
whitelist to extend.

The notes column is where a no-op refresh explains itself, and here it records
the thing a reader will otherwise wonder about: why the watermark never narrows
the next request.
"""
from django.db import migrations

COUNTRIES = ["SDN", "TCD", "SSD", "EGY", "ETH", "LBY", "CAF", "UGA"]

NOTE = ("Window is fixed: 15 Apr 2023 to today, on every pull, as asked. "
        "high_water_date therefore never narrows the next request - see "
        "MontandonFetcher.since(). Three calls per press: events, then "
        "severity onto them by corr_id, then impacts.")


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    for iso3 in COUNTRIES:
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3=iso3, variant="",
            defaults={"tool": "monty__search_items", "notes": NOTE},
        )


def unseed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.filter(source="montandon", dataset="hazard_events").delete()


class Migration(migrations.Migration):
    dependencies = [("external_data", "0014_hazard_events")]
    operations = [migrations.RunPython(seed, unseed)]
