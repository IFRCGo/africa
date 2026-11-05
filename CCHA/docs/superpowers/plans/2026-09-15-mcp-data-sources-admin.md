# MCP Data Sources Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Model Context Protocol (MCP)" section to the Django admin that lists every external data source with its last pull time, gives each API-backed row a button that fetches fresh data into the database, and offers a separate optional button to rebuild the dashboard layers.

**Architecture:** A new `external_data/fetchers/` package mirrors the existing `loaders/` package: a fetcher knows where a payload comes from, a loader knows what it means, neither knows the other. A fetcher plans one or more `Call`s; the `refresh_external` management command executes them serially, saves each raw response under `mcp_cache/`, and hands it to the existing loader — so all four loader guarantees still apply unchanged. A new `mcp` app holds a `PullJob` table (the attempt record), a claim lock, and the admin section, whose list is a proxy model over the existing `SourceSync` table.

**Tech Stack:** Django 5.0.6, PostgreSQL 16 + PostGIS, `requests` 2.32.3, Django admin. Everything runs in Docker.

**Spec:** `docs/superpowers/specs/2026-09-15-mcp-data-sources-admin-design.md`

## Global Constraints

- **Everything runs in Docker.** There is no Django environment on the host. Every command in this plan is run as `docker compose exec web python manage.py <command>` from the repository root. Tests: `docker compose exec web python manage.py test <app> -v 2`.
- **On Windows/Git Bash, prefix `docker compose exec` with `MSYS_NO_PATHCONV=1`** or paths in arguments get mangled.
- **Never pull two IPC countries in parallel.** Recorded incident: the connection closed and the server stayed down for the rest of the session. Calls are executed serially, never gathered or threaded.
- **Settings use `os.environ.get(X) or default`** for the new keys, not `get(X, default)`. An empty value in `.env` must fall back rather than be treated as set-but-empty.
- **`/work` is mounted read-only.** Anything written goes under `/app`.
- **No loader is modified by this plan.** The four guarantees in `external_data/loaders/base.py` are used, not changed.
- **`source_sync.last_pulled_at` and `high_water_date` are written only by `loaders.base.load`,** inside its successful transaction. Nothing in this plan writes them directly. A failed pull must never look fresh.
- **Secrets never reach a log.** `IPC_API_KEY` and `HDX_API_TOKEN` are redacted from every message and log line before writing.
- **`CRISIS_START` already exists** at `config/settings.py:270` (`"2023-04-15"`) and `data_pipeline/common.py:31` (`date(2023, 4, 15)`). Reuse it; do not define a third.
- **`ISO3_TO_ISO2` already exists** at `external_data/loaders/seasonal.py:26`. Import it; do not define a second map.
- **Test style:** Django `TestCase`, fixtures under `external_data/tests/fixtures/`, no network access in any test.

## File Structure

**Created:**
- `external_data/fetchers/__init__.py` — registry, keyed on `(source, dataset, variant)`
- `external_data/fetchers/base.py` — `Fetcher` contract, `Call`, HTTP helper, redaction, payload saving
- `external_data/fetchers/fewsnet.py` — seasons and IPC phases (no key)
- `external_data/fetchers/hdx.py` — IDPs and refugees, with pagination (`HDX_API_TOKEN`)
- `external_data/fetchers/ipc.py` — analyses diff, period from title, skip list (`IPC_API_KEY`)
- `external_data/management/commands/refresh_external.py` — fetch, save, load, record
- `external_data/migrations/0012_source_sync_skipped_ids.py` — the new column
- `external_data/migrations/0013_seed_skipped_ids.py` — transcribed exclusions
- `mcp/` — new Django app: `models.py` (`PullJob`, `DataSource` proxy), `locks.py`, `admin.py`, `views.py`, `templates/mcp/job.html`
- Tests under `external_data/tests/` and `mcp/tests/`

**Modified:**
- `requirements.txt`, `env.example`, `docker-compose.yml`, `config/settings.py`, `CLAUDE.md`

---

### Task 1: Dependencies, settings and keys

**Files:**
- Modify: `Community Centered Humanitarian Analysis Platform/requirements.txt`
- Modify: `Community Centered Humanitarian Analysis Platform/config/settings.py`
- Modify: `env.example`
- Modify: `docker-compose.yml`
- Test: `Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetch_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.IPC_API_KEY: str`, `settings.HDX_API_TOKEN: str` — empty string when unset. `requests` importable inside the web container.

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_fetch_settings.py`:

```python
"""The two API keys, and the empty-env trap they must not fall into."""
from django.conf import settings
from django.test import TestCase


class KeySettingsTests(TestCase):
    def test_both_keys_are_defined_as_strings(self):
        """Absent means empty string, never None - callers test truthiness."""
        self.assertIsInstance(settings.IPC_API_KEY, str)
        self.assertIsInstance(settings.HDX_API_TOKEN, str)

    def test_requests_is_installed(self):
        import requests
        self.assertTrue(hasattr(requests, "get"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetch_settings -v 2`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'IPC_API_KEY'`

- [ ] **Step 3: Add the dependency**

Append to `requirements.txt`:

```
requests==2.32.3         # the fetchers' HTTP client (external_data/fetchers/)
```

- [ ] **Step 4: Add the settings**

In `config/settings.py`, immediately after the `MCP_CACHE_DIR` line (line 50):

```python
# The two keys the fetchers need. `get(X) or ""`, NOT `get(X, "")`: an empty
# value in .env must fall back to "not set" rather than be sent as a blank key,
# which HAPI answers with a 403 instead of a comprehensible refusal.
#
# Absent is empty string, never None: the admin tests truthiness to decide
# whether a row's Pull button is live, and None would work by accident today
# and break the moment somebody writes `len(...)`.
IPC_API_KEY = os.environ.get("IPC_API_KEY") or ""
HDX_API_TOKEN = os.environ.get("HDX_API_TOKEN") or ""
```

- [ ] **Step 5: Add them to env.example**

Append to `env.example`:

```
# --------------------------------------------------------------------------
# Keys for the MCP data-source pull buttons (Admin -> Model Context Protocol).
# Without them those rows still show their freshness; their buttons are
# disabled and say which key is missing.
#
# IPC_API_KEY   covers the ipc and ch rows.  Request one from ipcinfo.org.
# HDX_API_TOKEN covers the hdx AND unhcr rows - the UNHCR figures are served
#               through HDX HAPI, so there is no separate UNHCR key. Encode
#               yours at https://hapi.humdata.org/docs#/Util/get_encoded_identifier_api_v1_encode_identifier_get
# FEWS NET needs no key at all.
# --------------------------------------------------------------------------
IPC_API_KEY=
HDX_API_TOKEN=
```

- [ ] **Step 6: Pass them into the container**

In `docker-compose.yml`, in the `web` service's `environment:` block, after the `LLM_API_KEY` line:

```yaml
      # Keys for the MCP pull buttons. Unset is fine: those buttons are then
      # disabled and say so. See env.example for where each one comes from.
      IPC_API_KEY: ${IPC_API_KEY:-}
      HDX_API_TOKEN: ${HDX_API_TOKEN:-}
```

- [ ] **Step 7: Rebuild and run the test**

Run:
```bash
docker compose up -d --build web
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetch_settings -v 2
```
Expected: PASS, 2 tests.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt "Community Centered Humanitarian Analysis Platform/config/settings.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetch_settings.py" \
  env.example docker-compose.yml
git commit -m "external_data: add requests and the two fetcher API keys"
```

---

### Task 2: The fetcher contract and registry

**Files:**
- Create: `external_data/fetchers/__init__.py`
- Create: `external_data/fetchers/base.py`
- Test: `external_data/tests/test_fetcher_base.py`

**Interfaces:**
- Consumes: `settings.IPC_API_KEY`, `settings.HDX_API_TOKEN` (Task 1).
- Produces:
  - `Call(url: str, params: dict, cache_path: Path, loader_dataset: str, context: dict)` — a frozen dataclass.
  - `class Fetcher` with class attributes `source`, `dataset`, `variant`, `tool`, `requires: tuple[str, ...]`, and method `plan(self, sync) -> Iterator[Call]`.
  - `register(cls)` — class decorator; fills `FETCHERS[(source, dataset, variant)]`.
  - `FETCHERS: dict[tuple[str, str, str], type[Fetcher]]`
  - `fetcher_for(source, dataset, variant) -> type[Fetcher] | None`
  - `missing_keys(fetcher_cls) -> list[str]`
  - `http_get_json(url, params, timeout=60) -> dict | list` — raises `FetchError`.
  - `save_payload(cache_path, payload) -> Path`
  - `redact(text) -> str`
  - `class FetchError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_fetcher_base.py`:

```python
"""The fetcher contract: registry keys, key checks, redaction, saving.

No test here touches the network. `http_get_json` is exercised with requests.get
patched, because the thing being tested is our handling, not theirs.
"""
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import FETCHERS, register
from external_data.fetchers.base import (Call, FetchError, Fetcher, fetcher_for,
                                         http_get_json, missing_keys, redact,
                                         save_payload)


class _Fake(Fetcher):
    source = "testsource"
    dataset = "testdataset"
    variant = "testvariant"
    tool = "get_test"
    requires = ("IPC_API_KEY",)

    def plan(self, sync):
        yield Call(url="https://example.org/x", params={"a": 1},
                   cache_path=Path("test/x.json"), loader_dataset="testdataset",
                   context={})


class RegistryTests(TestCase):
    def test_register_keys_on_source_dataset_and_variant(self):
        """Variant is in the key: fewsnet/food_security/'fewsnet-phases' is a
        different pull from anything keyed on source and dataset alone."""
        register(_Fake)
        self.addCleanup(FETCHERS.pop, ("testsource", "testdataset", "testvariant"), None)
        self.assertIs(fetcher_for("testsource", "testdataset", "testvariant"), _Fake)

    def test_an_unregistered_row_resolves_to_none(self):
        self.assertIsNone(fetcher_for("excel", "idps", "sudan-idps-workbook"))


class KeyCheckTests(TestCase):
    @override_settings(IPC_API_KEY="")
    def test_a_missing_key_is_reported_by_name(self):
        self.assertEqual(missing_keys(_Fake), ["IPC_API_KEY"])

    @override_settings(IPC_API_KEY="abc123")
    def test_a_present_key_leaves_nothing_missing(self):
        self.assertEqual(missing_keys(_Fake), [])


@override_settings(IPC_API_KEY="SUPERSECRET", HDX_API_TOKEN="TOKENVALUE")
class RedactionTests(TestCase):
    def test_key_values_are_removed_from_text(self):
        """HAPI carries its token in the query string, so it lands in exception
        text. Anything written to a job log goes through here first."""
        text = "GET https://hapi.humdata.org/x?app_identifier=TOKENVALUE failed"
        self.assertNotIn("TOKENVALUE", redact(text))
        self.assertIn("<redacted>", redact(text))

    def test_both_keys_are_covered(self):
        self.assertNotIn("SUPERSECRET", redact("key=SUPERSECRET"))

    def test_an_empty_key_does_not_redact_everything(self):
        """A blank key must not turn every character into <redacted>."""
        with override_settings(IPC_API_KEY="", HDX_API_TOKEN=""):
            self.assertEqual(redact("hello"), "hello")


class HttpTests(TestCase):
    def test_json_is_returned_on_success(self):
        with patch("external_data.fetchers.base.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"ok": True}
            get.return_value.raise_for_status.return_value = None
            self.assertEqual(http_get_json("https://example.org", {"a": 1}), {"ok": True})

    def test_an_http_error_becomes_a_fetcherror_with_the_key_redacted(self):
        import requests
        with override_settings(HDX_API_TOKEN="TOKENVALUE"), \
             patch("external_data.fetchers.base.requests.get") as get:
            get.side_effect = requests.RequestException("boom app_identifier=TOKENVALUE")
            with self.assertRaises(FetchError) as caught:
                http_get_json("https://example.org", {})
        self.assertNotIn("TOKENVALUE", str(caught.exception))


class SaveTests(TestCase):
    def test_payload_is_written_under_the_cache_dir_and_parents_created(self):
        path = save_payload(Path("testsource/deep/x.json"), {"hello": "world"})
        self.addCleanup(path.unlink, True)
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"hello": "world"})

    def test_the_path_is_relative_to_mcp_cache_dir(self):
        from django.conf import settings
        path = save_payload(Path("testsource/y.json"), [])
        self.addCleanup(path.unlink, True)
        self.assertEqual(path.parent.parent, Path(settings.MCP_CACHE_DIR))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_base -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'external_data.fetchers'`

- [ ] **Step 3: Write the registry**

Create `external_data/fetchers/__init__.py`:

```python
"""The fetcher registry. Adding a source is adding a file, not editing a command.

Deliberately the same shape as `external_data/loaders/__init__.py`, and for the
same reason: the two packages are halves of one idea. A loader knows what a
payload MEANS; a fetcher knows where it COMES FROM. Neither imports the other.

THE KEY INCLUDES `variant`, which the loader registry's does not. A loader is
chosen by dataset alone because `fewsnet_phases` is one way of reading one shape
of JSON. A fetch is chosen by all three because `hdx/idps/SDN` is an
admin2-overview request and `fewsnet/food_security/ETH` sits under variant
'fewsnet-phases' while its loader's dataset is 'fewsnet_phases'. Keying on
(source, dataset) alone silently misses that row.
"""
FETCHERS = {}


def register(cls):
    """Class decorator: put a Fetcher subclass into the registry under its key."""
    FETCHERS[(cls.source, cls.dataset, cls.variant)] = cls
    return cls


def fetcher_for(source, dataset, variant=""):
    """The fetcher for one source_sync row, or None if that row has no API."""
    return FETCHERS.get((source, dataset, variant or ""))


# Importing the modules is what populates FETCHERS. Kept at the bottom because
# each module imports `register` from this one.
from external_data.fetchers import fewsnet, hdx, ipc  # noqa: E402,F401
```

**Note for the implementer:** that last import line will fail until Tasks 3, 6 and 8 create those modules. Create all three now as empty files containing only a docstring, so the package imports; each task then fills its own in.

```bash
printf '"""FEWS NET fetchers. Filled in by Task 3."""\n' > external_data/fetchers/fewsnet.py
printf '"""HDX HAPI fetchers. Filled in by Task 6."""\n' > external_data/fetchers/hdx.py
printf '"""IPC fetcher. Filled in by Task 8."""\n' > external_data/fetchers/ipc.py
```

- [ ] **Step 4: Write the contract**

Create `external_data/fetchers/base.py`:

```python
"""What every fetcher guarantees, and the helpers that enforce it.

A fetcher turns one source_sync row into a sequence of Calls. It does not make
them - the runner does, serially - and it never touches the database. That split
is what keeps "never pull two IPC countries in parallel" enforceable in one place
instead of in five.

Four guarantees, matching the loaders' four:

  saved before loaded  the raw response is written to mcp_cache/ and only then
                       parsed, so a payload that breaks a loader is still on disk
  one call at a time   plan() is a generator; the runner consumes it serially and
                       never gathers, maps or threads it
  keyed, or refused    a fetcher whose `requires` is unmet calls nothing at all
  empty is a failure   an empty payload reaches the loader and trips EmptyPayload,
                       and no watermark moves. That guarantee is the loaders', and
                       this package exists partly to avoid weakening it.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import requests
from django.conf import settings

# Every setting whose value must never appear in a log line or an error message.
SECRET_SETTINGS = ("IPC_API_KEY", "HDX_API_TOKEN")


class FetchError(Exception):
    """An upstream call failed. The message is already redacted."""


@dataclass(frozen=True)
class Call:
    """One upstream request, and what to do with what comes back.

    `cache_path` is RELATIVE to MCP_CACHE_DIR, so a fetcher never has to know
    where the cache lives. `loader_dataset` names the loader that parses the
    result, which is not always the row's own dataset - see the registry note.
    """

    url: str
    params: dict
    cache_path: Path
    loader_dataset: str
    context: dict = field(default_factory=dict)


class Fetcher:
    """Subclass, set the class attributes, and implement plan()."""

    source = ""        # 'ipc'            - matches source_sync.source
    dataset = ""       # 'food_security'  - matches source_sync.dataset
    variant = ""       # 'admin2-overview'- matches source_sync.variant
    tool = ""          # the MCP tool this reproduces, for the record
    requires = ()      # ('IPC_API_KEY',) - checked before anything is called

    def plan(self, sync):
        """Yield one Call per upstream request this pull needs.

        `sync` is the SourceSync row. Read-only here: a fetcher decides WHAT to
        ask for, and the runner is what records that it asked.
        """
        raise NotImplementedError

    def params_record(self):
        """What to write into source_sync.params after a successful pull.

        The column is documented as "the last call made, for reproducibility" and
        is empty on every row today, because nothing has ever written it. The
        default records the tool; a fetcher with interesting parameters overrides.
        """
        return {"tool": self.tool, "fetcher": type(self).__name__}


def missing_keys(fetcher_cls):
    """Which of this fetcher's required settings are unset. Empty list means go."""
    return [name for name in fetcher_cls.requires if not getattr(settings, name, "")]


def redact(text):
    """Remove every secret value from text.

    HAPI takes its token as a QUERY PARAMETER, so it appears in the URL, which
    appears in requests' own exception messages, which would otherwise appear in
    a job log that anyone with admin access can read. Redaction happens here, on
    the way out, rather than being remembered at each call site.
    """
    out = str(text)
    for name in SECRET_SETTINGS:
        value = getattr(settings, name, "")
        if value:                      # an empty key must not match everything
            out = out.replace(value, "<redacted>")
    return out


def http_get_json(url, params, timeout=60):
    """GET and decode, or raise FetchError with the secrets already removed."""
    try:
        response = requests.get(url, params=params, timeout=timeout,
                                headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(redact(f"{url}: {exc}")) from None
    except ValueError as exc:
        # A 200 that is not JSON - an HTML error page, typically. Saying which
        # is worth more than "expecting value: line 1 column 1".
        raise FetchError(redact(f"{url}: response was not JSON ({exc})")) from None


def save_payload(cache_path, payload):
    """Write the raw response under MCP_CACHE_DIR and return the full path.

    Saved BEFORE the loader sees it, on purpose: a payload that breaks a parser
    is then still on disk to look at, which is the whole reason this project
    keeps a cache at all.
    """
    path = Path(settings.MCP_CACHE_DIR) / cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
```

- [ ] **Step 5: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_base -v 2`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/fetchers" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetcher_base.py"
git commit -m "external_data: add the fetcher contract and registry"
```

---

### Task 3: The FEWS NET fetchers

The unkeyed, single-call case — the first one demonstrable end to end.

**Files:**
- Modify: `external_data/fetchers/fewsnet.py`
- Test: `external_data/tests/test_fetcher_fewsnet.py`

**Interfaces:**
- Consumes: `Call`, `Fetcher`, `register` (Task 2); `ISO3_TO_ISO2` from `external_data/loaders/seasonal.py`.
- Produces: `SeasonsFetcher` (key `("fewsnet", "seasonal_calendar", "")`), `PhasesFetcher` (key `("fewsnet", "food_security", "fewsnet-phases")`, `loader_dataset="fewsnet_phases"`).

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_fetcher_fewsnet.py`:

```python
"""FEWS NET: no key, one call, and the ISO2 trap.

source_sync keys countries on ISO3. FEWS NET's API takes ISO 3166-1 alpha-2. The
map already exists in the seasonal loader and is imported, not re-typed.
"""
from pathlib import Path

from django.test import TestCase

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync


class SeasonsFetcherTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")
        self.fetcher = fetcher_for("fewsnet", "seasonal_calendar", "")()

    def test_it_is_registered_for_the_row(self):
        self.assertIsNotNone(fetcher_for("fewsnet", "seasonal_calendar", ""))

    def test_it_needs_no_key(self):
        self.assertEqual(missing_keys(type(self.fetcher)), [])

    def test_one_call_is_planned(self):
        self.assertEqual(len(list(self.fetcher.plan(self.sync))), 1)

    def test_the_call_asks_fdw_for_the_iso2_country(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.url, "https://fdw.fews.net/api/season/")
        self.assertEqual(call.params["country_code"], "TD")
        self.assertEqual(call.params["page_size"], 50)

    def test_the_payload_is_cached_per_country(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.cache_path, Path("fewsnet_seasons/TCD.json"))

    def test_it_names_the_seasonal_calendar_loader(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.loader_dataset, "seasonal_calendar")

    def test_an_unmapped_country_raises_rather_than_guessing(self):
        """A two-letter code is not derivable from a three-letter one. Guessing
        would send a valid-looking request for the wrong country."""
        self.sync.iso3 = "ZZZ"
        with self.assertRaises(KeyError):
            list(self.fetcher.plan(self.sync))


class PhasesFetcherTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="food_security", iso3="ETH",
            variant="fewsnet-phases")
        self.fetcher = fetcher_for("fewsnet", "food_security", "fewsnet-phases")()

    def test_the_variant_is_part_of_the_registry_key(self):
        """Without the variant in the key this row resolves to nothing, because
        its dataset is 'food_security' while its loader's is 'fewsnet_phases'."""
        self.assertIsNotNone(fetcher_for("fewsnet", "food_security", "fewsnet-phases"))
        self.assertIsNone(fetcher_for("fewsnet", "food_security", ""))

    def test_it_names_the_fewsnet_phases_loader_not_its_own_dataset(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.loader_dataset, "fewsnet_phases")

    def test_it_asks_for_phases_from_the_crisis_start(self):
        call = next(iter(self.fetcher.plan(self.sync)))
        self.assertEqual(call.url, "https://fdw.fews.net/api/ipcphase/")
        self.assertEqual(call.params["country_code"], "ET")
        self.assertEqual(call.params["start_date"], "2023-04-15")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_fewsnet -v 2`
Expected: FAIL — `TypeError: 'NoneType' object is not callable` (nothing registered yet).

- [ ] **Step 3: Write the fetchers**

Replace `external_data/fetchers/fewsnet.py` with:

```python
"""FEWS NET -> seasonal calendars and IPC-compatible phases.

The easy source: no key, one call each, and a published API that filters by
country. Both fetchers exist mainly to prove the contract before the keyed and
paginated ones arrive.

ISO2, NOT ISO3. `source_sync` keys countries on ISO3 and FEWS NET's
`country_code` is ISO 3166-1 alpha-2. The map is imported from the seasonal
loader rather than re-typed, because two copies of a country table is how one of
them silently goes stale.
"""
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher
from external_data.loaders.seasonal import ISO3_TO_ISO2

BASE = "https://fdw.fews.net"


def _iso2(iso3):
    """The two-letter code, or KeyError naming the country we cannot place.

    Deliberately not `.get()`: a missing country must stop the pull. Falling back
    to the ISO3 sends a valid-looking request that FEWS NET answers with an empty
    result set, which the loader then reports as an empty payload - a confusing
    way to learn that a country is simply not in the map.
    """
    try:
        return ISO3_TO_ISO2[iso3]
    except KeyError:
        raise KeyError(
            f"{iso3} is not in ISO3_TO_ISO2 (external_data/loaders/seasonal.py). "
            "Add it there rather than guessing a two-letter code here."
        ) from None


@register
class SeasonsFetcher(Fetcher):
    """`get_seasons` - the lean, harvest and rainy bands for one country."""

    source = "fewsnet"
    dataset = "seasonal_calendar"
    variant = ""
    tool = "get_seasons"
    requires = ()

    def plan(self, sync):
        # page_size 50 matches the MCP tool's own default. One country's seasons
        # are a few dozen rows even counting the historical unit versions the
        # loader discards, so this is one page in practice.
        yield Call(
            url=f"{BASE}/api/season/",
            params={"country_code": _iso2(sync.iso3), "page_size": 50},
            cache_path=Path("fewsnet_seasons") / f"{sync.iso3}.json",
            loader_dataset="seasonal_calendar",
            context={},
        )


@register
class PhasesFetcher(Fetcher):
    """`get_ipc_phases` - FEWS NET's own assessment, where IPC has published none.

    NOTE THE THREE NAMES, which are all different and all correct: the row's
    dataset is 'food_security', its variant is 'fewsnet-phases', and the loader
    that parses the payload is registered under 'fewsnet_phases'. The variant is
    why this fetcher is findable at all, and loader_dataset is why the right
    parser is used.
    """

    source = "fewsnet"
    dataset = "food_security"
    variant = "fewsnet-phases"
    tool = "get_ipc_phases"
    requires = ()

    def plan(self, sync):
        yield Call(
            url=f"{BASE}/api/ipcphase/",
            params={"country_code": _iso2(sync.iso3),
                    "start_date": settings.CRISIS_START},
            cache_path=Path("fewsnet_phases") / f"{sync.iso3}.json",
            loader_dataset="fewsnet_phases",
            context={},
        )
```

- [ ] **Step 4: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_fewsnet -v 2`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/fetchers/fewsnet.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetcher_fewsnet.py"
git commit -m "external_data: fetch FEWS NET seasons and phases"
```

---

### Task 4: The `mcp` app, `PullJob`, and the claim lock

**Files:**
- Create: `mcp/__init__.py`, `mcp/apps.py`, `mcp/models.py`, `mcp/locks.py`, `mcp/migrations/__init__.py`, `mcp/tests/__init__.py`
- Modify: `config/settings.py` (INSTALLED_APPS)
- Test: `mcp/tests/test_locks.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `mcp.models.PullJob` with fields `kind, source, dataset, iso3, variant, status, requested_by, requested_at, started_at, finished_at, rows_written, payload_path, message, log_path` and constants `ACTIVE = ("queued", "running")`.
  - `mcp.models.DataSource` — proxy over `external_data.SourceSync`.
  - `mcp.locks.claim(kind, *, source=None, dataset=None, iso3=None, variant="", user=None) -> PullJob`
  - `mcp.locks.JobBusy(Exception)`
  - `mcp.locks.STALE_AFTER` — `timedelta(minutes=30)`

- [ ] **Step 1: Write the failing test**

Create `mcp/tests/__init__.py` (empty) and `mcp/tests/test_locks.py`:

```python
"""Claiming a job, and the rule that stops the recorded IPC crash repeating.

The lock is tested through its effects rather than with threads. What must hold
is: while a source has work in flight, nothing else may claim that source; a
rebuild excludes everything; and the database refuses a duplicate even if some
future caller forgets to go through claim().
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from mcp.locks import JobBusy, STALE_AFTER, claim
from mcp.models import PullJob


class ClaimTests(TestCase):
    def test_a_claim_returns_a_queued_job(self):
        job = claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.source, "fewsnet")
        self.assertIsNotNone(job.requested_at)

    def test_a_second_claim_on_a_busy_source_is_refused(self):
        """Two tabs, two countries, two clicks - the way IPC went down before."""
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        with self.assertRaises(JobBusy):
            claim("pull", source="ipc", dataset="food_security", iso3="TCD")

    def test_a_different_source_is_allowed_at_the_same_time(self):
        claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        job = claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        self.assertEqual(job.status, "queued")

    def test_a_finished_job_does_not_hold_the_source(self):
        first = claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        first.status = "succeeded"
        first.save(update_fields=["status"])
        self.assertIsNotNone(claim("pull", source="ipc", dataset="food_security", iso3="TCD"))

    def test_a_rebuild_is_refused_while_any_pull_runs(self):
        """A rebuild reads the tables a pull is writing."""
        claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")
        with self.assertRaises(JobBusy):
            claim("rebuild")

    def test_a_pull_is_refused_while_a_rebuild_runs(self):
        claim("rebuild")
        with self.assertRaises(JobBusy):
            claim("pull", source="fewsnet", dataset="seasonal_calendar", iso3="TCD")

    def test_a_second_rebuild_is_refused(self):
        claim("rebuild")
        with self.assertRaises(JobBusy):
            claim("rebuild")

    def test_the_refusal_names_the_job_holding_the_source(self):
        held = claim("pull", source="ipc", dataset="food_security", iso3="SDN")
        with self.assertRaises(JobBusy) as caught:
            claim("pull", source="ipc", dataset="food_security", iso3="TCD")
        self.assertIn(str(held.id), str(caught.exception))


class ConstraintTests(TestCase):
    def test_the_database_itself_refuses_two_active_jobs_for_one_source(self):
        """claim() is the front door; the constraint is the lock on it. A future
        caller that inserts directly must not be able to break the rule."""
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="running")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                   iso3="TCD", status="queued")


class StaleTests(TestCase):
    def test_a_long_running_job_is_reported_stale(self):
        job = PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                     iso3="SDN", status="running")
        PullJob.objects.filter(pk=job.pk).update(
            started_at=timezone.now() - STALE_AFTER - timedelta(minutes=1))
        self.assertTrue(PullJob.objects.get(pk=job.pk).is_stale)

    def test_a_fresh_job_is_not_stale(self):
        job = PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                                     iso3="SDN", status="running",
                                     started_at=timezone.now())
        self.assertFalse(job.is_stale)
```

- [ ] **Step 2: Create the app skeleton**

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py startapp mcp
```

Then replace `mcp/apps.py` with:

```python
from django.apps import AppConfig


class McpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp"
    # The sidebar heading. The office calls these sources "the MCPs", and this
    # section is where they are pulled from, so it is named for them - with the
    # caveat that the pulls themselves are plain HTTPS. See §15 of the spec.
    verbose_name = "Model Context Protocol (MCP)"
```

Add `"mcp",` to `INSTALLED_APPS` in `config/settings.py`, after `"external_data",`:

```python
    "external_data",                 # IPC, FEWS NET, DTM, UNHCR + their freshness
    "mcp",                           # pulling those sources, and the job record
```

- [ ] **Step 3: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp.tests.test_locks -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp.locks'`

- [ ] **Step 4: Write the models**

Replace `mcp/models.py` with:

```python
"""The attempt record, and the list the admin section draws.

THE DIVISION THIS TABLE EXISTS FOR. `source_sync` records what is HELD: it is
advanced only by a successful load, inside that load's transaction. `PullJob`
records what was ATTEMPTED, including everything that failed and why. Keeping
them apart is what lets the freshness table still be trusted once a button
exists - a pull that fails must never look like fresh data.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from external_data.models import SourceSync

# The statuses that mean "this job holds its source".
ACTIVE = ("queued", "running")

STATUS_CHOICES = [
    ("queued", "queued"), ("running", "running"),
    ("succeeded", "succeeded"), ("failed", "failed"),
]


class DataSource(SourceSync):
    """The freshness table, listed under the MCP heading.

    A PROXY, NOT A COPY. Django's admin groups the sidebar by app, so a separate
    heading needs a model in this app - but the facts belong to `source_sync` and
    duplicating them into a second table is how two tables start disagreeing
    about which is right. This model has no table of its own.
    """

    class Meta:
        proxy = True
        verbose_name = "data source"
        verbose_name_plural = "data sources"


class PullJob(models.Model):
    """One press of a button, and everything that came of it."""

    kind = models.CharField(
        max_length=16, default="pull",
        help_text="pull (one source_sync row) / rebuild (the dashboard layers)",
    )
    # Null for a rebuild, which belongs to no single row.
    source = models.TextField(null=True, blank=True)
    dataset = models.TextField(null=True, blank=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True)
    variant = models.TextField(default="", blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    rows_written = models.IntegerField(default=0)
    payload_path = models.TextField(
        null=True, blank=True, help_text="Where the raw response was saved"
    )
    message = models.TextField(
        default="", blank=True, help_text="The error, or a one-line summary. Redacted."
    )
    # The full output goes to a FILE, not a column - the same choice
    # insights/admin.py makes for extraction jobs, and for the same reasons: the
    # job page can tail it while the command is still writing, and a 50,000-line
    # IPC run does not become a 50,000-line database row.
    log_path = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "mcp_pull_job"
        ordering = ["-requested_at"]
        constraints = [
            # The database's own guarantee, behind claim(). One active job per
            # source, whatever route the insert came in by.
            models.UniqueConstraint(
                fields=["source"], name="uniq_active_job_per_source",
                condition=Q(status__in=ACTIVE),
            ),
            # `source` is null on a rebuild and Postgres treats nulls as
            # distinct, so the constraint above cannot cover rebuilds. This one
            # does: at most one active rebuild, ever.
            models.UniqueConstraint(
                fields=["kind"], name="uniq_active_rebuild",
                condition=Q(kind="rebuild", status__in=ACTIVE),
            ),
        ]
        indexes = [
            models.Index(fields=["source", "status"], name="idx_pull_job_source_status"),
        ]

    @property
    def is_stale(self):
        """Running far longer than any real pull takes - probably a dead process.

        A container restart leaves a job at 'running' with nothing behind it. The
        row is then holding its source against every future press, so the list
        shows this and offers a reset - the same affordance, and the same reason,
        as reset_stuck_job in insights/admin.py.
        """
        from mcp.locks import STALE_AFTER
        if self.status not in ACTIVE:
            return False
        started = self.started_at or self.requested_at
        return bool(started and timezone.now() - started > STALE_AFTER)

    @property
    def target(self):
        """'ipc/food_security SDN', or 'dashboard layers' for a rebuild."""
        if self.kind == "rebuild":
            return "dashboard layers"
        where = self.iso3 or "global"
        return f"{self.source}/{self.dataset} {where} {self.variant}".strip()

    def __str__(self):
        return f"job {self.id}: {self.target} ({self.status})"
```

- [ ] **Step 5: Write the lock**

Create `mcp/locks.py`:

```python
"""Claiming a job, which is the only way one may be created.

WHY NOT `select_for_update()`. It locks rows that EXIST. When no ipc job is
active there is no row to lock, so two simultaneous requests both find nothing
and both insert - which is precisely the case the lock is for. A PostgreSQL
advisory lock is held on a name rather than a row, so it serialises the empty
case too, and the transaction releases it however it ends.

ONE GLOBAL CLAIM LOCK, not one per source. Claiming is a query and an insert -
microseconds - while the job it creates may run for minutes. Serialising the
claims costs nothing and removes the race between "may a rebuild start?" and
"may a pull start?", which per-source locks could not see.
"""
from datetime import timedelta

from django.db import connection, transaction

from mcp.models import ACTIVE, PullJob

# Any stable pair. Namespace 8123 is this application's; 1 is "the claim lock".
CLAIM_LOCK = (8123, 1)

# Longer than any real pull. Sudan's IDP series, the biggest, is 57 pages.
STALE_AFTER = timedelta(minutes=30)


class JobBusy(Exception):
    """Something is already running that this job would collide with."""


def claim(kind, *, source=None, dataset=None, iso3=None, variant="", user=None):
    """Create a queued job, or raise JobBusy naming what is in the way."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", list(CLAIM_LOCK))

        active = PullJob.objects.filter(status__in=ACTIVE)

        if kind == "rebuild":
            # A rebuild reads every table a pull writes, so it waits for all of
            # them rather than for one source.
            blocker = active.first()
            if blocker:
                raise JobBusy(
                    f"job {blocker.id} ({blocker.target}) is {blocker.status}. "
                    "A rebuild waits for every pull to finish."
                )
        else:
            blocker = active.filter(source=source).first() or active.filter(kind="rebuild").first()
            if blocker:
                raise JobBusy(
                    f"job {blocker.id} ({blocker.target}) is {blocker.status}. "
                    f"Wait for it, or reset it if it is stuck."
                )

        return PullJob.objects.create(
            kind=kind, source=source, dataset=dataset, iso3=iso3,
            variant=variant or "", requested_by=user, status="queued",
        )
```

- [ ] **Step 6: Make and run the migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py makemigrations mcp
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py migrate mcp
```
Expected: creates `mcp/migrations/0001_initial.py` with `PullJob` and the `DataSource` proxy, then applies it.

- [ ] **Step 7: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp.tests.test_locks -v 2`
Expected: PASS, 11 tests.

- [ ] **Step 8: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/mcp" \
  "Community Centered Humanitarian Analysis Platform/config/settings.py"
git commit -m "mcp: add the PullJob record and the claim lock"
```

---

### Task 5: `manage.py refresh_external`

**Files:**
- Create: `external_data/management/commands/refresh_external.py`
- Test: `external_data/tests/test_refresh_external.py`

**Interfaces:**
- Consumes: `fetcher_for`, `missing_keys`, `http_get_json`, `save_payload`, `redact`, `FetchError` (Task 2); `LOADERS`, `load`, `EmptyPayload` (existing); `PullJob` (Task 4).
- Produces: the command `refresh_external <source> <dataset> [--iso3] [--variant] [--job N] [--dry-run]`.

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_refresh_external.py`:

```python
"""The runner: fetch, save, load, record - and what it must not do on failure.

The HTTP layer is patched at external_data.fetchers.base.http_get_json, which is
the single door every fetcher goes through. Nothing here touches the network.
"""
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from external_data.models import SeasonalCalendar, SourceSync
from mcp.models import PullJob

FIXTURES = Path(__file__).parent / "fixtures"


def _seasons_payload():
    return json.loads((FIXTURES / "fewsnet_seasons_TCD.json").read_text(encoding="utf-8"))


class SuccessTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")

    def test_a_successful_pull_writes_rows_and_advances_the_watermark(self):
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        self.sync.refresh_from_db()
        self.assertIsNotNone(self.sync.last_pulled_at)

    def test_the_raw_payload_is_saved_before_it_is_loaded(self):
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        saved = Path(settings.MCP_CACHE_DIR) / "fewsnet_seasons" / "TCD.json"
        self.addCleanup(saved.unlink, True)
        self.assertTrue(saved.is_file())

    def test_the_job_records_the_row_count_and_finishes(self):
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar",
                         "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.rows_written, 6)
        self.assertIsNotNone(job.finished_at)

    def test_params_are_written_back_onto_the_row(self):
        """source_sync.params is empty on every row today. After a pull it says
        what was asked, which is what its help text has always promised."""
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        self.sync.refresh_from_db()
        self.assertEqual(self.sync.params["tool"], "get_seasons")


class FailureTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")

    def test_an_empty_payload_fails_the_job_and_leaves_the_watermark_alone(self):
        """THE REGRESSION THIS DESIGN TURNS ON. An MCP or API error serialised as
        [] must never be recorded as a successful, up-to-date pull."""
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json", return_value=[]):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.sync.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNone(self.sync.last_pulled_at)
        self.assertEqual(self.sync.row_count, 0)

    def test_an_http_failure_is_recorded_on_the_job(self):
        from external_data.fetchers.base import FetchError
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json",
                   side_effect=FetchError("503 Service Unavailable")):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("503", job.message)

    def test_a_secret_never_reaches_the_job_message(self):
        """HAPI puts its token in the query string, so it lands in exception text.
        Without this test, "never echoed into a log" is a wish."""
        from django.test import override_settings
        from external_data.fetchers.base import FetchError, redact
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with override_settings(HDX_API_TOKEN="TOKENVALUE"), \
             patch("external_data.fetchers.base.http_get_json",
                   side_effect=FetchError(redact("failed app_identifier=TOKENVALUE"))):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertNotIn("TOKENVALUE", job.message)

    def test_a_row_with_no_fetcher_is_refused_by_name(self):
        SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                  variant="sudan-idps-workbook")
        with self.assertRaises(CommandError) as caught:
            call_command("refresh_external", "excel", "idps", "--iso3", "SDN",
                         "--variant", "sudan-idps-workbook")
        self.assertIn("no fetcher", str(caught.exception).lower())

    def test_a_missing_key_is_refused_before_anything_is_called(self):
        from django.test import override_settings
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        with override_settings(IPC_API_KEY=""), \
             patch("external_data.fetchers.base.http_get_json") as http:
            with self.assertRaises(CommandError) as caught:
                call_command("refresh_external", "ipc", "food_security", "--iso3", "SDN")
        http.assert_not_called()
        self.assertIn("IPC_API_KEY", str(caught.exception))


class DryRunTests(TestCase):
    def test_dry_run_writes_no_rows(self):
        SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                  iso3="TCD", variant="")
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar",
                         "--iso3", "TCD", "--dry-run")
        self.assertEqual(SeasonalCalendar.objects.count(), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_refresh_external -v 2`
Expected: FAIL — `CommandError: Unknown command: 'refresh_external'`

- [ ] **Step 3: Write the command**

Create `external_data/management/commands/refresh_external.py`:

```python
"""`python manage.py refresh_external <source> <dataset> --iso3 XXX`

Fetch, save, then load - the rule CLAUDE.md states for the agent, kept by the
application. The command is the feature and the admin button is a caller, which
is how this gets tested and how it would be scheduled if that is ever wanted.

    docker compose exec web python manage.py refresh_external fewsnet \\
        seasonal_calendar --iso3 TCD

ONE CALL AT A TIME. The fetcher's plan() is a generator and it is consumed with a
plain for-loop. Do not gather, map or thread it: two IPC countries in parallel
closed the connection and took that server down for a whole session.
"""
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import (FetchError, http_get_json, missing_keys,
                                         redact, save_payload)
from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load
from external_data.models import SourceSync


class Command(BaseCommand):
    help = "Fetch one external source into the database, and record the attempt."

    def add_arguments(self, parser):
        parser.add_argument("source", help="e.g. fewsnet")
        parser.add_argument("dataset", help="e.g. seasonal_calendar")
        parser.add_argument("--iso3", default=None)
        parser.add_argument("--variant", default="")
        parser.add_argument("--job", type=int, default=None,
                            help="PullJob id to record progress against")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **options):
        from mcp.models import PullJob

        job = PullJob.objects.filter(pk=options["job"]).first() if options["job"] else None
        if job:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.save(update_fields=["status", "started_at"])

        try:
            written = self._run(options)
        except Exception as exc:
            # Every failure route ends here, so there is exactly one place that
            # writes a failure onto the job - and exactly one place that has to
            # remember to redact.
            self._finish(job, "failed", message=redact(exc))
            raise CommandError(redact(exc)) from None

        self._finish(job, "succeeded", rows=written,
                     message=f"wrote {written} rows")
        self.stdout.write(f"wrote {written} rows")
        return None

    def _run(self, options):
        source, dataset = options["source"], options["dataset"]
        variant = options["variant"] or ""

        sync = SourceSync.objects.filter(
            source=source, dataset=dataset, iso3=options["iso3"], variant=variant,
        ).first()
        if sync is None:
            raise CommandError(
                f"no source_sync row for {source}/{dataset} "
                f"{options['iso3'] or 'global'} '{variant}'"
            )

        fetcher_cls = fetcher_for(source, dataset, variant)
        if fetcher_cls is None:
            raise CommandError(
                f"no fetcher for {source}/{dataset} '{variant}'. This source is "
                "file-based - load it with its own command."
            )

        absent = missing_keys(fetcher_cls)
        if absent:
            raise CommandError(
                f"{', '.join(absent)} is not set. Add it to .env and restart the "
                "web container; nothing was called."
            )

        fetcher = fetcher_cls()
        written = 0
        failures = []

        for call in fetcher.plan(sync):
            self.stdout.write(f"GET {call.url}")
            payload = http_get_json(call.url, call.params)
            path = save_payload(call.cache_path, payload)
            self.stdout.write(f"  saved {path}")

            loader = LOADERS[call.loader_dataset]()
            try:
                # ONE CALL IS ONE TRANSACTION, not one job. Rolling six good IPC
                # analyses back because the seventh was an empty projection
                # update would throw away 8-15 MB of successful work per failure
                # and let one bad analysis poison a whole country.
                result = load(loader, payload, sync.iso3,
                              dry_run=options["dry_run"], context=call.context)
            except EmptyPayload as exc:
                failures.append((call, exc))
                self.stdout.write(self.style.WARNING(f"  empty: {exc}"))
                self._note_empty(fetcher, sync, call)
                continue

            written += result.written
            self.stdout.write(f"  loaded {result.written} rows")

        if failures and not written:
            raise EmptyPayload(
                f"{len(failures)} call(s) produced no rows and none succeeded: "
                f"{failures[0][1]}"
            )
        if failures:
            raise EmptyPayload(
                f"{written} rows loaded, but {len(failures)} call(s) were empty: "
                f"{failures[0][1]}"
            )

        if not options["dry_run"]:
            SourceSync.objects.filter(pk=sync.pk).update(params=fetcher.params_record())
        return written

    def _note_empty(self, fetcher, sync, call):
        """Let a fetcher record that one of its Calls came back empty.

        IPC uses this to add an analysis id to skipped_ids, so a projection
        update that publishes no geometry is not re-fetched on every press. Other
        fetchers do not implement it and nothing happens.
        """
        hook = getattr(fetcher, "note_empty", None)
        if hook:
            hook(sync, call)

    def _finish(self, job, status, rows=0, message=""):
        if not job:
            return
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.rows_written = rows
        job.message = str(message)[:4000]
        job.save(update_fields=["status", "finished_at", "rows_written", "message"])
```

- [ ] **Step 4: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_refresh_external -v 2`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/management/commands/refresh_external.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_refresh_external.py"
git commit -m "external_data: add refresh_external, the fetch-save-load runner"
```

---

### Task 6: The HDX fetchers, and pagination

**Files:**
- Modify: `external_data/fetchers/hdx.py`
- Test: `external_data/tests/test_fetcher_hdx.py`

**Interfaces:**
- Consumes: `Call`, `Fetcher`, `register`, `http_get_json` (Task 2).
- Produces: `IdpsFetcher` (key `("hdx", "idps", "admin2-overview")`), `RefugeesFetcher` (key `("unhcr", "refugees", "")`), and `fetch_all_pages(url, params) -> dict` — the paginating helper.

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_fetcher_hdx.py`:

```python
"""HDX HAPI: the keyed source, and the one that paginates.

HAPI's `limit` defaults to 100. Sudan's IDP series is 5,686 rows - 57 pages. A
fetcher that takes the first page loads 100 rows over the top of 5,686 and calls
it a refresh.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.fetchers.hdx import PAGE_SIZE, fetch_all_pages
from external_data.models import SourceSync


class RegistrationTests(TestCase):
    def test_idps_is_registered_under_its_variant(self):
        self.assertIsNotNone(fetcher_for("hdx", "idps", "admin2-overview"))

    def test_refugees_is_registered_under_source_unhcr(self):
        """The figures are UNHCR's and the row says so; the API is HDX HAPI's."""
        self.assertIsNotNone(fetcher_for("unhcr", "refugees", ""))

    @override_settings(HDX_API_TOKEN="")
    def test_both_need_the_hdx_token_even_the_unhcr_one(self):
        self.assertEqual(missing_keys(fetcher_for("hdx", "idps", "admin2-overview")),
                         ["HDX_API_TOKEN"])
        self.assertEqual(missing_keys(fetcher_for("unhcr", "refugees", "")),
                         ["HDX_API_TOKEN"])


@override_settings(HDX_API_TOKEN="TESTTOKEN")
class CallShapeTests(TestCase):
    def test_idps_asks_for_admin_level_2(self):
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.url,
                         "https://hapi.humdata.org/api/v1/affected-people/idps")
        self.assertEqual(call.params["location_code"], "SDN")
        self.assertEqual(call.params["admin_level"], 2)
        self.assertEqual(call.cache_path, Path("hdx_idps/SDN-admin2-overview.json"))

    def test_refugees_asks_for_sudanese_origin(self):
        """RefugeeLoader files these as population_group 'sudanese_refugees'. The
        request must actually be for people originating in Sudan, or the label
        is a lie about someone else's figures."""
        sync = SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD")
        call = next(iter(fetcher_for("unhcr", "refugees", "")().plan(sync)))
        self.assertEqual(call.params["origin_location_code"], "SDN")
        self.assertEqual(call.params["asylum_location_code"], "TCD")

    def test_the_token_travels_with_the_request(self):
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview")
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.params["app_identifier"], "TESTTOKEN")


class PaginationTests(TestCase):
    def test_pages_are_followed_until_a_short_one(self):
        pages = [
            {"data": [{"n": i} for i in range(PAGE_SIZE)]},
            {"data": [{"n": i} for i in range(PAGE_SIZE)]},
            {"data": [{"n": 1}, {"n": 2}]},
        ]
        with patch("external_data.fetchers.hdx.http_get_json", side_effect=pages) as http:
            result = fetch_all_pages("https://example.org", {"a": 1})
        self.assertEqual(len(result["data"]), PAGE_SIZE * 2 + 2)
        self.assertEqual(http.call_count, 3)

    def test_the_offset_advances_by_a_page_each_time(self):
        pages = [{"data": [{"n": i} for i in range(PAGE_SIZE)]}, {"data": []}]
        with patch("external_data.fetchers.hdx.http_get_json", side_effect=pages) as http:
            fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_args_list[0].args[1]["offset"], 0)
        self.assertEqual(http.call_args_list[1].args[1]["offset"], PAGE_SIZE)

    def test_one_short_page_is_a_single_call(self):
        with patch("external_data.fetchers.hdx.http_get_json",
                   return_value={"data": [{"n": 1}]}) as http:
            result = fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_count, 1)
        self.assertEqual(len(result["data"]), 1)

    def test_an_empty_first_page_returns_empty_rather_than_looping(self):
        """Empty is the loader's business - it must reach EmptyPayload, not spin."""
        with patch("external_data.fetchers.hdx.http_get_json",
                   return_value={"data": []}) as http:
            result = fetch_all_pages("https://example.org", {})
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["data"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_hdx -v 2`
Expected: FAIL — `ImportError: cannot import name 'PAGE_SIZE' from 'external_data.fetchers.hdx'`

- [ ] **Step 3: Write the fetchers**

Replace `external_data/fetchers/hdx.py` with:

```python
"""HDX HAPI -> IDP localities and refugee stocks.

ONE KEY COVERS TWO SOURCES. `hdx/idps` is obviously HAPI's. `unhcr/refugees` is
too: RefugeeLoader records source='unhcr' because the figures are UNHCR's, but the
tool behind it is HAPI's `get_refugees`. So both need HDX_API_TOKEN and there is
no UNHCR key at all.

PAGINATION IS NOT OPTIONAL HERE. HAPI's `limit` defaults to 100 and Sudan's IDP
series is 5,686 rows. A fetcher that takes the first page would write 100 rows
over the top of 5,686 and report a successful refresh.
"""
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, http_get_json

BASE = "https://hapi.humdata.org/api/v1"

# HAPI's documented maximum for these endpoints. Larger is rejected; smaller
# just means more round trips.
PAGE_SIZE = 1000


def fetch_all_pages(url, params):
    """Follow `offset` until a short page, and return one combined payload.

    The saved file then has the shape the loader expects - a single {"data": [...]}
    - as though it had been one call. The loader has no idea pagination happened,
    which is the point: paging is a property of the API, not of the data.
    """
    rows = []
    offset = 0
    while True:
        page = http_get_json(url, {**params, "limit": PAGE_SIZE, "offset": offset})
        batch = page.get("data", []) if isinstance(page, dict) else (page or [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            # A short page is the last page. An EMPTY first page also stops here
            # and returns empty, which is correct: emptiness is the loader's to
            # judge, and EmptyPayload is where it gets judged.
            return {"data": rows}
        offset += PAGE_SIZE


class _HapiFetcher(Fetcher):
    """Shared: the token, and the paginating call."""

    requires = ("HDX_API_TOKEN",)

    def _params(self, extra):
        return {**extra, "app_identifier": settings.HDX_API_TOKEN,
                "output_format": "json"}


@register
class IdpsFetcher(_HapiFetcher):
    """`get_idps` at admin 2 - the locality series the dashboard draws."""

    source = "hdx"
    dataset = "idps"
    variant = "admin2-overview"
    tool = "get_idps"

    def plan(self, sync):
        yield Call(
            url=f"{BASE}/affected-people/idps",
            params=self._params({"location_code": sync.iso3, "admin_level": 2}),
            cache_path=Path("hdx_idps") / f"{sync.iso3}-admin2-overview.json",
            loader_dataset="idps",
            context={},
        )

    def params_record(self):
        return {"tool": self.tool, "admin_level": 2, "paginated": True}


@register
class RefugeesFetcher(_HapiFetcher):
    """`get_refugees` - Sudanese refugees, by country of asylum.

    ORIGIN IS PINNED TO SUDAN, and that is not a detail. RefugeeLoader files every
    row it writes under population_group 'sudanese_refugees'. A request without
    origin_location_code returns every refugee in the asylum country, whoever they
    are, and the loader would label them all Sudanese.
    """

    source = "unhcr"
    dataset = "refugees"
    variant = ""
    tool = "get_refugees"

    def plan(self, sync):
        yield Call(
            url=f"{BASE}/affected-people/refugees",
            params=self._params({"origin_location_code": "SDN",
                                 "asylum_location_code": sync.iso3}),
            cache_path=Path("hdx_refugees") / f"{sync.iso3}.json",
            loader_dataset="refugees",
            context={},
        )

    def params_record(self):
        return {"tool": self.tool, "origin_location_code": "SDN", "paginated": True}
```

- [ ] **Step 4: Route the HAPI calls through the pager**

In `external_data/management/commands/refresh_external.py`, the runner calls `http_get_json` for every Call. HAPI needs the pager instead. Give `Call` an opt-in rather than special-casing HDX in the runner.

In `external_data/fetchers/base.py`, add a field to `Call`, after `context`:

```python
    # HAPI pages at 100 by default and Sudan's IDP series is 5,686 rows, so some
    # Calls must be followed to the end. The flag lives on the Call rather than
    # in the runner because whether an endpoint paginates is the fetcher's
    # knowledge, not the runner's.
    paginated: bool = False
```

In `external_data/fetchers/hdx.py`, add `paginated=True` to both `Call(...)` constructions.

In `refresh_external.py`, replace the fetch line inside the loop:

```python
            self.stdout.write(f"GET {call.url}")
            if call.paginated:
                from external_data.fetchers.hdx import fetch_all_pages
                payload = fetch_all_pages(call.url, call.params)
            else:
                payload = http_get_json(call.url, call.params)
```

- [ ] **Step 5: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_hdx external_data.tests.test_refresh_external -v 2`
Expected: PASS, all tests from both modules.

- [ ] **Step 6: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/fetchers" \
  "Community Centered Humanitarian Analysis Platform/external_data/management/commands/refresh_external.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetcher_hdx.py"
git commit -m "external_data: fetch HDX IDPs and refugees, following every page"
```

---

### Task 7: `source_sync.skipped_ids`

**Files:**
- Modify: `external_data/models.py`
- Create: `external_data/migrations/0012_source_sync_skipped_ids.py` (generated)
- Create: `external_data/migrations/0013_seed_skipped_ids.py` (hand-written)
- Test: `external_data/tests/test_skipped_ids.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SourceSync.skipped_ids: list[dict]` — entries `{"id": "87143421", "reason": "..."}`.

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/test_skipped_ids.py`:

```python
"""The column that stops a button undoing a curator's judgement.

known_ids means HELD. The notes column already records analyses a person
deliberately left out, and those ids are in neither list - so a naive diff
re-pulls every one of them, and the known-empty ones fail forever.
"""
from django.test import TestCase

from external_data.models import SourceSync


class ColumnTests(TestCase):
    def test_a_new_row_starts_with_an_empty_skip_list(self):
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        self.assertEqual(sync.skipped_ids, [])

    def test_entries_carry_an_id_and_a_reason(self):
        """A skip with no reason is indistinguishable from a bug six months on."""
        sync = SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="CAF",
            skipped_ids=[{"id": "87143421", "reason": "publishes no current-period geometry"}],
        )
        sync.refresh_from_db()
        self.assertEqual(sync.skipped_ids[0]["id"], "87143421")
        self.assertIn("geometry", sync.skipped_ids[0]["reason"])


class SeedTests(TestCase):
    """The four exclusions transcribed out of the notes by migration 0013.

    These rows exist in the real database, created by seed_external. The test
    reads whatever is there rather than creating its own, because what is being
    checked is that the data migration found and marked the right rows.
    """

    def test_caf_skips_the_analysis_with_no_geometry(self):
        sync = SourceSync.objects.filter(source="ipc", dataset="food_security",
                                         iso3="CAF").first()
        if sync is None:
            self.skipTest("no CAF row in this database")
        self.assertIn("87143421", [s["id"] for s in sync.skipped_ids])

    def test_ssd_skips_its_projection_update(self):
        sync = SourceSync.objects.filter(source="ipc", dataset="food_security",
                                         iso3="SSD").first()
        if sync is None:
            self.skipTest("no SSD row in this database")
        self.assertIn("81832747", [s["id"] for s in sync.skipped_ids])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_skipped_ids -v 2`
Expected: FAIL — `TypeError: SourceSync() got unexpected keyword arguments: 'skipped_ids'`

- [ ] **Step 3: Add the field**

In `external_data/models.py`, inside `SourceSync`, immediately after the `known_ids` field:

```python
    # WHAT known_ids CANNOT SAY. known_ids means "held": it is filled from rows
    # that loaded. It has no way to record that a person looked at an analysis
    # and decided it does not belong - Chad's Mar 2024 analysis "counts a
    # different denominator and would not compose with the rest" - or that a
    # source publishes an id with no data behind it at all.
    #
    # Without this column, an automated diff of "published minus held" re-pulls
    # every deliberate exclusion and retries every empty analysis on every press,
    # forever. Entries are {"id": "...", "reason": "..."}; the reason is not
    # decoration, it is the difference between a decision and a mystery.
    skipped_ids = models.JSONField(
        default=list, blank=True,
        help_text="Identities deliberately NOT held: [{id, reason}]. See known_ids.",
    )
```

- [ ] **Step 4: Generate the schema migration**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py makemigrations external_data --name source_sync_skipped_ids`
Expected: creates `external_data/migrations/0012_source_sync_skipped_ids.py`.

- [ ] **Step 5: Write the data migration**

Create `external_data/migrations/0013_seed_skipped_ids.py`:

```python
"""Move four curatorial exclusions out of prose and into a column.

Each one is already written in `notes`, where a person can read it and a fetcher
cannot. The reasons below are copied from those notes rather than paraphrased, so
the two say the same thing.

THIS IS A TRANSCRIPTION OF SOMEBODY'S JUDGEMENT. If a reading here is wrong, a
real analysis stays out of the database and nothing complains - which is why the
admin list shows each skipped id with its reason, and why removing one is a
one-line shell command.
"""
from django.db import migrations

SKIPS = {
    # (source, iso3): [(analysis_id, reason), ...]
    ("ch", "TCD"): [
        ("58836358", "Mar 2023 analysis predates the crisis start (notes, 2026-09-09)"),
        ("72156898", "Mar 2024 displaced-population analysis counts a different "
                     "denominator and would not compose with the rest (notes)"),
    ],
    ("ipc", "CAF"): [
        ("87143421", "May 2026 analysis publishes no current-period geometry - "
                     "an empty FeatureCollection (notes)"),
    ],
    ("ipc", "SSD"): [
        ("81832747", "Apr 2025 Proj Update publishes no current-period geometry - "
                     "it is a projection update, not a new current-situation "
                     "analysis (notes)"),
    ],
}


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    for (source, iso3), entries in SKIPS.items():
        for sync in SourceSync.objects.filter(source=source, dataset="food_security",
                                              iso3=iso3):
            held = {s.get("id") for s in (sync.skipped_ids or [])}
            sync.skipped_ids = (sync.skipped_ids or []) + [
                {"id": aid, "reason": reason}
                for aid, reason in entries if aid not in held
            ]
            sync.save(update_fields=["skipped_ids"])


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
```

**Note for the implementer:** the two Chad analysis ids above are placeholders for ids the notes describe but do not number — the notes name them by date ("Mar 2023", "the Mar 2024 displaced-population analysis"), not by id. **Before running this migration**, get the real ids with one call and substitute them:

```bash
# In a Claude Code session on the host, one country only, never two in parallel:
#   mcp__ipc__list_analyses(country="TD", type="A")
# Match the Mar 2023 and Mar 2024 titles, and put their ids above.
```
If that call cannot be made, delete the `("ch", "TCD")` entry rather than guessing ids — a wrong id skips a real analysis silently. The CAF and SSD ids are confirmed from `source_sync.notes` and from `mcp_cache/ipc/analyses-CAF.json`.

- [ ] **Step 6: Apply and test**

Run:
```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py migrate external_data
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_skipped_ids -v 2
```
Expected: PASS, 4 tests.

- [ ] **Step 7: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/models.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/migrations/0012_source_sync_skipped_ids.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/migrations/0013_seed_skipped_ids.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_skipped_ids.py"
git commit -m "external_data: record deliberately skipped analysis ids beside the held ones"
```

---

### Task 8: The IPC fetcher

The one with real logic. Everything here is driven by the saved fixture `data_pipeline/mcp_cache/ipc/analyses-CAF.json`.

**Files:**
- Modify: `external_data/fetchers/ipc.py`
- Create: `external_data/tests/fixtures/ipc_analyses_CAF.json` (copy of the cached reconnaissance)
- Test: `external_data/tests/test_fetcher_ipc.py`

**Interfaces:**
- Consumes: `Call`, `Fetcher`, `register` (Task 2); `SourceSync.skipped_ids` (Task 7); `settings.CRISIS_START`; `ISO3_TO_ISO2`.
- Produces: `FoodSecurityFetcher` registered twice — keys `("ipc", "food_security", "")` and `("ch", "food_security", "")`; module function `period_from_title(title) -> date | None`; method `note_empty(sync, call)`.

- [ ] **Step 1: Copy the fixture**

```bash
cp "Community Centered Humanitarian Analysis Platform/data_pipeline/mcp_cache/ipc/analyses-CAF.json" \
   "Community Centered Humanitarian Analysis Platform/external_data/tests/fixtures/ipc_analyses_CAF.json"
```

- [ ] **Step 2: Write the failing test**

Create `external_data/tests/test_fetcher_ipc.py`:

```python
"""IPC: the diff, the period, and the two ways a naive version goes wrong.

Every expectation is derived from the real listing in the fixture (22 CAF
analyses, 2013-2026), not from numbers typed by hand.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.ipc import period_from_title
from external_data.models import SourceSync

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSES = json.loads((FIXTURES / "ipc_analyses_CAF.json").read_text(encoding="utf-8"))


class PeriodFromTitleTests(TestCase):
    """The listing carries no period date. It is in the title or nowhere."""

    def test_a_month_and_year_are_read(self):
        self.assertEqual(
            period_from_title("Central African Republic - Acute Food Insecurity September 2025"),
            date(2025, 9, 1))

    def test_an_abbreviated_month_is_read(self):
        self.assertEqual(
            period_from_title("CAR - Acute Food Insecurity Apr 2020 (Projection update)"),
            date(2020, 4, 1))

    def test_a_trailing_country_code_does_not_confuse_it(self):
        self.assertEqual(
            period_from_title("Central African Republic - Acute Food Insecurity "
                              "Analysis Update – CF May 2026"),
            date(2026, 5, 1))

    def test_a_title_with_no_month_yields_none(self):
        """None means the job stops and says which analysis. It must NEVER guess:
        a wrong period files an analysis under the wrong month silently."""
        self.assertIsNone(period_from_title("Central African Republic - CAR AFI 2013"))


@override_settings(IPC_API_KEY="TESTKEY")
class PlanTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="ipc", dataset="food_security", iso3="CAF", variant="")
        self.fetcher = fetcher_for("ipc", "food_security", "")()

    def _plan(self):
        with patch("external_data.fetchers.ipc.http_get_json", return_value=ANALYSES):
            return list(self.fetcher.plan(self.sync))

    def test_analyses_older_than_the_crisis_start_are_not_planned(self):
        """The listing goes back to 2013. Without a floor the first press queues
        eighteen pulls of 8-15 MB each - the load that took IPC down before."""
        planned = {c.context["analysis_id"] for c in self._plan()}
        self.assertNotIn("12640404", planned)     # CAR AFI Nov-Dec 2013
        self.assertNotIn("26546456", planned)     # September 2022

    def test_the_april_2023_analysis_is_not_planned(self):
        """Created 2023-05-09, AFTER the crisis start, but it describes April
        2023, before it. The floor is applied to the PERIOD, not to `created`."""
        self.assertNotIn("56657074", {c.context["analysis_id"] for c in self._plan()})

    def test_an_analysis_already_held_is_not_planned(self):
        self.sync.known_ids = ["87143397"]
        self.sync.save(update_fields=["known_ids"])
        self.assertNotIn("87143397", {c.context["analysis_id"] for c in self._plan()})

    def test_a_skipped_analysis_is_not_planned(self):
        """The empty May 2026 one. Without this it fails on every single press."""
        self.sync.skipped_ids = [{"id": "87143421", "reason": "no geometry"}]
        self.sync.save(update_fields=["skipped_ids"])
        self.assertNotIn("87143421", {c.context["analysis_id"] for c in self._plan()})

    def test_nothing_is_planned_when_held_and_skipped_cover_everything(self):
        self.sync.known_ids = ["87143397", "82028572", "72156887", "62439499"]
        self.sync.skipped_ids = [{"id": "87143421", "reason": "no geometry"}]
        self.sync.save(update_fields=["known_ids", "skipped_ids"])
        self.assertEqual(self._plan(), [])

    def test_the_call_asks_for_the_current_period(self):
        call = self._plan()[0]
        self.assertTrue(call.url.startswith("https://api.ipcinfo.org/areas/"))
        self.assertTrue(call.url.endswith("/C"))

    def test_the_period_travels_in_the_context(self):
        call = next(c for c in self._plan() if c.context["analysis_id"] == "87143397")
        self.assertEqual(call.context["period_date"], date(2025, 9, 1))

    def test_the_cache_name_matches_the_existing_files(self):
        call = next(c for c in self._plan() if c.context["analysis_id"] == "87143397")
        self.assertEqual(call.cache_path, Path("ipc/CAF-87143397-C.geojson"))

    def test_the_listing_is_saved_too(self):
        """The analyses response is evidence about what was offered, not just a
        means to an end. Saved beside the areas, under the repo's own rule."""
        saved = Path("/app/data_pipeline/mcp_cache/ipc/analyses-CAF.json")
        self._plan()
        self.assertTrue(saved.is_file())

    def test_the_listing_is_asked_for_by_iso2(self):
        with patch("external_data.fetchers.ipc.http_get_json",
                   return_value=ANALYSES) as http:
            list(self.fetcher.plan(self.sync))
        self.assertEqual(http.call_args.args[1]["country"], "CF")


@override_settings(IPC_API_KEY="TESTKEY")
class ChadTests(TestCase):
    def test_the_same_fetcher_serves_cadre_harmonise(self):
        """Chad's analyses come from the IPC API under source 'ch'."""
        self.assertIsNotNone(fetcher_for("ch", "food_security", ""))


@override_settings(IPC_API_KEY="TESTKEY")
class NoteEmptyTests(TestCase):
    def test_an_empty_analysis_is_added_to_the_skip_list_with_its_title(self):
        from external_data.fetchers.base import Call
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="CAF")
        call = Call(url="x", params={}, cache_path=Path("x"), loader_dataset="food_security",
                    context={"analysis_id": "87143421",
                             "analysis_title": "CAR - Analysis Update CF May 2026"})
        fetcher_for("ipc", "food_security", "")().note_empty(sync, call)
        sync.refresh_from_db()
        self.assertEqual(sync.skipped_ids[0]["id"], "87143421")
        self.assertIn("May 2026", sync.skipped_ids[0]["reason"])

    def test_noting_the_same_analysis_twice_does_not_duplicate_it(self):
        from external_data.fetchers.base import Call
        sync = SourceSync.objects.create(source="ipc", dataset="food_security", iso3="CAF")
        call = Call(url="x", params={}, cache_path=Path("x"), loader_dataset="food_security",
                    context={"analysis_id": "87143421", "analysis_title": "t"})
        fetcher = fetcher_for("ipc", "food_security", "")()
        fetcher.note_empty(sync, call)
        fetcher.note_empty(sync, call)
        sync.refresh_from_db()
        self.assertEqual(len(sync.skipped_ids), 1)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_ipc -v 2`
Expected: FAIL — `ImportError: cannot import name 'period_from_title'`

- [ ] **Step 4: Write the fetcher**

Replace `external_data/fetchers/ipc.py` with:

```python
"""IPC and Cadre Harmonise -> food security areas.

THE ONE WITH REAL LOGIC, and three traps that reconnaissance found rather than
review. The listing behind them is saved at mcp_cache/ipc/analyses-CAF.json and
is this module's test fixture.

1. THE LISTING GOES BACK TO 2013. CAF returns 22 analyses; four are held. A diff
   of "published minus held" queues eighteen pulls of 8-15 MB each on the first
   press - the load profile that closed the IPC connection and took the server
   down for a session. CRISIS_START is the floor.

2. known_ids MEANS HELD, AND THE DIFF NEEDS "CONSIDERED". Analyses a person
   deliberately excluded are in neither list, so they would be pulled straight
   back in; analyses that publish no geometry would fail on every press forever.
   skipped_ids is the other half of the answer, and note_empty() grows it.

3. THERE IS NO PERIOD DATE IN THE RESPONSE. The record carries id, title,
   country, year, condition, created and modified - and no analysis period. The
   period is in the title, so it is parsed from there, and a title that yields
   nothing stops the job instead of guessing.
"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, http_get_json, save_payload
from external_data.loaders.seasonal import ISO3_TO_ISO2

BASE = "https://api.ipcinfo.org"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b[\s.,-]*(\d{4})",
    re.IGNORECASE,
)


def period_from_title(title):
    """The first day of the period the title names, or None.

    None is a refusal, not a default. `_period_date` in load_external keeps the
    same rule and states the reason: a wrong period silently files an analysis
    under the wrong month, which is worse than a load that stops.

    Longest-first alternation matters - "September" must win over "Sep", or every
    September analysis parses as one and leaves "tember 2025" behind.
    """
    match = _MONTH_YEAR.search(title or "")
    if not match:
        return None
    return date(int(match.group(2)), MONTHS[match.group(1).lower()], 1)


def _crisis_floor():
    """CRISIS_START as a date. Defined in settings as a string, and in
    data_pipeline.common as a date; this module has no business importing the
    pipeline, so it parses the setting."""
    year, month, day = (int(p) for p in settings.CRISIS_START.split("-"))
    return date(year, month, day)


@register
class FoodSecurityFetcher(Fetcher):
    """`list_analyses`, then `get_areas_by_analysis` for each one not considered.

    Registered twice, at the bottom of this file: Chad's Cadre Harmonise
    analyses come from this same API under source 'ch'.
    """

    source = "ipc"
    dataset = "food_security"
    variant = ""
    tool = "get_areas_by_analysis"
    requires = ("IPC_API_KEY",)

    def plan(self, sync):
        iso2 = ISO3_TO_ISO2.get(sync.iso3)
        if not iso2:
            raise KeyError(
                f"{sync.iso3} is not in ISO3_TO_ISO2 (external_data/loaders/"
                "seasonal.py). IPC takes a two-letter country code."
            )

        analyses = http_get_json(
            f"{BASE}/analyses",
            {"country": iso2, "type": "A", "format": "json",
             "key": settings.IPC_API_KEY},
        )
        # Saved as evidence of what was OFFERED, which is a different fact from
        # what was taken, and the only record of why an analysis was passed over.
        save_payload(Path("ipc") / f"analyses-{sync.iso3}.json", analyses)

        considered = set(sync.known_ids or [])
        considered |= {s.get("id") for s in (sync.skipped_ids or [])}
        floor = _crisis_floor()

        for record in analyses:
            analysis_id = str(record.get("id") or "")
            if not analysis_id or analysis_id in considered:
                continue

            title = record.get("title") or ""
            period = period_from_title(title)
            if period is None:
                # Every analysis inside the crisis window has a parseable title;
                # the ones that do not are all from 2013-2014. Skipping them
                # quietly here is right, because the floor would drop them anyway.
                continue
            if period < floor:
                continue

            yield Call(
                url=f"{BASE}/areas/{analysis_id}/C",
                params={"format": "geojson", "key": settings.IPC_API_KEY},
                # The existing naming, unchanged: every file already in
                # mcp_cache/ipc/ is <ISO3>-<id>-C.geojson.
                cache_path=Path("ipc") / f"{sync.iso3}-{analysis_id}-C.geojson",
                loader_dataset="food_security",
                context={"analysis_id": analysis_id, "analysis_title": title,
                         "period_date": period},
            )

    def note_empty(self, sync, call):
        """Record that this analysis published nothing, so it is asked once only.

        Called by the runner when a Call trips EmptyPayload. The title is kept as
        the reason because "87143421" tells a later reader nothing and
        "Analysis Update CF May 2026" tells them what to go and look at.
        """
        analysis_id = call.context.get("analysis_id")
        if not analysis_id:
            return
        existing = sync.skipped_ids or []
        if analysis_id in {s.get("id") for s in existing}:
            return
        title = call.context.get("analysis_title") or "no title"
        sync.skipped_ids = existing + [{
            "id": analysis_id,
            "reason": f"returned no areas when pulled: {title}",
        }]
        sync.save(update_fields=["skipped_ids"])

    def params_record(self):
        return {"tool": self.tool, "listing": "list_analyses", "period": "C",
                "floor": settings.CRISIS_START}


# Chad's analyses are Cadre Harmonise, published through the same IPC API. The
# loader already varies `source` by country (food_security.source_for); the fetch
# is identical, so the same class is registered under both names rather than
# copied.
@register
class CadreHarmoniseFetcher(FoodSecurityFetcher):
    source = "ch"
```

- [ ] **Step 5: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data.tests.test_fetcher_ipc -v 2`
Expected: PASS, 17 tests.

- [ ] **Step 6: Run the whole external_data suite**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test external_data -v 2`
Expected: PASS — the existing loader tests must be untouched by all of this.

- [ ] **Step 7: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/external_data/fetchers/ipc.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/test_fetcher_ipc.py" \
  "Community Centered Humanitarian Analysis Platform/external_data/tests/fixtures/ipc_analyses_CAF.json"
git commit -m "external_data: fetch IPC analyses, honouring the skip list and the crisis floor"
```

---

### Task 9: The admin section and the Pull button

**Files:**
- Create: `mcp/admin.py`, `mcp/views.py`, `mcp/templates/mcp/job.html`
- Test: `mcp/tests/test_admin.py`

**Interfaces:**
- Consumes: `DataSource`, `PullJob` (Task 4); `claim`, `JobBusy` (Task 4); `fetcher_for`, `missing_keys` (Tasks 2, 3, 6, 8).
- Produces: admin at `/admin/mcp/datasource/`, pull endpoint at `/admin/mcp/datasource/pull/<pk>/`, job page at `/admin/mcp/datasource/job/<id>/`, and `mcp.admin.SOURCE_LABELS`.

- [ ] **Step 1: Write the failing test**

Create `mcp/tests/test_admin.py`:

```python
"""The section, the button, and the rows that must not offer one."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from external_data.models import SourceSync
from mcp.models import PullJob


class AdminTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "tester", "t@example.org", "pw")
        self.client.force_login(self.user)
        self.api_row = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")
        self.file_row = SourceSync.objects.create(
            source="excel", dataset="idps", iso3="SDN", variant="sudan-idps-workbook")


class ListTests(AdminTestCase):
    def test_the_section_is_reachable(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_the_source_is_shown_by_its_display_name(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "FEWS NET")

    @override_settings(IPC_API_KEY="", HDX_API_TOKEN="")
    def test_a_row_whose_key_is_missing_says_which_one(self):
        SourceSync.objects.create(source="ipc", dataset="food_security", iso3="SDN")
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "IPC_API_KEY")

    def test_a_file_based_row_offers_no_button(self):
        """A button that cannot work is worse than no button."""
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertNotContains(
            response, f'/admin/mcp/datasource/pull/{self.file_row.pk}/')

    def test_an_api_row_offers_one(self):
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, f"/admin/mcp/datasource/pull/{self.api_row.pk}/")


class PullTests(AdminTestCase):
    def _url(self, row):
        return f"/admin/mcp/datasource/pull/{row.pk}/"

    def test_pressing_the_button_creates_a_queued_job_and_launches_it(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self.client.post(self._url(self.api_row))
        self.assertEqual(response.status_code, 302)
        job = PullJob.objects.get()
        self.assertEqual(job.source, "fewsnet")
        self.assertEqual(job.requested_by, self.user)
        popen.assert_called_once()

    def test_the_command_is_launched_detached(self):
        """start_new_session, or a child that outlives its worker reparents to
        gunicorn's arbiter, which misreads its exit code and halts the server."""
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.api_row))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("refresh_external", popen.call_args.args[0])

    def test_a_get_does_not_start_anything(self):
        """A pull is a change. It must not be triggerable by following a link."""
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.get(self._url(self.api_row))
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)

    def test_an_anonymous_visitor_is_refused(self):
        self.client.logout()
        with patch("mcp.views.subprocess.Popen") as popen:
            response = self.client.post(self._url(self.api_row))
        popen.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_a_busy_source_is_refused_without_launching(self):
        PullJob.objects.create(kind="pull", source="fewsnet",
                               dataset="seasonal_calendar", iso3="TCD",
                               status="running")
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.api_row))
        popen.assert_not_called()

    def test_a_file_based_row_is_refused(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post(self._url(self.file_row))
        popen.assert_not_called()
        self.assertEqual(PullJob.objects.count(), 0)


class JobPageTests(AdminTestCase):
    def test_a_job_page_shows_its_status(self):
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="failed", message="503 from fdw.fews.net")
        response = self.client.get(f"/admin/mcp/datasource/job/{job.id}/")
        self.assertContains(response, "503 from fdw.fews.net")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp.tests.test_admin -v 2`
Expected: FAIL — `NoReverseMatch: 'mcp_datasource_changelist' is not a registered namespace`

- [ ] **Step 3: Write the views**

Create `mcp/views.py`:

```python
"""Starting a job from a button, and watching it.

The launch pattern is the one insights/admin.py established: create the row, set
it running, then Popen the management command with start_new_session=True. That
flag is not optional - docker-compose.yml explains why at length: a detached
child that outlives its worker otherwise reparents to gunicorn's arbiter, which
reads its exit code as a worker boot failure and halts the server.
"""
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync
from mcp.locks import JobBusy, claim
from mcp.models import PullJob


def _log_path(job):
    """Where this job's output goes. Under /app, because /work is read-only."""
    directory = Path(settings.MCP_CACHE_DIR) / "mcp"
    # Created here rather than by the command: on a fresh setup the very first
    # press would otherwise fail opening the file before the command could run.
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"job-{job.id}.log"


def _launch(job, argv):
    """Run a management command detached, with its output going to the job log."""
    path = _log_path(job)
    job.log_path = str(path)
    job.save(update_fields=["log_path"])
    with open(path, "wb") as log_file:
        subprocess.Popen(
            [sys.executable, "manage.py", *argv],
            cwd=settings.BASE_DIR,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )


def pull(request, pk):
    """Start a pull for one source_sync row."""
    if request.method != "POST":
        # A pull changes the database, so it is never a GET. Otherwise a crawler,
        # a prefetching browser or a pasted link starts an 8-15 MB IPC fetch.
        return redirect("admin:mcp_datasource_changelist")

    row = SourceSync.objects.filter(pk=pk).first()
    if row is None:
        raise Http404("no such data source")

    fetcher_cls = fetcher_for(row.source, row.dataset, row.variant)
    if fetcher_cls is None:
        messages.error(request, f"{row.source}/{row.dataset} is file-based - "
                                "there is no API to pull from.")
        return redirect("admin:mcp_datasource_changelist")

    absent = missing_keys(fetcher_cls)
    if absent:
        messages.error(request, f"{', '.join(absent)} is not set in .env, so this "
                                "source cannot be pulled yet.")
        return redirect("admin:mcp_datasource_changelist")

    try:
        job = claim("pull", source=row.source, dataset=row.dataset, iso3=row.iso3,
                    variant=row.variant, user=request.user)
    except JobBusy as exc:
        messages.warning(request, str(exc))
        return redirect("admin:mcp_datasource_changelist")

    argv = ["refresh_external", row.source, row.dataset, "--job", str(job.id)]
    if row.iso3:
        argv += ["--iso3", row.iso3]
    if row.variant:
        argv += ["--variant", row.variant]
    _launch(job, argv)

    messages.success(request, f"job {job.id}: pulling {row.source}/{row.dataset} "
                              f"{row.iso3 or 'global'} in the background.")
    return redirect("admin:mcp_datasource_changelist")


def job_page(request, job_id):
    """One job, with its log."""
    job = PullJob.objects.filter(pk=job_id).first()
    if job is None:
        raise Http404("no such job")
    log = ""
    if job.log_path and Path(job.log_path).is_file():
        log = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
    return render(request, "mcp/job.html", {"job": job, "log": log})


def job_status(request, job_id):
    """Just enough for the page to poll without reloading everything."""
    job = PullJob.objects.filter(pk=job_id).first()
    if job is None:
        raise Http404("no such job")
    return JsonResponse({"status": job.status, "rows": job.rows_written,
                         "message": job.message})
```

- [ ] **Step 4: Write the admin**

Create `mcp/admin.py`:

```python
"""The Model Context Protocol section: what is held, and the button to refresh it.

READ-ONLY APART FROM THE BUTTONS, and for the reason external_data/admin.py
already gives: every row here is written by a loader, so a row hand-edited in the
browser is a row the next refresh silently overwrites.
"""
from django.contrib import admin
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from mcp import views
from mcp.models import ACTIVE, DataSource, PullJob

# What each source is CALLED, as opposed to what its column says. The office says
# "FEWS NET", not "fewsnet".
SOURCE_LABELS = {
    "fewsnet": "FEWS NET", "hdx": "HDX HAPI", "ipc": "IPC",
    "ch": "Cadre Harmonisé", "unhcr": "UNHCR", "acaps": "ACAPS",
    "excel": "Excel workbook", "kobo": "Kobo",
}

# Why a source has no button. Naming the command that DOES load it turns a dead
# end into an instruction.
FILE_BASED = {
    "excel": "file-based — manage.py load_workbooks",
    "kobo": "file-based — manage.py load_hsps",
    "acaps": "CSV export — manage.py load_external acaps_seasonal",
}


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("source_label", "dataset", "country", "last_pulled_at",
                    "high_water_date", "row_count", "job_status", "pull_button")
    list_filter = ("source", "dataset", "iso3")
    search_fields = ("source", "dataset", "variant", "tool", "notes")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path("pull/<int:pk>/", self.admin_site.admin_view(views.pull),
                 name="mcp_pull"),
            path("job/<int:job_id>/", self.admin_site.admin_view(views.job_page),
                 name="mcp_job"),
            path("job/<int:job_id>/status/",
                 self.admin_site.admin_view(views.job_status),
                 name="mcp_job_status"),
        ] + super().get_urls()

    @admin.display(description="source", ordering="source")
    def source_label(self, obj):
        return SOURCE_LABELS.get(obj.source, obj.source)

    @admin.display(description="country", ordering="iso3")
    def country(self, obj):
        return obj.iso3 or "global"

    @admin.display(description="status")
    def job_status(self, obj):
        """The latest attempt for this row - including the ones that failed.

        This column is why PullJob exists: source_sync records what is HELD and
        says nothing about an attempt that did not land.
        """
        job = (PullJob.objects
               .filter(source=obj.source, dataset=obj.dataset, iso3=obj.iso3,
                       variant=obj.variant)
               .order_by("-requested_at").first())
        if job is None:
            return "—"
        label = "stuck" if job.is_stale else job.status
        detail = f": {job.message[:80]}" if job.status == "failed" else ""
        return format_html('<a href="{}">{}{}</a>',
                           f"job/{job.id}/", label, detail)

    @admin.display(description="")
    def pull_button(self, obj):
        fetcher_cls = fetcher_for(obj.source, obj.dataset, obj.variant)
        if fetcher_cls is None:
            return mark_safe(f'<span style="color:#888">'
                             f'{FILE_BASED.get(obj.source, "no API behind this source")}'
                             f'</span>')

        absent = missing_keys(fetcher_cls)
        if absent:
            return mark_safe(f'<span style="color:#888" title="Add it to .env and '
                             f'restart the web container">needs {absent[0]} in .env</span>')

        if PullJob.objects.filter(source=obj.source, status__in=ACTIVE).exists():
            return mark_safe('<span style="color:#888">source busy</span>')

        # A POST, not a link: a pull changes the database, and an IPC pull moves
        # 8-15 MB per analysis. Nothing should be able to start one by prefetch.
        return format_html(
            '<form method="post" action="pull/{}/" style="margin:0">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<button type="submit">Pull now</button></form>',
            obj.pk, _csrf(),
        )


def _csrf():
    """The admin renders columns outside a request-bound template context, so the
    token is fetched explicitly rather than by {% csrf_token %}."""
    from django.middleware.csrf import get_token
    from mcp.middleware_local import current_request
    request = current_request()
    return get_token(request) if request else ""


@admin.register(PullJob)
class PullJobAdmin(admin.ModelAdmin):
    """The attempt log. Never edited; kept as an audit trail."""

    list_display = ("id", "kind", "target", "status", "rows_written",
                    "requested_by", "requested_at", "finished_at")
    list_filter = ("kind", "status", "source")
    search_fields = ("source", "dataset", "iso3", "message")
    date_hierarchy = "requested_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

**Note for the implementer:** the `_csrf()` helper above needs the current request, and Django's admin does not hand one to a `list_display` callable. Rather than add thread-local middleware, use Django's simpler route: render the button as a plain link that GETs a confirmation page which contains a real form. Replace `pull_button`'s final `format_html(...)` with:

```python
        return format_html('<a class="button" href="pull/{}/">Pull now</a>', obj.pk)
```

and change `views.pull` so a GET renders `mcp/confirm.html` (a one-button POST form with `{% csrf_token %}`) instead of redirecting. Update the test `test_a_get_does_not_start_anything` to assert the GET returns 200 and starts nothing, which it already checks. Delete `_csrf()` and the `middleware_local` import entirely — there is no such module and there should not be one.

- [ ] **Step 5: Write the templates**

Create `mcp/templates/mcp/confirm.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
  <h1>Pull {{ row.source }}/{{ row.dataset }} {{ row.iso3|default:"global" }}?</h1>
  <p>
    This fetches from the source's API, saves the raw response under
    <code>mcp_cache/</code>, and loads it into the database. It does not rebuild
    the dashboard — that is a separate button on the data sources list.
  </p>
  {% if row.notes %}<p><strong>Note on this row:</strong> {{ row.notes }}</p>{% endif %}
  <form method="post">
    {% csrf_token %}
    <button type="submit" class="default">Pull now</button>
    <a href="{% url 'admin:mcp_datasource_changelist' %}" class="button cancel-link">Cancel</a>
  </form>
{% endblock %}
```

Create `mcp/templates/mcp/job.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
  <h1>Job {{ job.id }} — {{ job.target }}</h1>
  <p>
    <strong>{{ job.status }}</strong>
    {% if job.rows_written %} · {{ job.rows_written }} rows{% endif %}
    {% if job.requested_by %} · started by {{ job.requested_by }}{% endif %}
    · requested {{ job.requested_at }}
  </p>
  {% if job.message %}<p>{{ job.message }}</p>{% endif %}
  <pre style="background:#111;color:#eee;padding:1em;overflow:auto;max-height:60vh">{{ log }}</pre>
  <p><a href="{% url 'admin:mcp_datasource_changelist' %}">Back to data sources</a></p>
  {% if job.status in "queued running" %}
  <script>
    // The command is still writing. Reload until it stops, then leave the page
    // alone so a finished log can be read and copied.
    setTimeout(function () { location.reload(); }, 4000);
  </script>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Update `views.pull` for the GET confirmation**

In `mcp/views.py`, replace the first three lines of `pull()` with:

```python
    row = SourceSync.objects.filter(pk=pk).first()
    if row is None:
        raise Http404("no such data source")

    if request.method != "POST":
        # A pull changes the database and an IPC one moves 8-15 MB per analysis,
        # so it is never started by following a link. The GET is a confirmation
        # page whose form POSTs back here with a CSRF token.
        return render(request, "mcp/confirm.html", {"row": row})
```

- [ ] **Step 7: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp -v 2`
Expected: PASS, all tests in `mcp`.

- [ ] **Step 8: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/mcp"
git commit -m "mcp: add the data sources section and the pull button"
```

---

### Task 10: The Rebuild dashboard layers button

**Files:**
- Modify: `mcp/views.py`, `mcp/admin.py`
- Create: `mcp/templates/admin/mcp/datasource/change_list.html`
- Test: `mcp/tests/test_rebuild.py`

**Interfaces:**
- Consumes: `claim`, `JobBusy`, `PullJob`, `_launch` (Tasks 4, 9).
- Produces: `views.rebuild`, URL name `mcp_rebuild`, and `mcp.views.pulls_since_last_rebuild() -> int`.

- [ ] **Step 1: Write the failing test**

Create `mcp/tests/test_rebuild.py`:

```python
"""The second button: the database is updated, the map is not - until you say so."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from mcp.models import PullJob
from mcp.views import pulls_since_last_rebuild


class RebuildTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("t", "t@e.org", "pw")
        self.client.force_login(self.user)

    def test_pressing_it_launches_the_pipeline_steps(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post("/admin/mcp/datasource/rebuild/")
        argv = popen.call_args.args[0]
        self.assertIn("run_pipeline", argv)
        self.assertIn("s06,s07", argv)

    def test_it_creates_a_rebuild_job(self):
        with patch("mcp.views.subprocess.Popen"):
            self.client.post("/admin/mcp/datasource/rebuild/")
        self.assertEqual(PullJob.objects.get().kind, "rebuild")

    def test_it_is_refused_while_a_pull_runs(self):
        PullJob.objects.create(kind="pull", source="ipc", dataset="food_security",
                               iso3="SDN", status="running")
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.post("/admin/mcp/datasource/rebuild/")
        popen.assert_not_called()

    def test_a_get_starts_nothing(self):
        with patch("mcp.views.subprocess.Popen") as popen:
            self.client.get("/admin/mcp/datasource/rebuild/")
        popen.assert_not_called()


class CounterTests(TestCase):
    def test_it_counts_successful_pulls_since_the_last_rebuild(self):
        PullJob.objects.create(kind="rebuild", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="hdx", status="succeeded",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 2)

    def test_failed_pulls_do_not_count(self):
        """A failed pull changed nothing, so it is not a reason to rebuild."""
        PullJob.objects.create(kind="rebuild", status="succeeded",
                               finished_at=timezone.now())
        PullJob.objects.create(kind="pull", source="ipc", status="failed",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 0)

    def test_with_no_rebuild_ever_every_successful_pull_counts(self):
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        self.assertEqual(pulls_since_last_rebuild(), 1)

    def test_the_changelist_reports_the_count(self):
        user = get_user_model().objects.create_superuser("u", "u@e.org", "pw")
        self.client.force_login(user)
        PullJob.objects.create(kind="pull", source="ipc", status="succeeded",
                               finished_at=timezone.now())
        response = self.client.get(reverse("admin:mcp_datasource_changelist"))
        self.assertContains(response, "1 pull")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp.tests.test_rebuild -v 2`
Expected: FAIL — `ImportError: cannot import name 'pulls_since_last_rebuild'`

- [ ] **Step 3: Add the view**

Append to `mcp/views.py`:

```python
def pulls_since_last_rebuild():
    """How many successful pulls the dashboard has not been rebuilt for.

    The button works with zero; the count is what tells an operator whether it is
    worth pressing. FAILED PULLS DO NOT COUNT - a pull that failed changed
    nothing, so it is not a reason to rebuild anything.
    """
    last = (PullJob.objects.filter(kind="rebuild", status="succeeded")
            .order_by("-finished_at").first())
    pulls = PullJob.objects.filter(kind="pull", status="succeeded")
    if last and last.finished_at:
        pulls = pulls.filter(finished_at__gt=last.finished_at)
    return pulls.count()


def rebuild(request):
    """Rebuild the dashboard's external layers from what is now in the database.

    SEPARATE FROM A PULL, deliberately. A pull updates the database and stops
    there; rebuilding the map is the operator's call, made after they have looked
    at what arrived. Chaining the two would widen a refresh button's blast radius
    to a pipeline that rewrites dashboard files.

    The steps are s06 and s07 - the same pair the updater page's own rebuild runs.
    """
    if request.method != "POST":
        return render(request, "mcp/confirm_rebuild.html",
                      {"pulls": pulls_since_last_rebuild()})

    try:
        job = claim("rebuild", user=request.user)
    except JobBusy as exc:
        messages.warning(request, str(exc))
        return redirect("admin:mcp_datasource_changelist")

    _launch(job, ["run_pipeline", "--only", "s06,s07"])
    messages.success(request, f"job {job.id}: rebuilding the dashboard layers.")
    return redirect("admin:mcp_datasource_changelist")
```

**Note:** `test_pressing_it_launches_the_pipeline_steps` asserts `"s06,s07"` is in the argv list, which it is — as its own element, because `--only` and its value are separate arguments.

- [ ] **Step 4: Wire the URL and the changelist**

In `mcp/admin.py`, add to `get_urls()` before the closing bracket:

```python
            path("rebuild/", self.admin_site.admin_view(views.rebuild),
                 name="mcp_rebuild"),
```

And add to `DataSourceAdmin`:

```python
    change_list_template = "admin/mcp/datasource/change_list.html"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["pulls_since_rebuild"] = views.pulls_since_last_rebuild()
        return super().changelist_view(request, extra_context)
```

- [ ] **Step 5: Write the templates**

Create `mcp/templates/admin/mcp/datasource/change_list.html`:

```html
{% extends "admin/change_list.html" %}
{% block object-tools %}
  <div style="margin:0 0 1em 0;padding:.75em 1em;background:#f6f6f6;border:1px solid #ddd">
    <a class="button" href="rebuild/">Rebuild dashboard layers</a>
    <span style="margin-left:.75em;color:#555">
      {% if pulls_since_rebuild %}
        {{ pulls_since_rebuild }} pull{{ pulls_since_rebuild|pluralize }} since the last rebuild.
      {% else %}
        No pulls since the last rebuild.
      {% endif %}
      A pull updates the database only; the map changes when you rebuild.
    </span>
  </div>
  {{ block.super }}
{% endblock %}
```

Create `mcp/templates/mcp/confirm_rebuild.html`:

```html
{% extends "admin/base_site.html" %}
{% block content %}
  <h1>Rebuild the dashboard layers?</h1>
  <p>
    This runs pipeline steps s06 and s07, rewriting the files under
    <code>dashboard/data/</code> from what is currently in the database.
    {% if pulls %}
      There {{ pulls|pluralize:"has,have" }} been {{ pulls }} successful
      pull{{ pulls|pluralize }} since the last rebuild.
    {% else %}
      Nothing has been pulled since the last rebuild, so this will reproduce what
      is already on screen.
    {% endif %}
  </p>
  <form method="post">
    {% csrf_token %}
    <button type="submit" class="default">Rebuild now</button>
    <a href="{% url 'admin:mcp_datasource_changelist' %}" class="button cancel-link">Cancel</a>
  </form>
{% endblock %}
```

- [ ] **Step 6: Run the tests**

Run: `MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test mcp -v 2`
Expected: PASS, all tests in `mcp`.

- [ ] **Step 7: Commit**

```bash
git add "Community Centered Humanitarian Analysis Platform/mcp"
git commit -m "mcp: add the optional dashboard rebuild button"
```

---

### Task 11: Verify against the real APIs, and document the route

**Files:**
- Modify: `CLAUDE.md`
- Test: manual, plus the full suite

**Interfaces:**
- Consumes: everything.
- Produces: nothing new.

- [ ] **Step 1: Run the whole suite**

Run:
```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py test -v 2
```
Expected: PASS. If anything in `data_pipeline`, `dashboard` or `insights` broke, stop and fix it — nothing in this plan should have touched them.

- [ ] **Step 2: Pull FEWS NET for Chad, for real**

This needs no key, so it proves the whole path end to end.

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py external_status | grep "fewsnet   seasonal_calendar TCD"
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py refresh_external fewsnet seasonal_calendar --iso3 TCD
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py external_status | grep "fewsnet   seasonal_calendar TCD"
```
Expected: the "pulled" date moves to today; the row count stays at 6 (the same six seasons, upserted — idempotence is the loader's first guarantee).

- [ ] **Step 3: Pull the UNHCR refugees for Chad, for real**

This needs `HDX_API_TOKEN` and is the row that has never been pulled at all.

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py refresh_external unhcr refugees --iso3 TCD
MSYS_NO_PATHCONV=1 docker compose exec -T web python manage.py external_status | grep "unhcr     refugees          TCD"
```
Expected: "pulled" changes from `never` to today. If the token is not set, the command refuses by name and nothing is called — that is also a pass for this step; note it and move on.

- [ ] **Step 4: Press the buttons in a browser**

Open `http://localhost:2026/admin/mcp/datasource/`. Confirm:
- the sidebar heading reads **Model Context Protocol (MCP)**
- the FEWS NET rows show **Pull now**; the Excel, Kobo and ACAPS rows show their file-based note instead
- pressing **Pull now** on `fewsnet / seasonal_calendar / SDN` shows the confirmation page, then a job message, and the job page shows the command's output
- pressing it again while that job runs is refused with a message naming the job
- **Rebuild dashboard layers** reports the pulls since the last rebuild

- [ ] **Step 5: Update CLAUDE.md**

In `CLAUDE.md`, replace the opening of the section "### 1. Pull external data through the MCP servers" with:

```markdown
### 1. Pull external data

**For a person, the route in is Admin → Model Context Protocol (MCP) → Data
sources.** Each row carries its last pull and its newest data date, and every
API-backed row has a Pull now button that fetches, saves the raw response under
`data_pipeline/mcp_cache/`, and loads it — the same fetch-save-load rule below,
run by the application. Rebuilding the dashboard afterwards is a separate button
on that page, so the database and the map move only when you say so.

Those buttons call the upstream APIs directly, because the container cannot run
the MCP servers: they are Node scripts on a host share that is not mounted into
it. The payloads are identical — each MCP tool this project uses is a
pass-through wrapper — but the distinction matters when a fetcher and its tool
ever disagree. See `docs/superpowers/specs/2026-09-15-mcp-data-sources-admin-design.md`.

From a terminal, the same thing:

    docker compose exec web python manage.py refresh_external <source> <dataset> --iso3 <ISO3>

**For an agent, and for the sources with no fetcher** (`excel`, `kobo`, `acaps`),
the rule is unchanged — **fetch, save, then load**, never fetch straight into the
database:
```

Leave the four numbered steps that follow exactly as they are.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: the MCP admin section is now the route in for a person"
```

---

## Self-Review

**Spec coverage.** §5.1 list → Task 9. §5.2 file-based rows → Task 9 (`FILE_BASED`). §5.3 rebuild button and counter → Task 10. §6 `PullJob` → Task 4. §7.1 contract → Task 2. §7.2 fetchers → Tasks 3, 6, 8. §7.3 IPC → Tasks 7, 8. §7.4 params and the variant key → Tasks 2, 5. §8 command → Task 5. §9 lock → Task 4. §10 launch → Task 9. §11 settings → Task 1. §12 verification → the tests in each task, plus Task 11. §13 sequencing → task order. §14 rollback → no task needed; it is a property of the structure.

**One deliberate deviation from the spec.** §6 lists `log` as a text column on `PullJob`; the plan writes the output to a file under `MCP_CACHE_DIR/mcp/` and stores `log_path` instead. That follows `insights/admin.py`, which already does exactly this, and keeps a long IPC run out of a database row. `message` still holds the one-line summary or error, which is what the list column shows.

**Types.** `Call(url, params, cache_path, loader_dataset, context, paginated)` is constructed with those names in Tasks 3, 6 and 8 and consumed by those names in Task 5. `claim(kind, *, source, dataset, iso3, variant, user)` is defined in Task 4 and called with exactly those keywords in Tasks 9 and 10. `missing_keys` and `fetcher_for` are defined in Task 2 and used in Tasks 5 and 9. `note_empty(sync, call)` is defined in Task 8 and called through `_note_empty` in Task 5, which tolerates its absence on every other fetcher.

**One thing the implementer must not skip.** Task 7 Step 5 contains two placeholder analysis ids for Chad, clearly marked, with instructions to obtain the real ones or delete that entry. They are the only unresolved values in this plan, and they are unresolved because the notes name those analyses by date rather than by id. Guessing them would silently exclude real data.
