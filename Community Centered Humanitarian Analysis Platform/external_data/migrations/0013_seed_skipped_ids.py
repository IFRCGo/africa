"""Move four curatorial exclusions out of prose and into a column.

Each one is already written in `notes`, where a person can read it and a fetcher
cannot. The reasons below are copied from those notes rather than paraphrased, so
the two say the same thing. The analysis ids were confirmed against IPC's own
`list_analyses` on 2026-09-15; the listings are saved beside the areas, at
api_cache/ipc/analyses-CAF.json and analyses-TCD.json.

THIS IS A TRANSCRIPTION OF SOMEBODY'S JUDGEMENT. If a reading here is wrong, a
real analysis stays out of the database and nothing complains - which is why the
admin list shows each skipped id with its reason, and why removing one is a
one-line shell command.

NOTE WHICH ONE ACTUALLY MATTERS. Chad's March 2023 analysis and nothing else
would be excluded by the crisis-start floor anyway. 68596035 would NOT: it is a
March 2024 analysis, well inside the crisis window, and only a person's decision
keeps it out. It is the reason this column exists.
"""
from django.db import migrations

SKIPS = {
    # (source, iso3): [(analysis_id, reason), ...]
    ("ch", "TCD"): [
        ("48055748",
         "Cadre Harmonisé March 2023 predates the crisis start (notes, 2026-09-09)"),
        ("68596035",
         "CH March 2024 (displaced population) counts a different denominator and "
         "would not compose with the rest (notes, 2026-09-09)"),
    ],
    ("ipc", "CAF"): [
        ("87143421",
         "May 2026 analysis publishes NO current-period geometry - an empty "
         "FeatureCollection (notes, 2026-09-09)"),
    ],
    ("ipc", "SSD"): [
        ("81832747",
         "Apr 2025 Proj Update publishes no current-period geometry - it is a "
         "projection update, not a new current-situation analysis (notes)"),
    ],
}


def apply_skips(SourceSync):
    """Append the transcribed skips, without duplicating what is already there.

    Split out of the migration body so a test can exercise it on rows it created:
    the real source_sync rows are written by seed_external and do not exist in a
    fresh test database, so a migration that only ever runs against them cannot
    be tested at all.
    """
    for (source, iso3), entries in SKIPS.items():
        for sync in SourceSync.objects.filter(source=source, dataset="food_security",
                                              iso3=iso3):
            held = {s.get("id") for s in (sync.skipped_ids or [])}
            sync.skipped_ids = (sync.skipped_ids or []) + [
                {"id": aid, "reason": reason}
                for aid, reason in entries if aid not in held
            ]
            sync.save(update_fields=["skipped_ids"])


def seed(apps, schema_editor):
    apply_skips(apps.get_model("external_data", "SourceSync"))


def unseed(apps, schema_editor):
    """Reversible, and it only removes what this migration added.

    A skip appended later by a failed pull is somebody's data, not this
    migration's, and dropping it on a rollback would lose it.
    """
    SourceSync = apps.get_model("external_data", "SourceSync")
    seeded = {aid for entries in SKIPS.values() for aid, _ in entries}
    for sync in SourceSync.objects.exclude(skipped_ids=[]):
        kept = [s for s in sync.skipped_ids if s.get("id") not in seeded]
        if len(kept) != len(sync.skipped_ids):
            sync.skipped_ids = kept
            sync.save(update_fields=["skipped_ids"])


class Migration(migrations.Migration):
    dependencies = [("external_data", "0012_source_sync_skipped_ids")]
    operations = [migrations.RunPython(seed, unseed)]
