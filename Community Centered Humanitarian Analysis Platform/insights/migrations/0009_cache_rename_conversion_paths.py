"""`Conversion.markdown_path` follows the cache folder's rename.

The same absolute-path problem as api_calls/0003, and the same fix. A
conversion whose markdown cannot be found is not an error anyone sees: the
wizard re-reads the document with Docling instead, throwing away an OCR pass
that can take minutes on a scanned file.

Only the broad pair is needed here - the converted markdown lives under
`<cache>/insights/converted/`, never under the job-log folder.
"""
from django.db import migrations

OLD, NEW = "/mcp_cache/", "/api_cache/"


def _rewrite(apps, old, new):
    Conversion = apps.get_model("insights", "Conversion")
    for row in Conversion.objects.exclude(markdown_path=None).iterator():
        if row.markdown_path and old in row.markdown_path:
            row.markdown_path = row.markdown_path.replace(old, new)
            row.save(update_fields=["markdown_path"])


def forwards(apps, schema_editor):
    _rewrite(apps, OLD, NEW)


def backwards(apps, schema_editor):
    _rewrite(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ('insights', '0008_extractionjob_codings_rejected'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
