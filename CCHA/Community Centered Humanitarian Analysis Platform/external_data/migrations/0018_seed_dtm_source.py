"""The source_sync row that makes the DTM button appear.

A row plus a registered fetcher is all a button needs: views.refresh_argv()
resolves it through fetcher_for() and the page renders Pull now. It joins the
"pull everything out of date" batch for free, because stale_rows() picks up
anything with a fetcher and no whitelist to extend.

`notes` is where a reader is told the thing they will otherwise wonder about:
why this row's watermark is a list of resource ids rather than a date.
"""
from django.db import migrations

NOTE = ("IOM DTM 'Displacement and Return Snapshot' workbooks, from the HDX "
        "catalogue. Each snapshot is a NEW resource rather than an edit, so "
        "known_ids (resource ids) is what narrows the next pull - not "
        "high_water_date. Eight held as of Jul 2026; IOM publishes roughly "
        "quarterly. IDP totals here sit BESIDE the hdx/idps series, not over "
        "it: see the 2026-09-25 spec, section 6.")


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.update_or_create(
        source="dtm", dataset="displacement_snapshot", iso3="SDN", variant="",
        defaults={"tool": "package_show + xlsx", "notes": NOTE},
    )


def unseed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.filter(source="dtm", dataset="displacement_snapshot").delete()


class Migration(migrations.Migration):
    dependencies = [("external_data", "0017_displacementbreakdown_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
