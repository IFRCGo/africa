# External Data Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist everything the MCP servers and Excel workbooks supply into subject-named PostgreSQL tables, with watermarks that let a refresh pull only what is missing or newer.

**Architecture:** A new Django app `external_data` holds five tables and one view. A loader registry turns a recorded JSON payload into rows and writes a `source_sync` watermark in the same transaction. Pipeline steps s06 and s07 stop reading `mcp_cache/` and read the database instead. The assistant still makes every MCP call on the host; nothing here fetches.

**Tech Stack:** Django 5.0.6, PostgreSQL 16 + PostGIS 3.4, psycopg 3, openpyxl. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-09-external-data-persistence-design.md`

## Global Constraints

- **No new Python dependencies.** `requirements.txt` is unchanged by this plan.
- **No GeoDjango.** Geometry columns are created and read with raw SQL, following `boundaries/migrations/0002_geometry_columns.py` and `boundaries/geo.py`.
- **Everything runs in Docker:** `docker compose exec web python manage.py <cmd>`. The host has no Django environment.
- **Tests use Django's built-in runner** (`manage.py test`). There is no pytest in this project and this plan does not add one.
- **Settings read as `os.environ.get(X) or default`**, never `get(X, default)` — an empty string in `.env` must fall through to the default.
- **`nulls_distinct=False` on every unique constraint containing a nullable column.** PostgreSQL's default treats two NULLs as distinct, which would let duplicates through on `iso3`, `admin_pcode` and `population_group`. This is the same trap `admin_areas.uniq_area_identity` already documents.
- **Upserts use `bulk_create(update_conflicts=True, unique_fields=..., update_fields=...)`**, which Django 5.0 compiles to `ON CONFLICT DO UPDATE` on PostgreSQL.
- **Never pull two IPC countries in parallel.** Recorded incident: `-32000 Connection closed`, server down for the session.
- **Step output format is load-bearing.** Pipeline steps print `=== sNN_name ===`; `updater/views.py` parses those lines for its progress bar.

---

### Task 1: App skeleton, `source_sync`, and the test harness

**Files:**
- Create: `external_data/__init__.py`, `external_data/apps.py`, `external_data/models.py`, `external_data/migrations/__init__.py`
- Create: `external_data/tests/__init__.py`, `external_data/tests/test_source_sync.py`
- Modify: `config/settings.py:108-120` (INSTALLED_APPS)

**Interfaces:**
- Consumes: nothing.
- Produces: `external_data.models.SourceSync`, with fields `source`, `dataset`, `iso3`, `variant`, `tool`, `params`, `last_pulled_at`, `high_water_date`, `known_ids`, `row_count`, `notes`. Unique on `(source, dataset, iso3, variant)`.

- [ ] **Step 1: Create the app package**

```bash
mkdir -p "external_data/migrations" "external_data/tests"
touch external_data/__init__.py external_data/migrations/__init__.py external_data/tests/__init__.py
```

`external_data/apps.py`:

```python
"""External humanitarian data: what the MCP servers and the Excel workbooks supply.

Three apps now divide this project's data. `data_track` holds what the UNHCR PDFs
said. `boundaries` holds the geography those statements are placed on. This one
holds what the humanitarian data providers publish directly - IPC phases, FEWS NET
seasons, IOM-DTM displacement, UNHCR refugee stocks - together with the bookkeeping
that says how fresh each of them is.

The tables are named for their subject rather than their source, because a seasonal
calendar is a seasonal calendar whether FEWS NET or ACAPS published it. Which
provider a row came from is a column, not a table name.
"""
from django.apps import AppConfig


class ExternalDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "external_data"
```

- [ ] **Step 2: Register the app**

In `config/settings.py`, add to `INSTALLED_APPS` after `"boundaries",`:

```python
    "external_data",                 # IPC, FEWS NET, DTM, UNHCR + their freshness
```

- [ ] **Step 3: Write the failing test**

`external_data/tests/test_source_sync.py`:

```python
"""What the watermark table must guarantee.

The first test is the one that matters. An earlier draft of this design keyed the
table on a digest of the call's arguments, which is wrong in a way that is easy to
miss: `start_date` is one of those arguments, so every incremental pull would have
hashed differently, created a new row, and left the next pull with no accumulated
watermark to read. The row identifies a thing that CAN be pulled, not a pull.
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from external_data.models import SourceSync


class SourceSyncIdentityTests(TestCase):
    def test_two_pulls_of_the_same_thing_are_one_row(self):
        """Different start_date, same row - this is the whole mechanism."""
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview",
            params={"start_date": "2024-01-01"}, high_water_date=date(2024, 6, 30),
        )
        row = SourceSync.objects.get(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        row.params = {"start_date": "2024-06-30"}
        row.high_water_date = date(2025, 12, 31)
        row.save()

        self.assertEqual(SourceSync.objects.count(), 1)
        self.assertEqual(
            SourceSync.objects.get().high_water_date, date(2025, 12, 31)
        )

    def test_duplicate_identity_is_refused(self):
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceSync.objects.create(
                source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
            )

    def test_variants_are_separate_rows(self):
        """IDPs at admin1 and at admin2 are genuinely different things to pull."""
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin1"
        )
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview"
        )
        self.assertEqual(SourceSync.objects.count(), 2)

    def test_null_iso3_still_collides(self):
        """A global pull has no country. Two NULLs must not slip past the constraint."""
        SourceSync.objects.create(source="ipc", dataset="food_security", variant="")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceSync.objects.create(source="ipc", dataset="food_security", variant="")
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `docker compose exec web python manage.py test external_data -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'external_data.models'`

- [ ] **Step 5: Write the model**

`external_data/models.py`:

```python
"""The subject tables, and the one table that says how fresh they are.

    SourceSync        one row per thing that can be pulled, and its watermark
    SeasonalCalendar  lean / harvest / dry bands, per country          (task 3)
    FoodSecurityArea  IPC and Cadre Harmonise phases, per area         (task 4)
    MovementPattern   IDP and refugee series, long format              (task 5)
    BorderCrossing    curated crossings, no API behind them            (task 7)

Geometry is not declared here. `FoodSecurityArea` gains two PostGIS columns in
migration 0002, added with raw SQL, exactly as `admin_areas` does and for the same
reason: GeoDjango would mean GDAL in the web image for no capability this needs.
"""
from django.db import models


class SourceSync(models.Model):
    """What has already been fetched, so the next pull asks only for the rest.

    IDENTITY EXCLUDES THE CALL'S ARGUMENTS, and that is the point of this table.
    `params` records the last call made, for reproducibility, but it is not part of
    the unique key - `start_date` lives in there, so keying on it would give every
    incremental pull its own row and the watermark would never accumulate.

    `variant` is what legitimately separates two rows for one country: IDPs at
    admin1 and IDPs at admin2 are different things to fetch. Date windows, page
    offsets and result limits never are.
    """

    source = models.TextField(help_text="fewsnet / ipc / hdx / unhcr / acaps / excel")
    dataset = models.TextField(help_text="seasonal_calendar / food_security / idps / refugees")
    iso3 = models.CharField(max_length=3, null=True, blank=True, help_text="Null for a global pull")
    variant = models.TextField(
        default="", blank=True, help_text="Which slice: 'admin2-overview' vs 'admin1'"
    )
    tool = models.TextField(null=True, blank=True, help_text="The MCP tool called")
    params = models.JSONField(
        default=dict, blank=True, help_text="The last call made. NOT part of identity."
    )

    # last_pulled_at moves on every attempt; high_water_date moves only when data
    # genuinely newer than what we held came back. Keeping them apart is what stops
    # a no-op refresh from looking like fresh data.
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    high_water_date = models.DateField(
        null=True, blank=True, help_text="Latest DATA date held - not the pull date"
    )
    known_ids = models.JSONField(
        default=list, blank=True,
        help_text="Identities already held, for sources with no date filter (IPC analysis ids)",
    )
    row_count = models.IntegerField(default=0)
    notes = models.TextField(
        null=True, blank=True,
        help_text="e.g. 'publishes annually, latest 2024' - so a no-op refresh explains itself",
    )

    class Meta:
        db_table = "source_sync"
        ordering = ["source", "dataset", "iso3", "variant"]
        constraints = [
            # nulls_distinct=False because iso3 is null for global pulls, and under
            # PostgreSQL's default rule two nulls never collide - so duplicate
            # global rows would accumulate silently.
            models.UniqueConstraint(
                fields=["source", "dataset", "iso3", "variant"],
                name="uniq_source_sync_identity",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        where = self.iso3 or "global"
        return f"{self.source}/{self.dataset} {where} {self.variant}".strip()
```

- [ ] **Step 6: Make and apply the migration**

```bash
docker compose exec web python manage.py makemigrations external_data
docker compose exec web python manage.py migrate
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test external_data -v 2`
Expected: PASS, 4 tests.

If test-database creation fails on `CREATE EXTENSION postgis`, the configured
`POSTGRES_USER` lacks superuser rights. Fix by granting once:
`docker compose exec db psql -U postgres -c "ALTER ROLE sudan SUPERUSER;"` — record it in
`MAINTENANCE.md` rather than working around it in code.

- [ ] **Step 8: Commit**

```bash
git add external_data config/settings.py
git commit -m "external_data app: the source_sync watermark table

Identity is (source, dataset, iso3, variant) and deliberately excludes the call's
arguments: start_date is one of them, so keying on it would give every incremental
pull its own row and the watermark could never accumulate."
```

---

### Task 2: `external_status` — what is held and what is missing

**Files:**
- Create: `external_data/management/__init__.py`, `external_data/management/commands/__init__.py`, `external_data/management/commands/external_status.py`
- Create: `external_data/tests/test_external_status.py`

**Interfaces:**
- Consumes: `SourceSync` from Task 1.
- Produces: `python manage.py external_status [--json]`. The `--json` form emits a list of dicts with keys `source`, `dataset`, `iso3`, `variant`, `last_pulled_at`, `high_water_date`, `row_count`, `notes`. Task 9 reuses this shape for `/api/sync/`.

- [ ] **Step 1: Write the failing test**

`external_data/tests/test_external_status.py`:

```python
"""The command an analyst runs before asking for a refresh.

It is the first command of any refresh, so its job is to be readable and to be
honest about the difference between 'pulled recently' and 'holds recent data'.
"""
import json
from datetime import date, datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from external_data.models import SourceSync


class ExternalStatusTests(TestCase):
    def setUp(self):
        SourceSync.objects.create(
            source="hdx", dataset="idps", iso3="SDN", variant="admin2-overview",
            last_pulled_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
            high_water_date=date(2025, 12, 31), row_count=4210,
            notes="source has published nothing for 2026 yet",
        )
        SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="TCD", variant="",
            last_pulled_at=None, high_water_date=None, row_count=0,
        )

    def test_json_output_reports_every_row(self):
        out = StringIO()
        call_command("external_status", "--json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(len(rows), 2)
        by_key = {(r["source"], r["iso3"]): r for r in rows}
        self.assertEqual(by_key[("hdx", "SDN")]["high_water_date"], "2025-12-31")
        self.assertEqual(by_key[("hdx", "SDN")]["row_count"], 4210)

    def test_never_pulled_is_shown_as_never_not_as_blank(self):
        """A row that has never been pulled is the most important thing to see."""
        out = StringIO()
        call_command("external_status", stdout=out)
        text = out.getvalue()
        self.assertIn("TCD", text)
        self.assertIn("never", text.lower())

    def test_notes_are_shown_so_a_no_op_refresh_explains_itself(self):
        out = StringIO()
        call_command("external_status", stdout=out)
        self.assertIn("nothing for 2026", out.getvalue())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python manage.py test external_data.tests.test_external_status -v 2`
Expected: FAIL — `CommandError: Unknown command: 'external_status'`

- [ ] **Step 3: Write the command**

`external_data/management/commands/external_status.py`:

```python
"""`python manage.py external_status` - what external data is held, and how fresh.

This is the FIRST command of any refresh. It answers the only question that
matters before making an MCP call: what does the database already have?

    docker compose exec web python manage.py external_status
    docker compose exec web python manage.py external_status --json

Two dates are shown per row and they mean different things. "pulled" is when we
last asked. "data to" is the newest data we actually hold. A source that publishes
annually will show a recent pull and an old data date, and that is correct, not a
fault - which is why `notes` is printed beside them.
"""
import json

from django.core.management.base import BaseCommand

from external_data.models import SourceSync


def status_rows():
    """Every watermark as a plain dict. Shared with /api/sync/ in external_data.views."""
    return [
        {
            "source": r.source,
            "dataset": r.dataset,
            "iso3": r.iso3,
            "variant": r.variant,
            "last_pulled_at": r.last_pulled_at.isoformat() if r.last_pulled_at else None,
            "high_water_date": r.high_water_date.isoformat() if r.high_water_date else None,
            "row_count": r.row_count,
            "known_id_count": len(r.known_ids or []),
            "notes": r.notes or "",
        }
        for r in SourceSync.objects.all()
    ]


class Command(BaseCommand):
    help = "Show what external data is held and how fresh it is."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", dest="as_json",
            help="Emit machine-readable JSON instead of a table.",
        )

    def handle(self, *args, **options):
        rows = status_rows()
        if options["as_json"]:
            self.stdout.write(json.dumps(rows, indent=2))
            return

        if not rows:
            self.stdout.write("No external data has been loaded yet.")
            return

        header = f"{'source':<9} {'dataset':<17} {'iso3':<5} {'variant':<18} " \
                 f"{'pulled':<12} {'data to':<12} {'rows':>7}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for r in rows:
            pulled = (r["last_pulled_at"] or "never")[:10]
            data_to = r["high_water_date"] or "-"
            self.stdout.write(
                f"{r['source']:<9} {r['dataset']:<17} {(r['iso3'] or '-'):<5} "
                f"{r['variant']:<18} {pulled:<12} {data_to:<12} {r['row_count']:>7}"
            )
            if r["notes"]:
                self.stdout.write(f"          note: {r['notes']}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test external_data -v 2`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add external_data
git commit -m "external_status: what is held, how fresh, and what was never pulled"
```

---

### Task 3: The loader framework and the FEWS NET seasonal parser

**Files:**
- Create: `external_data/loaders/__init__.py`, `external_data/loaders/base.py`, `external_data/loaders/seasonal.py`
- Create: `external_data/management/commands/load_external.py`
- Create: `external_data/tests/fixtures/fewsnet_seasons_TCD.json`, `external_data/tests/fixtures/empty.json`
- Create: `external_data/tests/test_loader.py`
- Modify: `external_data/models.py` (add `SeasonalCalendar`)

**Interfaces:**
- Consumes: `SourceSync` (Task 1).
- Produces:
  - `external_data.loaders.base.Loader` — subclass API: class attributes `dataset`, `source`, `model`, `unique_fields`, `update_fields`; methods `parse(payload, iso3) -> list[dict]`, `sync_key(iso3) -> dict`, `high_water(rows) -> date | None`, `known_ids(rows) -> list`.
  - `external_data.loaders.LOADERS` — dict mapping dataset name to loader class, populated by the `@register` decorator.
  - `external_data.loaders.base.load(loader, payload, iso3, dry_run=False) -> LoadResult` with attributes `written`, `high_water_date`, `sync`.
  - `python manage.py load_external <dataset> <file.json> [--iso3 XXX] [--dry-run]`
  - `external_data.models.SeasonalCalendar`

- [ ] **Step 1: Record the fixture**

Save the real FEWS NET Chad payload (15 results, already pulled and verified) to
`external_data/tests/fixtures/fewsnet_seasons_TCD.json`. It is the response of
`get_seasons(country_code="TD")`: an object with `count`, `next`, `previous` and
`results`, where each result carries `name`, `country`, `purpose`, `season_type`,
`start_month`, `end_month`, `alignment`, `fnid`, `unit_type`, `description`,
`order`, `aliases`, `country_code`. Six results have `fnid: "TD"`; the other nine
repeat three of those seasons under `fnid` values `TD1960A0`, `TD2008A0` and
`TD2012A0`.

Also create `external_data/tests/fixtures/empty.json` containing exactly:

```json
{"count": 0, "next": null, "previous": null, "results": []}
```

- [ ] **Step 2: Write the failing tests**

`external_data/tests/test_loader.py`:

```python
"""What every loader must guarantee, proved on the smallest real source.

The de-duplication test uses the genuine Chad payload rather than a hand-made one,
because the duplication is the kind of thing nobody invents: FEWS NET returns each
season once per historical geographic-unit version, so Chad's six seasons arrive as
fifteen rows. A loader that misses this renders every band three times.
"""
import json
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from external_data.models import SeasonalCalendar, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SeasonalLoaderTests(TestCase):
    fixture = "fewsnet_seasons_TCD.json"

    def _load(self, **kwargs):
        call_command("load_external", "seasonal_calendar",
                     str(FIXTURES / self.fixture), "--iso3", "TCD", **kwargs)

    def test_historical_unit_versions_are_discarded(self):
        """15 rows in, 6 out - one per real season, none from a versioned fnid."""
        self._load()
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        refs = set(SeasonalCalendar.objects.values_list("source_ref", flat=True))
        self.assertEqual(refs, {"TD"})

    def test_the_lean_season_is_read_correctly(self):
        self._load()
        lean = SeasonalCalendar.objects.get(label="Lean", purpose="NutritionIndicator")
        self.assertEqual((lean.start_month, lean.end_month), (4, 9))
        self.assertEqual(lean.season_type, "Lean")
        self.assertEqual(lean.iso3, "TCD")
        self.assertIn("soudure", lean.aliases)

    def test_a_season_that_wraps_the_year_end_is_kept_as_published(self):
        """Chad's cold off-season harvest is November to February. Do not 'fix' it."""
        self._load()
        cold = SeasonalCalendar.objects.get(label="Cold off-season harvest")
        self.assertEqual((cold.start_month, cold.end_month), (11, 2))

    def test_loading_twice_changes_nothing(self):
        self._load()
        self._load()
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        self.assertEqual(SourceSync.objects.count(), 1)
        self.assertEqual(SourceSync.objects.get().row_count, 6)

    def test_the_watermark_is_written(self):
        self._load()
        sync = SourceSync.objects.get()
        self.assertEqual(sync.source, "fewsnet")
        self.assertEqual(sync.dataset, "seasonal_calendar")
        self.assertEqual(sync.iso3, "TCD")
        self.assertIsNotNone(sync.last_pulled_at)

    def test_dry_run_writes_nothing(self):
        self._load(dry_run=True)
        self.assertEqual(SeasonalCalendar.objects.count(), 0)
        self.assertEqual(SourceSync.objects.count(), 0)


class EmptyPayloadTests(TestCase):
    def test_an_empty_payload_fails_loudly(self):
        """An MCP error serialised as [] must never be recorded as 'up to date'.

        This is the failure mode most likely to make the whole design lie: a silent
        empty load would advance the watermark and the next refresh would skip
        genuinely missing data forever.
        """
        with self.assertRaises(CommandError):
            call_command("load_external", "seasonal_calendar",
                         str(FIXTURES / "empty.json"), "--iso3", "TCD")
        self.assertEqual(SourceSync.objects.count(), 0)
        self.assertEqual(SeasonalCalendar.objects.count(), 0)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec web python manage.py test external_data.tests.test_loader -v 2`
Expected: FAIL — `CommandError: Unknown command: 'load_external'`

- [ ] **Step 4: Add the `SeasonalCalendar` model**

Append to `external_data/models.py`:

```python
class SeasonalCalendar(models.Model):
    """When the lean season bites, when the harvest comes in - per country.

    NO COLOUR COLUMN, deliberately. The dashboard's calendar strip needs one, but
    FEWS NET does not publish colours, so a colour column would be null for every
    real row. Colour is derived at build time from `season_type`, which also means
    a lean season is the same colour in every country.
    """

    iso3 = models.CharField(max_length=3, db_index=True)
    country_name = models.TextField()
    admin_pcode = models.TextField(
        null=True, blank=True,
        help_text="Null for a national calendar. ACAPS publishes at admin-1.",
    )
    source = models.TextField(help_text="fewsnet / acaps / curated")
    source_ref = models.TextField(
        null=True, blank=True, help_text="FEWS NET fnid, or the ACAPS record id"
    )
    label = models.TextField(help_text="'Lean', 'Main harvest', 'Post-harvest'")
    season_type = models.TextField(null=True, blank=True, help_text="Lean / Harvest / Dry / Rainy")
    purpose = models.TextField(
        null=True, blank=True, help_text="NutritionIndicator / CropProductionIndicator"
    )
    # A season that runs November to February has end_month < start_month. That is
    # the source telling the truth about the calendar, not an error to correct.
    start_month = models.IntegerField()
    end_month = models.IntegerField()
    alignment = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    aliases = models.JSONField(
        default=list, blank=True, help_text="Multilingual synonyms - 'soudure' for lean"
    )
    display_order = models.IntegerField(default=0)

    class Meta:
        db_table = "seasonal_calendar"
        ordering = ["iso3", "purpose", "display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "iso3", "admin_pcode", "purpose", "label"],
                name="uniq_seasonal_band",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        return f"{self.iso3} {self.label} ({self.start_month}-{self.end_month})"
```

- [ ] **Step 5: Write the loader framework**

`external_data/loaders/base.py`:

```python
"""The contract every loader keeps, and the one function that applies it.

A loader is a small class that knows how to turn one recorded payload into rows.
It does not know where the payload came from, which is the point: the assistant
pulls through MCP today and something else might fetch the same JSON tomorrow.

Four guarantees, enforced here rather than left to each parser:

  idempotent    upsert on the natural key, so loading a file twice is a no-op
  transactional one file is one transaction; a bad record aborts the whole load
  ordered       source_sync is written LAST, inside that transaction, so the
                watermark can never claim data the tables do not have
  loud on empty an MCP error serialised as [] is a failed load, never 'up to date'
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from django.db import transaction

from external_data.models import SourceSync


class EmptyPayload(Exception):
    """The payload held no usable rows. Never treated as success."""


@dataclass
class LoadResult:
    written: int
    high_water_date: object
    sync: object


class Loader:
    """Subclass and set the five class attributes, then implement parse()."""

    dataset = ""          # 'seasonal_calendar' - also the command-line name
    source = ""           # 'fewsnet'
    model = None          # the Django model rows are written to
    unique_fields = []    # the natural key, matching the model's UniqueConstraint
    update_fields = []    # everything else, overwritten on conflict
    tool = ""             # the MCP tool this payload came from, for the record

    def parse(self, payload, iso3):
        """Return a list of dicts, one per model row. Pure - no database access."""
        raise NotImplementedError

    def sync_key(self, iso3):
        """Which source_sync row this load belongs to. Arguments are NEVER part of it."""
        return {"source": self.source, "dataset": self.dataset, "iso3": iso3, "variant": ""}

    def high_water(self, rows):
        """The newest DATA date in these rows, or None for a dateless source."""
        return None

    def known_ids(self, rows):
        """Identities now held, for sources with no date filter. Merged, not replaced."""
        return []


@transaction.atomic
def load(loader, payload, iso3, dry_run=False):
    """Parse, upsert, then write the watermark - all or nothing."""
    rows = loader.parse(payload, iso3)
    if not rows:
        # Deliberately an exception. Recording an empty pull as a successful one
        # would advance the watermark past data we do not have, and every later
        # refresh would skip it.
        raise EmptyPayload(
            f"{loader.dataset}: the payload produced no rows. "
            "An MCP error serialised as an empty list looks exactly like this - "
            "check the pull before treating it as 'nothing new'."
        )

    if dry_run:
        return LoadResult(written=len(rows), high_water_date=loader.high_water(rows), sync=None)

    objects = [loader.model(**row) for row in rows]
    loader.model.objects.bulk_create(
        objects,
        update_conflicts=True,
        unique_fields=loader.unique_fields,
        update_fields=loader.update_fields,
    )

    key = loader.sync_key(iso3)
    sync, _ = SourceSync.objects.get_or_create(**key)
    sync.tool = loader.tool
    sync.last_pulled_at = datetime.now(timezone.utc)
    hw = loader.high_water(rows)
    # Only ever move forward. A backfill of older data must not rewind the mark.
    if hw and (sync.high_water_date is None or hw > sync.high_water_date):
        sync.high_water_date = hw
    new_ids = loader.known_ids(rows)
    if new_ids:
        sync.known_ids = sorted(set(sync.known_ids or []) | set(new_ids))
    sync.row_count = loader.model.objects.filter(
        **{k: v for k, v in key.items() if k in ("source", "iso3")}
    ).count()
    sync.save()

    return LoadResult(written=len(rows), high_water_date=sync.high_water_date, sync=sync)
```

`external_data/loaders/__init__.py`:

```python
"""The loader registry. Adding a source is adding a file, not editing a command."""
LOADERS = {}


def register(cls):
    """Class decorator: put a Loader subclass into the registry under its dataset."""
    LOADERS[cls.dataset] = cls
    return cls


# Importing the modules is what populates LOADERS.
from external_data.loaders import seasonal  # noqa: E402,F401
```

- [ ] **Step 6: Write the seasonal parser**

`external_data/loaders/seasonal.py`:

```python
"""FEWS NET `get_seasons` -> seasonal_calendar rows.

THE DE-DUPLICATION IS THE WHOLE JOB. FEWS NET returns every season once per
historical version of the geographic unit it applies to, so Chad's six real seasons
arrive as fifteen records: six under fnid "TD", and three more each under
"TD1960A0", "TD2008A0" and "TD2012A0" - the country's 1960, 2008 and 2012 unit
definitions. They carry identical months. Keeping them all would draw every band
three times over.

The rule: keep the national record for the CURRENT definition - unit_type "Admin 0"
and an fnid equal to the plain country code - and discard the rest.
"""
from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import SeasonalCalendar

# FEWS NET speaks ISO 3166-1 alpha-2; everything else here speaks alpha-3.
ISO3_TO_ISO2 = {
    "SDN": "SD", "TCD": "TD", "EGY": "EG", "ETH": "ET", "LBY": "LY",
    "SSD": "SS", "UGA": "UG", "CAF": "CF", "ERI": "ER",
}


@register
class SeasonalLoader(Loader):
    dataset = "seasonal_calendar"
    source = "fewsnet"
    model = SeasonalCalendar
    tool = "get_seasons"
    unique_fields = ["source", "iso3", "admin_pcode", "purpose", "label"]
    update_fields = [
        "country_name", "source_ref", "season_type", "start_month", "end_month",
        "alignment", "description", "aliases", "display_order",
    ]

    def parse(self, payload, iso3):
        iso2 = ISO3_TO_ISO2.get(iso3)
        results = payload.get("results", []) if isinstance(payload, dict) else payload
        rows = []
        for r in results:
            # The two conditions that drop the historical unit versions.
            if r.get("unit_type") != "Admin 0":
                continue
            if r.get("fnid") != (iso2 or r.get("country_code")):
                continue
            rows.append({
                "iso3": iso3,
                "country_name": r.get("country") or "",
                "admin_pcode": None,
                "source": self.source,
                "source_ref": r.get("fnid"),
                "label": r.get("name") or "",
                "season_type": r.get("season_type"),
                "purpose": r.get("purpose"),
                "start_month": r.get("start_month"),
                "end_month": r.get("end_month"),
                "alignment": r.get("alignment"),
                "description": r.get("description") or "",
                "aliases": r.get("aliases") or [],
                "display_order": r.get("order") or 0,
            })
        return rows
```

- [ ] **Step 7: Write the `load_external` command**

`external_data/management/commands/load_external.py`:

```python
"""`python manage.py load_external <dataset> <file.json>` - cache into database.

The assistant pulls through MCP on the host and drops the raw response into
data_pipeline/mcp_cache/. This command is the other half: it reads one of those
files and upserts it into the subject tables, writing the watermark as it goes.

    load_external seasonal_calendar mcp_cache/seasonal/TCD.json --iso3 TCD
    load_external food_security     mcp_cache/ipc/TCD-89623970.json --iso3 TCD --dry-run

The cache file is staging, not truth. Keeping it on disk means any load can be
replayed without going back to a single MCP server.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load


class Command(BaseCommand):
    help = "Load one recorded MCP payload into the external data tables."

    def add_arguments(self, parser):
        parser.add_argument("dataset", choices=sorted(LOADERS), help="Which loader to use")
        parser.add_argument("path", help="Path to the recorded JSON payload")
        parser.add_argument("--iso3", default=None, help="Country the payload is for")
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change and write nothing.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}") from exc

        loader = LOADERS[options["dataset"]]()
        try:
            result = load(loader, payload, options["iso3"], dry_run=options["dry_run"])
        except EmptyPayload as exc:
            raise CommandError(str(exc)) from exc

        verb = "would write" if options["dry_run"] else "wrote"
        self.stdout.write(f"{verb} {result.written} rows to {loader.model._meta.db_table}")
        if result.high_water_date:
            self.stdout.write(f"  data now held to {result.high_water_date}")
```

- [ ] **Step 8: Make the migration and run the tests**

```bash
docker compose exec web python manage.py makemigrations external_data
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, 14 tests.

- [ ] **Step 9: Commit**

```bash
git add external_data
git commit -m "Loader framework, and the FEWS NET seasonal parser

Four guarantees enforced in one place: idempotent upsert, one transaction per
file, source_sync written last, and an empty payload raising rather than being
recorded as 'up to date'.

The seasonal parser drops FEWS NET's historical geographic-unit versions -
Chad's six seasons arrive as fifteen records, repeated under the country's 1960,
2008 and 2012 unit definitions."
```

---

### Task 4: Food security — model, geometry columns, and the IPC parser

**Files:**
- Modify: `external_data/models.py` (add `FoodSecurityArea`)
- Create: `external_data/migrations/000N_food_security_geometry.py` (raw SQL)
- Create: `external_data/loaders/food_security.py`
- Create: `external_data/tests/fixtures/ipc_areas_TCD_89623970.geojson`
- Create: `external_data/tests/test_food_security.py`
- Modify: `external_data/loaders/__init__.py` (import the new module)

**Interfaces:**
- Consumes: `Loader`, `register`, `load` (Task 3).
- Produces: `external_data.models.FoodSecurityArea`; `FoodSecurityLoader` registered as dataset `food_security`; helper `external_data.loaders.food_security.write_geometry(rows)` which sets `geom`/`geom_web` by raw SQL after the upsert.

- [ ] **Step 1: Record the fixture**

Trim a real IPC `get_areas_by_analysis` GeoJSON response to **three features** and
save as `external_data/tests/fixtures/ipc_areas_TCD_89623970.geojson`. Keep the
`FeatureCollection` envelope and, on each feature's `properties`, the keys the
existing `s06_mcp_layers.build_foodsec` already reads: `title`, `overall_phase`,
`phase3_percent`, `phase4_percent`, `phase5_percent`, `phase5_population`, `color`.
Give one feature `overall_phase: null` — the parser must skip it, exactly as
`build_foodsec` does today.

- [ ] **Step 2: Write the failing tests**

`external_data/tests/test_food_security.py`:

```python
"""IPC phases into the database, geometry included.

Two behaviours are carried over from s06_mcp_layers.build_foodsec deliberately:
an area with no overall_phase is skipped, and phase 3+ is the sum of the phase 3,
4 and 5 percentages. Changing either would change what the map has always shown.
"""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from external_data.models import FoodSecurityArea, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


class FoodSecurityLoaderTests(TestCase):
    def _load(self, **kwargs):
        call_command("load_external", "food_security",
                     str(FIXTURES / "ipc_areas_TCD_89623970.geojson"),
                     "--iso3", "TCD", **kwargs)

    def test_areas_without_a_phase_are_skipped(self):
        self._load()
        self.assertEqual(FoodSecurityArea.objects.count(), 2)

    def test_phase3plus_is_the_sum_of_phases_3_4_and_5(self):
        self._load()
        area = FoodSecurityArea.objects.exclude(phase3plus_pct=None).first()
        self.assertAlmostEqual(
            area.phase3plus_pct,
            round((area.phase3_pct or 0) + (area.phase4_pct or 0) + (area.phase5_pct or 0), 3),
        )

    def test_the_source_records_cadre_harmonise_for_chad(self):
        self._load()
        self.assertEqual(set(FoodSecurityArea.objects.values_list("source", flat=True)), {"ch"})

    def test_geometry_is_written_and_simplified(self):
        self._load()
        with connection.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM food_security
                WHERE geom IS NOT NULL AND geom_web IS NOT NULL
            """)
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute("""
                SELECT ST_NPoints(geom) >= ST_NPoints(geom_web) FROM food_security LIMIT 1
            """)
            self.assertTrue(cur.fetchone()[0])

    def test_loading_twice_changes_nothing(self):
        self._load()
        self._load()
        self.assertEqual(FoodSecurityArea.objects.count(), 2)

    def test_the_analysis_id_is_remembered_for_identity_diffing(self):
        """IPC has no date filter, so known_ids is how we know what to skip."""
        self._load()
        sync = SourceSync.objects.get(source="ch", dataset="food_security", iso3="TCD")
        self.assertIn("89623970", sync.known_ids)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec web python manage.py test external_data.tests.test_food_security -v 2`
Expected: FAIL — `ImportError: cannot import name 'FoodSecurityArea'`

- [ ] **Step 4: Add the model**

Append to `external_data/models.py`:

```python
class FoodSecurityArea(models.Model):
    """One IPC or Cadre Harmonise analysis unit, at one phase, in one period.

    IPC ANALYSIS UNITS ARE NOT ADMIN UNITS. IPC redraws them each round, which is
    why the existing ipc_areas_fs.geojson holds a complete snapshot per period
    rather than a series per area. The geometry is stored as IPC published it;
    `admin_pcode` is a convenience join filled in where a polygon confidently
    matches one in admin_areas, and left null otherwise. Nothing depends on it.

    `source` separates products that must never be conflated: 'ipc' is an official
    IPC analysis, 'ch' a Cadre Harmonise one (same five-phase scale, used across
    the Sahel - Chad's analyses are these), and 'fewsnet' is FEWS NET's own
    IPC-compatible assessment, which is a different organisation's judgement.
    """

    source = models.TextField(db_index=True, help_text="ipc / ch / fewsnet")
    analysis_id = models.TextField(db_index=True)
    analysis_title = models.TextField(null=True, blank=True)
    condition = models.CharField(
        max_length=1, null=True, blank=True, help_text="A acute, C chronic"
    )
    iso3 = models.CharField(max_length=3, db_index=True)
    period_date = models.DateField(db_index=True, help_text="First day of the period described")
    period_type = models.TextField(
        default="current", help_text="current / projection / second_projection"
    )
    area_id = models.TextField()
    area_title = models.TextField(null=True, blank=True)
    admin_pcode = models.TextField(null=True, blank=True)

    phase = models.IntegerField(null=True, blank=True, help_text="Overall IPC phase 1-5")
    phase3_pct = models.FloatField(null=True, blank=True)
    phase4_pct = models.FloatField(null=True, blank=True)
    phase5_pct = models.FloatField(null=True, blank=True)
    phase3plus_pct = models.FloatField(null=True, blank=True, help_text="Phases 3+4+5")
    phase5_population = models.BigIntegerField(null=True, blank=True)
    total_population = models.BigIntegerField(null=True, blank=True)
    # IPC's own phase colour, kept so the map never invents one.
    colour = models.TextField(null=True, blank=True)

    # geom / geom_web  geometry(MultiPolygon, 4326) - added in the raw SQL migration

    class Meta:
        db_table = "food_security"
        ordering = ["iso3", "period_date", "area_title"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "analysis_id", "period_type", "area_id"],
                name="uniq_food_security_area",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["iso3", "period_date"], name="idx_fs_country_period"),
        ]

    @property
    def famine(self):
        """Phase 5 present - what the dashboard's 'fam' flag has always meant."""
        return bool((self.phase5_population or 0) > 0 or (self.phase is not None and self.phase >= 5))

    def __str__(self):
        return f"{self.iso3} {self.area_title} phase {self.phase} ({self.period_date})"
```

- [ ] **Step 5: Write the geometry migration**

Create `external_data/migrations/000N_food_security_geometry.py` (replace `000N`
and the dependency with the actual latest migration name):

```python
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

    dependencies = [("external_data", "000N_previous")]

    operations = [
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
```

- [ ] **Step 6: Write the parser**

`external_data/loaders/food_security.py`:

```python
"""IPC `get_areas_by_analysis` GeoJSON -> food_security rows.

The two rules carried over verbatim from s06_mcp_layers.build_foodsec, because
changing either would change what the map has shown since it was built:

  * an area with no overall_phase is skipped entirely
  * phase 3+ is phase3_percent + phase4_percent + phase5_percent, rounded to 3dp

Geometry goes in through raw SQL after the upsert. ST_SimplifyPreserveTopology at
the same tolerance boundaries uses for a district (0.002 degrees, about 220 m) is
what makes the web copy small enough to send.
"""
import json
import re

from django.db import connection

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import FoodSecurityArea

# Sahel analyses are Cadre Harmonise; elsewhere the same API serves IPC proper.
CH_COUNTRIES = {"TCD", "MLI", "NER", "BFA", "SEN", "MRT", "NGA"}

SIMPLIFY_TOLERANCE = 0.002


@register
class FoodSecurityLoader(Loader):
    dataset = "food_security"
    model = FoodSecurityArea
    tool = "get_areas_by_analysis"
    unique_fields = ["source", "analysis_id", "period_type", "area_id"]
    update_fields = [
        "analysis_title", "condition", "iso3", "period_date", "area_title",
        "phase", "phase3_pct", "phase4_pct", "phase5_pct", "phase3plus_pct",
        "phase5_population", "total_population", "colour",
    ]

    # `source` varies per country, so it cannot be a fixed class attribute.
    def source_for(self, iso3):
        return "ch" if iso3 in CH_COUNTRIES else "ipc"

    def sync_key(self, iso3):
        return {
            "source": self.source_for(iso3), "dataset": self.dataset,
            "iso3": iso3, "variant": "",
        }

    def parse(self, payload, iso3):
        meta = payload.get("_meta", {}) if isinstance(payload, dict) else {}
        analysis_id = str(meta.get("analysis_id") or payload.get("analysis_id") or "")
        period_date = _period_date(payload, meta)
        source = self.source_for(iso3)

        rows = []
        for ft in payload.get("features", []):
            p = ft.get("properties", {})
            phase = p.get("overall_phase")
            if phase is None:
                continue                      # same rule as build_foodsec
            p3 = p.get("phase3_percent") or 0
            p4 = p.get("phase4_percent") or 0
            p5 = p.get("phase5_percent") or 0
            rows.append({
                "source": source,
                "analysis_id": analysis_id,
                "analysis_title": meta.get("title") or "",
                "condition": (meta.get("condition") or "A")[:1],
                "iso3": iso3,
                "period_date": period_date,
                "period_type": meta.get("period_type") or "current",
                "area_id": str(p.get("area_id") or p.get("id") or (p.get("title") or "").strip()),
                "area_title": (p.get("title") or "").strip(),
                "admin_pcode": None,
                "phase": phase,
                "phase3_pct": p.get("phase3_percent"),
                "phase4_pct": p.get("phase4_percent"),
                "phase5_pct": p.get("phase5_percent"),
                "phase3plus_pct": round(p3 + p4 + p5, 3),
                "phase5_population": p.get("phase5_population"),
                "total_population": p.get("total_population"),
                "colour": p.get("color") or "#cccccc",
                # carried out of band to write_geometry, not a model field
                "_geometry": ft.get("geometry"),
            })
        return rows

    def known_ids(self, rows):
        return [r["analysis_id"] for r in rows if r["analysis_id"]]

    def high_water(self, rows):
        return max((r["period_date"] for r in rows if r["period_date"]), default=None)


def _period_date(payload, meta):
    """The first day of the period, from the metadata or the filename convention."""
    from datetime import date
    raw = meta.get("period_date") or meta.get("period") or ""
    m = re.search(r"(\d{4})-(\d{2})", str(raw))
    if m:
        return date(int(m[1]), int(m[2]), 1)
    return date(1900, 1, 1)     # never silently today's date; an obvious sentinel
```

The `_geometry` key must be stripped before `bulk_create`. Add to `base.load`,
immediately before `objects = [...]`:

```python
    geometries = [row.pop("_geometry", None) for row in rows]
```

and immediately after the `bulk_create` call:

```python
    if any(g is not None for g in geometries):
        _write_geometry(loader, rows, geometries)
```

with this helper at the bottom of `base.py`:

```python
def _write_geometry(loader, rows, geometries):
    """Set geom and geom_web by raw SQL, one row at a time, keyed on the natural key.

    Raw SQL because these columns are invisible to Django - see the migration.
    ST_Multi wraps a plain Polygon so the MultiPolygon column accepts it;
    ST_MakeValid repairs the self-intersections that publishers' polygons carry.
    """
    where = " AND ".join(f"{f} = %s" for f in loader.unique_fields)
    sql = f"""
        UPDATE {loader.model._meta.db_table}
           SET geom = ST_Multi(ST_MakeValid(ST_GeomFromGeoJSON(%s))),
               geom_web = ST_Multi(ST_CollectionExtract(ST_MakeValid(
                   ST_SimplifyPreserveTopology(
                       ST_MakeValid(ST_GeomFromGeoJSON(%s)), %s)), 3))
         WHERE {where}
    """
    import json as _json
    with connection.cursor() as cur:
        for row, geom in zip(rows, geometries):
            if geom is None:
                continue
            gj = _json.dumps(geom)
            cur.execute(sql, [gj, gj, 0.002] + [row[f] for f in loader.unique_fields])
```

Add `from django.db import connection, transaction` at the top of `base.py`.

- [ ] **Step 7: Register the module**

In `external_data/loaders/__init__.py`, extend the import line:

```python
from external_data.loaders import food_security, seasonal  # noqa: E402,F401
```

- [ ] **Step 8: Migrate and run the tests**

```bash
docker compose exec web python manage.py makemigrations external_data
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, 20 tests.

- [ ] **Step 9: Commit**

```bash
git add external_data
git commit -m "Food security: IPC and Cadre Harmonise phases, with PostGIS geometry

Keeps two rules from build_foodsec verbatim - skip an area with no overall phase,
and read phase 3+ as the sum of 3, 4 and 5 - so what the map shows does not move.

source separates products that must not be conflated: official IPC, Cadre
Harmonise (Chad's), and FEWS NET's own IPC-compatible assessments."
```

---

### Task 5: Movement patterns — the model and the HDX / UNHCR parsers

**Files:**
- Modify: `external_data/models.py` (add `MovementPattern`)
- Create: `external_data/loaders/movement.py`
- Create: `external_data/tests/fixtures/hdx_idps_SDN_admin2.json`
- Create: `external_data/tests/test_movement.py`
- Modify: `external_data/loaders/__init__.py`

**Interfaces:**
- Consumes: `Loader`, `register`, `load` (Task 3).
- Produces: `external_data.models.MovementPattern`; `IdpLoader` (dataset `idps`, variant `admin2-overview`) and `RefugeeLoader` (dataset `refugees`).

- [ ] **Step 1: Record the fixture**

Save a real HDX `get_idps` response for SDN admin2 to
`external_data/tests/fixtures/hdx_idps_SDN_admin2.json` — a JSON list whose records
carry `admin1_name`, `admin2_name`, `admin2_code`, `population`,
`reference_period_start`, `reference_period_end`. Include at least two localities
across three reference periods so the watermark test has something to move.

- [ ] **Step 2: Write the failing tests**

`external_data/tests/test_movement.py`:

```python
"""IDP and refugee series, long format.

The watermark test is the one that proves the design's central claim: loading an
overlapping range must move high_water_date forward once and must not duplicate
the rows that were already there.
"""
import json
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from external_data.models import MovementPattern, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


class IdpLoaderTests(TestCase):
    def _load(self, name="hdx_idps_SDN_admin2.json"):
        call_command("load_external", "idps", str(FIXTURES / name), "--iso3", "SDN")

    def test_rows_are_long_format_one_per_place_per_date(self):
        self._load()
        self.assertGreater(MovementPattern.objects.count(), 0)
        row = MovementPattern.objects.first()
        self.assertEqual(row.metric, "idps")
        self.assertEqual(row.source, "hdx")
        self.assertEqual(row.unit, "individuals")
        self.assertIsNotNone(row.admin_pcode)

    def test_the_watermark_is_the_latest_data_date_not_today(self):
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        latest = max(MovementPattern.objects.values_list("date", flat=True))
        self.assertEqual(sync.high_water_date, latest)
        self.assertNotEqual(sync.high_water_date, date.today())

    def test_the_variant_distinguishes_admin_levels(self):
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        self.assertEqual(sync.variant, "admin2-overview")

    def test_reloading_overlapping_data_does_not_duplicate(self):
        self._load()
        first = MovementPattern.objects.count()
        self._load()
        self.assertEqual(MovementPattern.objects.count(), first)

    def test_the_watermark_never_rewinds(self):
        """A backfill of older data must not move the mark backwards."""
        self._load()
        sync = SourceSync.objects.get(source="hdx", dataset="idps", iso3="SDN")
        high = sync.high_water_date
        sync.high_water_date = date(2099, 1, 1)
        sync.save()
        self._load()
        sync.refresh_from_db()
        self.assertEqual(sync.high_water_date, date(2099, 1, 1))
        self.assertGreater(date(2099, 1, 1), high)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec web python manage.py test external_data.tests.test_movement -v 2`
Expected: FAIL — `ImportError: cannot import name 'MovementPattern'`

- [ ] **Step 4: Add the model**

Append to `external_data/models.py`:

```python
class MovementPattern(models.Model):
    """Displacement figures as the agencies themselves publish them.

    THIS IS NOT data_track.PopulationFigure, and the distinction is deliberate.
    That table holds numbers read out of UNHCR PDFs, each with the sentence that
    produced it. This one holds the same KINDS of quantity from the agencies' own
    APIs and from the office's Excel workbooks. They overlap and they disagree,
    because a situation report and an IOM-DTM round count different things on
    different dates.

    They stay apart. An analyst who wants both writes a UNION and chooses what
    that means. One merged table would produce plausible, wrong totals that nobody
    could trace back - the exact failure this project's evidence trail exists to
    prevent.
    """

    date = models.DateField(db_index=True)
    iso3 = models.CharField(max_length=3, db_index=True)
    admin_pcode = models.TextField(null=True, blank=True, help_text="Null for a national total")
    admin_level = models.IntegerField(null=True, blank=True)
    place_name = models.TextField(null=True, blank=True)

    metric = models.TextField(
        db_index=True, help_text="idps / refugees / returnees / asylum_seekers"
    )
    population_group = models.TextField(null=True, blank=True)
    value = models.BigIntegerField()
    unit = models.TextField(default="individuals", help_text="individuals / households")

    source = models.TextField(help_text="hdx / unhcr / excel")
    source_dataset = models.TextField(
        null=True, blank=True, help_text="iom-dtm / get_refugees / the workbook name"
    )
    # DTM reports a period, not an instant. Keeping both ends means a later reader
    # can tell a fortnight's round from a single day's count.
    reference_period_start = models.DateField(null=True, blank=True)
    reference_period_end = models.DateField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "movement_patterns"
        ordering = ["iso3", "metric", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "metric", "iso3", "admin_pcode", "date", "population_group"],
                name="uniq_movement_observation",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["metric", "iso3", "date"], name="idx_movement_series"),
        ]

    def __str__(self):
        return f"{self.date} {self.iso3} {self.metric} {self.value:,}"
```

- [ ] **Step 5: Write the parsers**

`external_data/loaders/movement.py`:

```python
"""HDX IOM-DTM and UNHCR stocks -> movement_patterns rows.

Two loaders, one table. They differ in exactly one interesting way: DTM publishes
dated rounds, so its watermark is a real high-water date and the next pull can ask
for everything after it. UNHCR's stock figures are annual, so its watermark barely
moves and `notes` carries the ceiling - otherwise a refresh that correctly returns
nothing looks like a broken one.
"""
from datetime import date, datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import MovementPattern


def _as_date(value):
    """'2025-12-31T00:00:00' or '2025-12-31' -> date. None stays None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


class _MovementLoader(Loader):
    model = MovementPattern
    unique_fields = [
        "source", "metric", "iso3", "admin_pcode", "date", "population_group",
    ]
    update_fields = [
        "admin_level", "place_name", "value", "unit", "source_dataset",
        "reference_period_start", "reference_period_end", "lat", "lon",
    ]

    def high_water(self, rows):
        return max((r["date"] for r in rows if r["date"]), default=None)


@register
class IdpLoader(_MovementLoader):
    """IOM-DTM cumulative IDP counts by admin2, via HDX HAPI `get_idps`."""

    dataset = "idps"
    source = "hdx"
    tool = "get_idps"

    def sync_key(self, iso3):
        # The variant matters: the same country's IDPs at admin1 are a different
        # thing to pull, and must not share this row's watermark.
        return {
            "source": self.source, "dataset": self.dataset,
            "iso3": iso3, "variant": "admin2-overview",
        }

    def parse(self, payload, iso3):
        records = payload if isinstance(payload, list) else payload.get("data", [])
        rows = []
        for r in records:
            end = _as_date(r.get("reference_period_end"))
            if end is None or r.get("population") is None:
                continue
            rows.append({
                "date": end,
                "iso3": iso3,
                "admin_pcode": r.get("admin2_code"),
                "admin_level": 2,
                "place_name": r.get("admin2_name"),
                "metric": "idps",
                "population_group": "idps",
                "value": int(r["population"]),
                "unit": "individuals",
                "source": self.source,
                "source_dataset": "iom-dtm",
                "reference_period_start": _as_date(r.get("reference_period_start")),
                "reference_period_end": end,
                "lat": None, "lon": None,
            })
        return rows


@register
class RefugeeLoader(_MovementLoader):
    """UNHCR registered refugee stocks by country of asylum, via HDX `get_refugees`."""

    dataset = "refugees"
    source = "unhcr"
    tool = "get_refugees"

    def parse(self, payload, iso3):
        records = payload if isinstance(payload, list) else payload.get("data", [])
        rows = []
        for r in records:
            year = r.get("year") or r.get("reference_period_end", "")[:4]
            if not year or r.get("population") is None:
                continue
            rows.append({
                "date": date(int(year), 7, 1),   # mid-year, as the existing series does
                "iso3": r.get("asylum_location_code") or iso3,
                "admin_pcode": None,
                "admin_level": 0,
                "place_name": r.get("asylum_location_name"),
                "metric": "refugees",
                "population_group": r.get("population_group") or "sudanese_refugees",
                "value": int(r["population"]),
                "unit": "individuals",
                "source": self.source,
                "source_dataset": "get_refugees",
                "reference_period_start": None,
                "reference_period_end": None,
                "lat": None, "lon": None,
            })
        return rows
```

- [ ] **Step 6: Register, migrate, run the tests**

In `external_data/loaders/__init__.py`:

```python
from external_data.loaders import food_security, movement, seasonal  # noqa: E402,F401
```

```bash
docker compose exec web python manage.py makemigrations external_data
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, 25 tests.

- [ ] **Step 7: Commit**

```bash
git add external_data
git commit -m "Movement patterns: DTM displacement and UNHCR stocks, long format

Kept separate from data_track's PDF-derived figures on purpose. They measure
overlapping quantities from different sources on different dates; merging them
would produce plausible, wrong totals nobody could trace back."
```

---

### Task 6: The Excel workbooks become a source

**Files:**
- Create: `external_data/loaders/excel.py`
- Create: `external_data/management/commands/load_workbooks.py`
- Create: `external_data/tests/test_excel.py`
- Modify: `external_data/loaders/__init__.py`

**Interfaces:**
- Consumes: `MovementPattern` (Task 5), the sheet-reading helpers already in `data_pipeline/steps/s07_xlsx.py`.
- Produces: `python manage.py load_workbooks` — reads both workbooks from `SOURCE_ROOT` and writes `movement_patterns` rows with `source='excel'`; `SourceSync` rows keyed `(excel, refugees, None, 'neighbours-workbook')` and `(excel, idps, SDN, 'sudan-idps-workbook')`, whose `params` carries the file `sha1` and mtime.

**Why this task exists:** `s07_xlsx.py` runs *after* s06 and rewrites
`refugee_camps.json`, merging a 2026 biweekly series into the file s06 just
produced. It also writes `idp_states.json`, which s06 never touches. If s06 alone
moved onto the database, step 7 would silently overwrite it on the next pipeline
run. These workbooks also hold the freshest movement data the project has — 2026
biweekly, against UNHCR's annual figures ending 2024.

- [ ] **Step 1: Write the failing test**

`external_data/tests/test_excel.py`:

```python
"""The two hand-maintained workbooks, into the same table as the APIs.

They are not a lesser source. The neighbours workbook carries a 2026 biweekly
refugee series; UNHCR's API stops at 2024. Whichever is newer, an analyst asking
'what is the latest figure for Chad' should get it from one query.
"""
import openpyxl
from django.test import TestCase, override_settings

from external_data.loaders.excel import parse_neighbours_sheet, parse_idp_states_sheet
from external_data.models import MovementPattern


class NeighboursWorkbookTests(TestCase):
    def test_a_sheet_becomes_one_row_per_country_per_date(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Country", "Data Date", "Sudanese refugees/asylum seekers"])
        ws.append(["Chad", "2026-02-15", 1_250_000])
        ws.append(["Egypt", "2026-02-15", 1_500_000])

        rows = parse_neighbours_sheet(ws)

        self.assertEqual(len(rows), 2)
        chad = next(r for r in rows if r["place_name"] == "Chad")
        self.assertEqual(chad["value"], 1_250_000)
        self.assertEqual(chad["metric"], "refugees")
        self.assertEqual(chad["source"], "excel")
        self.assertEqual(chad["iso3"], "TCD")

    def test_the_other_spelling_of_the_column_is_accepted(self):
        """Sheets use 'Sudanese refugees' and 'Sudanese refugees/asylum seekers'."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Country", "Data Date", "Sudanese refugees"])
        ws.append(["Chad", "2026-02-15", 1_250_000])
        self.assertEqual(len(parse_neighbours_sheet(ws)), 1)

    def test_a_row_with_no_figure_is_skipped_not_stored_as_zero(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Country", "Data Date", "Sudanese refugees"])
        ws.append(["Chad", "2026-02-15", None])
        self.assertEqual(parse_neighbours_sheet(ws), [])


class IdpStatesWorkbookTests(TestCase):
    def test_dated_column_headers_become_dated_rows(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["State", "Population (15 Jan 2026)", "Population (15 Feb 2026)"])
        ws.append(["North Darfur", 1_000, 1_200])

        rows = parse_idp_states_sheet(ws)

        self.assertEqual(len(rows), 2)
        self.assertEqual({r["value"] for r in rows}, {1_000, 1_200})
        self.assertTrue(all(r["metric"] == "idps" for r in rows))
        self.assertTrue(all(r["admin_level"] == 1 for r in rows))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python manage.py test external_data.tests.test_excel -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'external_data.loaders.excel'`

- [ ] **Step 3: Write the parsers**

`external_data/loaders/excel.py`. Lift the column-name handling and country-name
mapping from `data_pipeline/steps/s07_xlsx.py` (`_SDN_COL_NAMES`, `_COUNTRY_MAP`)
rather than reinventing them, and add an ISO3 mapping so rows key the same way as
the API-sourced ones:

```python
"""The two hand-maintained workbooks -> movement_patterns rows.

    neighbouring countries Pop movement data.xlsx   one sheet per reporting date
    Sudan IDPs.xlsx                                 admin1 states, dated headers

These carry the freshest movement figures the project holds: the neighbours
workbook runs to 2026 biweekly, where UNHCR's API stops at 2024. Reading them into
the same table as the API sources is what makes "the latest figure for Chad" a
single query rather than a judgement call.

Column names vary between sheets - both 'Sudanese refugees' and 'Sudanese
refugees/asylum seekers' appear - so the header is matched, never assumed by
position.
"""
import re
from datetime import date, datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import MovementPattern

SDN_COL_NAMES = {"Sudanese refugees/asylum seekers", "Sudanese refugees"}

COUNTRY_TO_ISO3 = {
    "car": "CAF", "central african republic": "CAF", "chad": "TCD",
    "egypt": "EGY", "ethiopia": "ETH", "libya": "LBY",
    "south sudan": "SSD", "uganda": "UGA", "sudan": "SDN",
}
CANONICAL_NAME = {
    "CAF": "Central African Republic", "TCD": "Chad", "EGY": "Egypt",
    "ETH": "Ethiopia", "LBY": "Libya", "SSD": "South Sudan",
    "UGA": "Uganda", "SDN": "Sudan",
}

# 'Population (15 Jan 2026)' -> 15 January 2026
_HEADER_DATE = re.compile(r"\((\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})\)")
_MONTHS = {m.lower()[:3]: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _header_date(text):
    m = _HEADER_DATE.search(str(text or ""))
    if not m:
        return None
    month = _MONTHS.get(m[2].lower()[:3])
    return date(int(m[3]), month, int(m[1])) if month else None


def parse_neighbours_sheet(ws):
    """One sheet of the neighbours workbook -> refugee rows."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(c or "").strip() for c in rows[0]]
    try:
        i_country = header.index("Country")
        i_date = header.index("Data Date")
    except ValueError:
        return []
    i_value = next((i for i, h in enumerate(header) if h in SDN_COL_NAMES), None)
    if i_value is None:
        return []

    out = []
    for row in rows[1:]:
        name = str(row[i_country] or "").strip()
        iso3 = COUNTRY_TO_ISO3.get(name.lower())
        value, when = row[i_value], _as_date(row[i_date])
        if not iso3 or value in (None, "") or when is None:
            continue
        out.append({
            "date": when, "iso3": iso3, "admin_pcode": None, "admin_level": 0,
            "place_name": CANONICAL_NAME[iso3], "metric": "refugees",
            "population_group": "sudanese_refugees", "value": int(value),
            "unit": "individuals", "source": "excel",
            "source_dataset": "neighbouring countries Pop movement data.xlsx",
            "reference_period_start": None, "reference_period_end": when,
            "lat": None, "lon": None,
        })
    return out


def parse_idp_states_sheet(ws):
    """Sudan IDPs.xlsx -> one row per state per dated column header."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = list(rows[0])
    dated = [(i, _header_date(h)) for i, h in enumerate(header)]
    dated = [(i, d) for i, d in dated if d]
    if not dated:
        return []

    out = []
    for row in rows[1:]:
        state = str(row[0] or "").strip()
        if not state:
            continue
        for i, when in dated:
            value = row[i] if i < len(row) else None
            if value in (None, ""):
                continue
            out.append({
                "date": when, "iso3": "SDN", "admin_pcode": None, "admin_level": 1,
                "place_name": state, "metric": "idps", "population_group": "idps",
                "value": int(value), "unit": "individuals", "source": "excel",
                "source_dataset": "Sudan IDPs.xlsx",
                "reference_period_start": None, "reference_period_end": when,
                "lat": None, "lon": None,
            })
    return out
```

- [ ] **Step 4: Write the `load_workbooks` command**

`external_data/management/commands/load_workbooks.py` opens both workbooks from
`settings.SOURCE_ROOT`, runs every sheet through the matching parser, upserts via
the same `bulk_create(update_conflicts=True, ...)` call the loaders use, and writes
two `SourceSync` rows whose `params` records each file's `sha1` and modification
time — the workbook equivalent of a date watermark. Raise `CommandError` if either
workbook is missing, naming the expected path.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose exec web python manage.py test external_data -v 2`
Expected: PASS, 31 tests.

- [ ] **Step 6: Commit**

```bash
git add external_data
git commit -m "The two Excel workbooks become a first-class movement source

s07 runs after s06 and rewrites refugee_camps.json; moving s06 alone onto the
database would have had step 7 silently overwrite it on the next run. These
workbooks also hold the freshest figures the project has - 2026 biweekly, against
UNHCR's annual data ending 2024."
```

---

### Task 7: `border_crossings` and `seed_external`

**Files:**
- Modify: `external_data/models.py` (add `BorderCrossing`)
- Create: `external_data/management/commands/seed_external.py`
- Create: `external_data/tests/test_seed.py`

**Interfaces:**
- Consumes: `SeasonalCalendar`, `MovementPattern` (Tasks 3, 5).
- Produces: `external_data.models.BorderCrossing` (fields `name`, `country`, `iso3`, `lon`, `lat`, `corridor`, `return_corridor`, `source`; unique on `name`); `python manage.py seed_external [--force]`.

- [ ] **Step 1: Write the failing test**

`external_data/tests/test_seed.py`:

```python
"""The three hand-typed dictionaries become rows, once.

seed_external is not part of a refresh. It runs once to move what is currently
Python source into the database, and after it the dictionaries are deleted from
s06_mcp_layers.py - leaving them in place would guarantee that one day the code
path nobody watches is the one serving the dashboard.
"""
from django.core.management import call_command
from django.test import TestCase

from external_data.models import BorderCrossing, MovementPattern, SeasonalCalendar


class SeedExternalTests(TestCase):
    def test_the_curated_crossings_are_seeded(self):
        call_command("seed_external")
        self.assertEqual(BorderCrossing.objects.count(), 9)
        adre = BorderCrossing.objects.get(name__startswith="El Geneina")
        self.assertEqual(adre.corridor, "sudan-chad")
        self.assertEqual(adre.return_corridor, "chad-sudan-return")
        self.assertEqual(adre.source, "curated")

    def test_the_sudan_calendar_is_seeded_as_curated_so_the_real_pull_can_replace_it(self):
        call_command("seed_external")
        bands = SeasonalCalendar.objects.filter(iso3="SDN", source="curated")
        self.assertEqual(bands.count(), 5)

    def test_refugee_totals_are_seeded_as_movement_rows(self):
        call_command("seed_external")
        rows = MovementPattern.objects.filter(source="unhcr", metric="refugees")
        self.assertEqual(rows.filter(iso3="TCD").count(), 3)      # 2022, 2023, 2024
        self.assertEqual(rows.get(iso3="TCD", date__year=2024).value, 1_109_357)

    def test_seeding_twice_changes_nothing(self):
        call_command("seed_external")
        call_command("seed_external")
        self.assertEqual(BorderCrossing.objects.count(), 9)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python manage.py test external_data.tests.test_seed -v 2`
Expected: FAIL — `ImportError: cannot import name 'BorderCrossing'`

- [ ] **Step 3: Add the model, write the command, migrate**

`BorderCrossing` mirrors the `CROSSINGS` list in `s06_mcp_layers.py:60-78`
one-for-one. `seed_external` copies all three dictionaries — `CROSSINGS`,
`SEASONAL` and `REF_COUNTRIES` — into the tables using `update_or_create`, so
re-running is a no-op. Seed the Sudan calendar with `source="curated"` so the real
FEWS NET pull in Task 8 can replace it by loading with `source="fewsnet"` and
deleting the curated rows.

```bash
docker compose exec web python manage.py makemigrations external_data
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, 35 tests.

- [ ] **Step 4: Commit**

```bash
git add external_data
git commit -m "seed_external: the three hardcoded dicts become rows"
```

---

### Task 8: Pull the real data

**Files:**
- Create: `data_pipeline/mcp_cache/seasonal/*.json`, `data_pipeline/mcp_cache/ipc/*.geojson`
- No code changes.

**This task is executed by the assistant on the host, not inside Docker.** It is the
first real use of the mechanism, and the order matters.

- [ ] **Step 1: Read the watermarks first**

```bash
docker compose exec web python manage.py external_status
```

- [ ] **Step 2: Pull FEWS NET seasons for every operational country**

One call per country: `get_seasons(country_code=...)` for `SD, TD, EG, ET, LY, SS, UG, CF`.
Save each to `data_pipeline/mcp_cache/seasonal/<ISO3>.json`. These are small and
may be pulled in parallel.

Expect uneven coverage and record it rather than retrying: verified 2026-09-09,
Libya returns a single placeholder "Annual" band and Egypt has crop seasons but no
lean season.

- [ ] **Step 3: Load them, then retire the curated Sudan rows**

```bash
for c in SDN TCD EGY ETH LBY SSD UGA CAF; do
  docker compose exec web python manage.py load_external seasonal_calendar \
      "data_pipeline/mcp_cache/seasonal/$c.json" --iso3 "$c"
done
docker compose exec web python manage.py shell -c \
  "from external_data.models import SeasonalCalendar as S; \
   print(S.objects.filter(iso3='SDN', source='curated').delete())"
```

- [ ] **Step 4: List IPC analyses and diff against what is held**

`list_analyses(country=...)` for `TD, SS, ET, CF` — small, cheap calls. Compare the
returned ids against `source_sync.known_ids`. **Pull only analyses dated 2023-01 or
later**; the timeline starts 15 April 2023 and earlier analyses cannot be displayed.

Egypt and Libya return `[]` — a real absence, verified 2026-09-09, not a failure.

- [ ] **Step 5: Pull the IPC areas, ONE COUNTRY AT A TIME**

`get_areas_by_analysis` per missing analysis. **Never two in parallel.** The
recorded failure is `-32000 Connection closed`, which took the IPC MCP server down
for the rest of that session. Save each to
`data_pipeline/mcp_cache/ipc/<ISO3>-<analysis_id>.geojson` and load it before
starting the next.

- [ ] **Step 6: Pull the missing AOI phases**

CAR (Vakaga) and Uganda (Kiryandongo) were never pulled, which is why they show
grey on the current AOI layer — a missing pull, not a confirmed absence. Uganda's
newest analysis is Karamoja-only and will not cover Kiryandongo; record that in
`source_sync.notes` rather than leaving it looking like a fault.

- [ ] **Step 7: Load the workbooks and record the source ceilings**

```bash
docker compose exec web python manage.py load_workbooks
docker compose exec web python manage.py external_status
```

Set `notes` on the HDX and UNHCR rows: HDX IDP admin2 ends 2025-12-31; UNHCR
refugee stocks are annual to 2024.

- [ ] **Step 8: Commit the caches**

```bash
git add data_pipeline/mcp_cache
git commit -m "MCP pulls: seasons for 8 countries, IPC analyses from 2023 for 4"
```

---

### Task 8b: The `community_insights` view

**Files:**
- Create: `external_data/migrations/000N_community_insights_view.py`
- Create: `external_data/tests/test_community_insights.py`

**Interfaces:**
- Consumes: `data_track`'s `narrative_tags` and `documents` tables.
- Produces: the SQL view `community_insights`, queried by `/api/community-insights/` in Task 9.

**Why a view and not a table:** the quotes already exist as `narrative_tags.snippet`.
A second copy would drift from the first the moment the corpus is re-parsed. The
user asked to see "Community Insights" in the database; this gives them exactly
that name, with zero duplication.

- [ ] **Step 1: Write the failing test**

`external_data/tests/test_community_insights.py`:

```python
"""The quotes, under the name the user asked for, without copying them.

A view rather than a table, so re-parsing the corpus can never leave two versions
of the same quote disagreeing with each other.
"""
from datetime import date

from django.db import connection
from django.test import TestCase

from data_track.models import Document, NarrativeTag


class CommunityInsightsViewTests(TestCase):
    def setUp(self):
        self.doc = Document.objects.create(
            file_name="UNHCR Chad Update.pdf", rel_path="chad/update.pdf",
            report_date=date(2026, 2, 15), family="chad_core",
        )

    def _rows(self):
        with connection.cursor() as cur:
            cur.execute("SELECT quote, source_document, dimension FROM community_insights")
            return cur.fetchall()

    def test_a_tagged_quote_appears_with_its_source_document(self):
        NarrativeTag.objects.create(
            document=self.doc, report_date=date(2026, 2, 15), dimension="hazard",
            tag="flooding", country="Chad", snippet="The wadi flooded the site.",
        )
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "The wadi flooded the site.")
        self.assertEqual(rows[0][1], "UNHCR Chad Update.pdf")
        self.assertEqual(rows[0][2], "hazard")

    def test_tags_with_no_quote_are_excluded(self):
        """A tag with no snippet is a classification, not an insight."""
        NarrativeTag.objects.create(
            document=self.doc, dimension="need", tag="food", snippet=None,
        )
        NarrativeTag.objects.create(
            document=self.doc, dimension="need", tag="water", snippet="",
        )
        self.assertEqual(self._rows(), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web python manage.py test external_data.tests.test_community_insights -v 2`
Expected: FAIL — `psycopg.errors.UndefinedTable: relation "community_insights" does not exist`

- [ ] **Step 3: Write the migration**

`external_data/migrations/000N_community_insights_view.py`:

```python
"""The Community Insights view: the quotes, named as the office names them.

A VIEW, NOT A TABLE. Every quote here already exists as narrative_tags.snippet.
Copying them into a second table would mean two versions of the same sentence,
diverging the first time the corpus is re-parsed. The view gives the name without
the duplication.

TWO THINGS THIS CONSTRAINS, both of which bite later and elsewhere:

  1. This migration MUST depend on data_track's latest migration. Without it a
     fresh `migrate` can order this before the tables exist and fail.
  2. PostgreSQL refuses to drop or alter a column that a view references.
     narrative_tags gained columns in 0002 and 0003 and will again - so any
     future migration touching that table must DROP this view first and recreate
     it after. There is no way to make Postgres forgive this; it can only be
     remembered.
"""
from django.db import migrations

CREATE = """
CREATE OR REPLACE VIEW community_insights AS
SELECT t.id,
       t.report_date,
       t.dimension,
       t.tag,
       t.country,
       t.area_id,
       t.area_name,
       t.area_level,
       t.snippet AS quote,
       d.file_name AS source_document,
       d.family,
       d.rel_path
FROM narrative_tags t
LEFT JOIN documents d ON d.id = t.document_id
WHERE t.snippet IS NOT NULL AND t.snippet <> '';
"""

DROP = "DROP VIEW IF EXISTS community_insights;"


class Migration(migrations.Migration):

    dependencies = [
        ("external_data", "000N_previous"),
        # Named explicitly so a fresh migrate can never order this first.
        ("data_track", "0003_narrativetag_area_level"),
    ]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
```

- [ ] **Step 4: Migrate and run the tests**

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, 37 tests.

- [ ] **Step 5: Commit**

```bash
git add external_data
git commit -m "community_insights: the quotes as a view, not a second copy

Named as the office names them, with no duplication - so a re-parse of the corpus
can never leave two versions of the same sentence disagreeing."
```

---

### Task 9: The read-only API

**Files:**
- Create: `external_data/urls.py`, `external_data/views.py`
- Create: `external_data/tests/test_api.py`
- Modify: `config/urls.py` (mount before `data_track`'s `api/`)
- Modify: `data_track/views.py:index` (list the new endpoints)

**Interfaces:**
- Consumes: every model, plus `status_rows()` from Task 2.
- Produces: `/api/seasonal/`, `/api/food-security/`, `/api/movement/`, `/api/community-insights/`, `/api/sync/`.

- [ ] **Step 1: Write the failing tests**

`external_data/tests/test_api.py`:

```python
"""The endpoints an analyst points Power BI at.

Same conventions as data_track/views.py: GET only, plain JsonResponse, filters as
query parameters, and a capped result set so one request can never dump a table.
"""
from datetime import date

from django.test import TestCase

from external_data.models import MovementPattern, SeasonalCalendar


class SeasonalApiTests(TestCase):
    def setUp(self):
        SeasonalCalendar.objects.create(
            iso3="TCD", country_name="Chad", source="fewsnet", label="Lean",
            season_type="Lean", purpose="NutritionIndicator",
            start_month=4, end_month=9, source_ref="TD",
        )
        SeasonalCalendar.objects.create(
            iso3="SDN", country_name="Sudan", source="fewsnet", label="Lean",
            season_type="Lean", purpose="NutritionIndicator",
            start_month=5, end_month=10, source_ref="SD",
        )

    def test_filtering_by_country_returns_only_that_country(self):
        data = self.client.get("/api/seasonal/?iso3=TCD").json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["start_month"], 4)

    def test_a_country_with_no_calendar_returns_an_empty_list_not_a_404(self):
        """Absence is a real answer here - Libya genuinely has almost nothing."""
        resp = self.client.get("/api/seasonal/?iso3=LBY")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])


class MovementApiTests(TestCase):
    def test_the_series_comes_back_in_date_order(self):
        for day, value in [(date(2024, 3, 1), 10), (date(2024, 1, 1), 5)]:
            MovementPattern.objects.create(
                date=day, iso3="SDN", metric="idps", value=value,
                source="hdx", population_group="idps", admin_pcode=f"X{value}",
            )
        rows = self.client.get("/api/movement/?iso3=SDN&metric=idps").json()["results"]
        self.assertEqual([r["value"] for r in rows], [5, 10])


class SyncApiTests(TestCase):
    def test_sync_is_reachable_and_lists_watermarks(self):
        resp = self.client.get("/api/sync/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec web python manage.py test external_data.tests.test_api -v 2`
Expected: FAIL — 404 on every endpoint.

- [ ] **Step 3: Write the views and URLs, mount them**

Follow `data_track/views.py` exactly: a module docstring listing the endpoints, one
function per endpoint, `_iso()` for dates, a `limit` capped at 5000. `/api/sync/`
returns `{"results": status_rows()}`, importing `status_rows` from the
`external_status` command module so the command and the API can never disagree.

In `config/urls.py`, mount `external_data.urls` **before** `data_track`'s `api/`
include, for the same reason `api/boundaries/` is already listed first.

- [ ] **Step 4: Run the tests and commit**

```bash
docker compose exec web python manage.py test external_data -v 2
git add external_data config/urls.py data_track/views.py
git commit -m "Read-only API over the external tables, and /api/sync/"
```

---

### Task 10: `s06` and `s07` read the database

**Files:**
- Modify: `data_pipeline/steps/s06_mcp_layers.py` (all six `build_*` functions)
- Modify: `data_pipeline/steps/s07_xlsx.py` (`build_refugees`, `build_idp_states`)
- Modify: `data_pipeline/steps/_build_aoi_ipc.py` (delete the pinned `TOOLRES` path)
- Create: `external_data/tests/test_pipeline_outputs.py`

**Interfaces:**
- Consumes: every model.
- Produces: unchanged output filenames; `seasonal.json` gains a country key —
  `{"source": ..., "countries": {"SDN": {"items": [...]}, ...}}`. Sub-project B
  consumes that shape.

- [ ] **Step 1: Write the equivalence test**

`external_data/tests/test_pipeline_outputs.py` asserts, against a database seeded
from the fixtures: the same number of IPC periods and the same feature count per
period; the same phase for every area title; locality names and values preserved in
`idp_localities.json`; country totals in `refugee_camps.json` including the 2026
Excel series; `idp_states.json` unchanged in state count.

**Do not assert a byte-identical rebuild.** It cannot pass:
`ST_SimplifyPreserveTopology` does not round coordinates the way `_simplify` does,
`admin_areas` centroids are not the name-matched geoBoundaries ones
`build_idp_localities` uses, and `seasonal.json` changes by design. An impossible
gate is one somebody skips.

- [ ] **Step 2: Capture the current output as the baseline**

```bash
docker compose exec web python manage.py run_pipeline --only s06,s07
cp -r "Community Centered Humanitarian Analysis Platform/dashboard/data" /tmp/data-before
```

- [ ] **Step 3: Swap each `build_*` to an ORM query**

Replace `json.loads((CACHE / "...").read_text())` with the equivalent queryset. Keep
every function's name, its `dump()` call and its printed line — `updater/views.py`
parses the `=== sNN_name ===` output for its progress bar, and `STEP_BANDS` keys on
the step file names.

`build_seasonal` gains a country loop and derives each band's colour from
`season_type`, since `SeasonalCalendar` has no colour column and FEWS NET publishes
none.

- [ ] **Step 4: Fix `_build_aoi_ipc.py`**

Delete `TOOLRES` — a hardcoded path pinned to a Claude session from June, which
silently reads stale data or nothing depending on what still exists on disk. Read
`FoodSecurityArea` instead.

- [ ] **Step 5: Rebuild and compare**

```bash
docker compose exec web python manage.py run_pipeline --only s06,s07
docker compose exec web python manage.py test external_data -v 2
```

- [ ] **Step 6: Commit**

```bash
git add data_pipeline external_data
git commit -m "s06 and s07 read the database; the MCP cache becomes staging

_build_aoi_ipc stops reading a tool-results path pinned to an expired session.
seasonal.json gains a country key so sub-project B is a frontend change alone."
```

---

### Task 11: The updater page shows real freshness

**Files:**
- Modify: `updater/views.py`, `updater/templates/updater/index.html`, `updater/static/updater/js/app.js`
- Modify: `MAINTENANCE.md` §4

- [ ] **Step 1: Replace file-mtime freshness with `source_sync`**

`updater/views.py` currently derives external-layer freshness from file
modification times. Point it at `status_rows()` instead, so the page shows, per
dataset × country: last pulled, latest data date held, and the `notes` that explain
a legitimate no-op.

- [ ] **Step 2: Rename the button**

"Rebuild external layers from latest cache" → "Rebuild external layers from the
database".

- [ ] **Step 3: Rewrite `MAINTENANCE.md` §4 around `external_status`**

The refresh workflow is now three steps, not two: read the watermarks, pull only
what they name, load. Document the IPC one-at-a-time rule and the 2023-01 floor
where someone will actually read them.

- [ ] **Step 4: Verify in a browser and commit**

```bash
docker compose up -d --build web
# open http://localhost:8000/updater/ and confirm per-dataset freshness renders
git add updater MAINTENANCE.md
git commit -m "Updater page reads source_sync; MAINTENANCE rewritten around external_status"
```

---

### Task 12: Final verification

- [ ] **Step 1: Full test run**

Run: `docker compose exec web python manage.py test -v 2`
Expected: all tests pass.

- [ ] **Step 2: Migrations apply cleanly on the live volume**

```bash
docker compose exec web python manage.py migrate
docker compose exec db psql -U sudan -d sudan_neighbouring_pop_movement -c "\dt"
```

Expected: `source_sync`, `seasonal_calendar`, `food_security`, `movement_patterns`,
`border_crossings`, plus the `community_insights` view in `\dv`.

- [ ] **Step 3: A real refresh round-trip**

`external_status` → pull only what it names → load → `external_status` again shows
the new high-water mark. Run against Chad, which has genuinely new data.

- [ ] **Step 4: The database answers a real question**

In DBeaver, join `food_security` to `admin_areas` and return Chad's ADM2 units at
phase 3+ for the November 2025 analysis. This is the goal-3 check, run with the
tool the user actually uses.

- [ ] **Step 5: The dashboard still works**

Open the dashboard, toggle every external layer, drag the timeline across its full
range, and confirm the seasonal panel still renders for Sudan.

- [ ] **Step 6: Commit any fixes and update the spec status**

Change the spec header to `**Status:** implemented`.

---

## Note on the `community_insights` view

The view is created by `RunSQL` in a migration whose `dependencies` **must** include
`data_track`'s latest migration, or a fresh `migrate` fails on ordering.

More importantly: PostgreSQL refuses to drop or alter a column that a view
references. `narrative_tags` already gained columns in `0002` and `0003` and will
again, so **any future migration touching `narrative_tags` must drop this view
first and recreate it after**. This is written here and in the spec because the
failure surfaces months later, inside someone else's unrelated migration, where
nothing points back to this decision.
