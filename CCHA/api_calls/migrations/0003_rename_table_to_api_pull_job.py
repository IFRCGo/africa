"""The table and the cache folder take the app's new name.

BOTH HALVES HAVE TO TRAVEL TOGETHER. `log_path` and `payload_path` hold
ABSOLUTE paths, so renaming the folder on disk without rewriting them leaves
every job page pointing at a file that is not there - and nothing raises, the
log simply reads empty. Sibling: insights/0009, which does the same for
`Conversion.markdown_path`.

The two replacements are ordered, not interchangeable: the job-log folder is
`<cache>/mcp/` INSIDE `mcp_cache/`, so the narrow pattern has to go first or
the broad one rewrites its parent and leaves `api_cache/mcp/` behind.
"""
from django.db import migrations

PAIRS = (("/mcp_cache/mcp/", "/api_cache/api/"), ("/mcp_cache/", "/api_cache/"))
FIELDS = ("log_path", "payload_path")


def _rewrite(apps, pairs):
    PullJob = apps.get_model("api_calls", "PullJob")
    changed = 0
    for job in PullJob.objects.all().iterator():
        dirty = False
        for field in FIELDS:
            value = getattr(job, field)
            if not value:
                continue
            new = value
            for old, replacement in pairs:
                new = new.replace(old, replacement)
            if new != value:
                setattr(job, field, new)
                dirty = True
        if dirty:
            job.save(update_fields=list(FIELDS))
            changed += 1
    return changed


def forwards(apps, schema_editor):
    _rewrite(apps, PAIRS)


def backwards(apps, schema_editor):
    # Reversed pairs AND reversed order, for the same reason as above.
    _rewrite(apps, tuple((new, old) for old, new in reversed(PAIRS)))


class Migration(migrations.Migration):

    dependencies = [
        ('api_calls', '0002_job_progress_and_batch'),
    ]

    operations = [
        migrations.AlterModelTable(
            name='pulljob',
            table='api_pull_job',
        ),
        migrations.RunPython(forwards, backwards),
    ]
