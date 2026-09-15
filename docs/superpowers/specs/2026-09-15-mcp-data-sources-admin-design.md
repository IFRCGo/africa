# Model Context Protocol (MCP): a data-sources section in the admin, and a button that pulls

**Date:** 2026-09-15
**Status:** designed, not yet implemented
**Supersedes one decision:** the 2026-09-09 external-data-persistence spec listed "no new
fetching mechanism" as a non-goal, and said in the same breath that "a scheduled REST
fetcher is a possible later sub-project, and the loader is designed not to care who produced
the JSON it is handed." This is that sub-project. The loaders are not changed; they are
handed the same JSON by a different producer.

## 1. Why

The office can see what external data the platform holds. `manage.py external_status` prints
it, `/admin/external_data/sourcesync/` lists it, and both answer the question "how fresh is
this?" honestly. Neither answers the question that follows it: **"then go and get the new
one."**

Today the only way to refresh IPC phases or FEWS NET seasons is for someone to open Claude
Code on the host, call an MCP tool, save the response into `data_pipeline/mcp_cache/`, and
run `manage.py load_external`. That is four steps, a terminal, and a person who knows the
convention. It is the reason the UNHCR refugee rows still read "never" in the pulled column
and carry 2024 data.

**Django cannot call the MCP servers, and this spec does not pretend otherwise.** `.mcp.json`
points at Node scripts under `IFRC-GO-MCP/` on a Windows share that is not mounted into the
`web` container, and the container has no Node in it. What makes the button possible is that
those servers are thin wrappers: every tool used by this project resolves to a single
`axios.get(BASE + endpoint)` whose handler ends in `return response.data`, unchanged. A
Python client calling the same endpoint with the same parameters produces the same bytes,
and therefore a payload the existing loaders already know how to parse.

So the section is named for the Model Context Protocol because that is the family of sources
it covers and the vocabulary the office uses for them. The pull itself is a plain HTTPS
request to the same upstream API the MCP tool wraps. Section 15 states that limit plainly
rather than leaving someone to discover it.

## 2. Goals

1. A sidebar section in `/admin/` headed **Model Context Protocol (MCP)**, listing every
   external data source the platform holds, one row per source × dataset × country, with the
   source named, the last pull timestamped, and the newest data date beside it.
2. A **Pull now** button on each row whose source has an API behind it, which fetches,
   saves the raw payload to `mcp_cache/`, loads it through the existing loader, and leaves
   the database updated — with no terminal and no agent session.
3. A record of every attempt, including the failed ones, with the error text kept.
4. A separate, optional **Rebuild dashboard layers** button, so a pull updates the database
   and the operator decides afterwards whether the map should be rebuilt from it.
5. Rows whose source has no API say so instead of offering a button that cannot work.

## 3. Non-goals

- **No scheduler.** Nothing pulls on a timer. Every pull is a button press by a signed-in
  staff user. A cron-driven refresh is a later question and this design does not foreclose
  it — `refresh_external` is a management command first and an admin button second.
- **No new data tables for external data.** The six subject tables and `source_sync` stay
  exactly as they are. This adds one table, and it records jobs, not humanitarian data.
- **No change to any loader.** The four guarantees in `external_data/loaders/base.py` are
  what make the button safe; they are used, not modified.
- **No MCP client in Python.** Considered and rejected — see §4.
- **No new countries or datasets.** The 36 rows that exist today are the 36 rows the section
  lists. Adding a source remains adding a loader plus a fetcher.
- **No change to the dashboard's appearance.** The rebuild button runs the pipeline steps
  that already exist and produces what they already produce.

## 4. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| How the button fetches | **Direct HTTPS to the upstream API** | The container cannot run the MCP servers, and those servers are pass-through wrappers, so the payload is identical. §1. |
| Alternative rejected | MCP servers inside the container (Node in the image, folder mounted, Python `mcp` stdio client) | Ties the app to a path on a second OneDrive share — the fragility `docker-compose.yml` already apologises for on the boundary mounts — for a payload that is byte-identical either way. |
| Alternative rejected | A request queue the agent fulfils | Honest and cheap, but the data would not update on its own, which is the whole ask. |
| Where the section lives | **New app `mcp`**, its own admin heading | Django groups the admin sidebar by app. A separate heading keeps "pulling" and "what was pulled" apart, as requested. |
| The list's model | **Proxy model over `SourceSync`** | The freshness table already exists and is already correct. A second table holding the same facts would drift from it. |
| Row grain | **source × dataset × iso3 × variant** — one row per `source_sync` row | A pull is then a single upstream call, which is what keeps the IPC rule below enforceable. |
| Pull and rebuild | **Two separate buttons** | A pull touches the database only. Chaining a pipeline rebuild onto it widens the blast radius of a refresh button, and the operator wants to see the data before the map moves. |
| Concurrency | **A database lock, not `threading.Lock`** | `updater/views.py` uses an in-process lock, which cannot see the other gunicorn workers. Two browser tabs is exactly how the recorded IPC crash happens again. §9. |
| Failed attempts | **On `PullJob`, never on `source_sync`** | `source_sync` may only be advanced by a successful load. A failed pull must not look fresh. |
| HTTP client | **`requests==2.32.3`** | One pinned dependency, the mocking story is well understood, and `urllib` would cost hand-rolled retry and timeout handling for nothing. |

## 5. What the section looks like

`/admin/` gains a heading **Model Context Protocol (MCP)** with one entry, **Data sources**,
and a job log beneath it.

### 5.1 The Data sources list

One row per `source_sync` row — 36 today (9 ACAPS, 9 FEWS NET, 7 UNHCR, 6 IPC, 2 Excel, and
one each for Cadre Harmonisé, HDX and Kobo). Columns:

| Column | From | Notes |
|---|---|---|
| Source | `source_sync.source`, through a display map | `fewsnet` → FEWS NET, `hdx` → HDX HAPI, `ipc` → IPC, `ch` → Cadre Harmonisé, `unhcr` → UNHCR, `acaps` → ACAPS, `excel` → Excel workbook, `kobo` → Kobo |
| Dataset | `source_sync.dataset` | seasonal calendar / food security / idps / refugees / … |
| Country | `source_sync.iso3` | "global" where null |
| Last pulled | `source_sync.last_pulled_at` | **date and time**, not date alone |
| Data to | `source_sync.high_water_date` | the newest DATA date held, which is a different fact and stays labelled as one |
| Rows | `source_sync.row_count` | |
| Status | latest `PullJob` for that row | idle / running / failed, the failure showing its message |
| | | **Pull now**, or a disabled control naming why not |

Filterable by source, dataset and country; `notes` stays searchable, so a source that
publishes annually keeps explaining its own old date where the reader can see it.

**The list is read-only apart from the buttons.** It inherits the `ReadOnly` admin in
`external_data/admin.py` and its reasoning: every one of these rows is written by a loader,
so a row hand-edited here is a row the next refresh silently overwrites.

### 5.2 Rows with no API

`excel`, `kobo` and `acaps` show a disabled control reading *file-based — loaded by
`manage.py load_workbooks`* (respectively `load_hsps`, and `load_external acaps_seasonal`
from a CSV export). ACAPS is in this group for a specific reason worth writing down: there
is an `acaps-mcp` server in the `IFRC-GO-MCP` folder, but `.mcp.json` does not configure it,
and the 173 ACAPS rows in the database came from a CSV export. Giving that row a button
would be inventing a source the platform does not have.

### 5.3 The page-level controls

Above the list:

- **Rebuild dashboard layers** — runs `run_pipeline --only s06,s07`, exactly what the
  updater page's own rebuild does. Beside it, the count of successful pulls since the last
  rebuild finished, so the button says whether it is worth pressing: *"3 pulls since the
  last rebuild."* Zero pulls, and it still works; it just does not pretend to be needed.
- A link to the job log.

## 6. `PullJob` — the one new table

```
mcp_pull_job
  id
  kind             'pull' | 'rebuild'
  source           'ipc'            null for a rebuild
  dataset          'food_security'  null for a rebuild
  iso3             'SDN'            null for a rebuild or a global pull
  variant          ''               matches the source_sync row
  status           'queued' | 'running' | 'succeeded' | 'failed'
  requested_by     FK auth.User, null on delete
  requested_at     datetime
  started_at       datetime, null
  finished_at      datetime, null
  rows_written     integer, default 0
  payload_path     text, null       where the raw response was saved
  message          text             the error, or a one-line summary
  log              text             the command's output, for the job page
```

Indexed on `(source, status)`, which is the lock query, and on `(-requested_at)` for the log.

**This table is the attempt record and `source_sync` is the holding record.** A pull that
fails writes `failed` here and touches nothing there. That division is the reason the
freshness table can still be trusted after this feature exists.

Jobs are never deleted by the application. The log is a small table and an audit trail.

## 7. The fetchers

A new package `external_data/fetchers/`, mirroring `loaders/` in shape, registry and spirit.
A fetcher knows where a payload comes from; a loader knows what it means; neither knows the
other.

### 7.1 The contract

```python
class Fetcher:
    source = ""        # 'ipc'
    dataset = ""       # 'food_security'
    tool = ""          # the MCP tool this reproduces, for the record
    requires = ()      # ('IPC_API_KEY',) - checked before anything is called

    def plan(self, sync):
        """Yield one Call per upstream request this pull needs.

        A Call carries: url, params, the cache path to save under, and the
        `context` dict the loader will be given. Most sources yield one Call.
        IPC yields one per analysis it does not already hold.
        """
```

Four guarantees, matching the loaders' four:

- **saved before loaded** — the raw response is written to `mcp_cache/` and only then parsed,
  so a payload that breaks a loader is still on disk to look at.
- **one call at a time** — `plan()` is a generator and the runner consumes it serially. It is
  never gathered, mapped or threaded. See §9.
- **keyed, or refused** — a fetcher whose `requires` is unmet does not call anything and does
  not create a job; the button was disabled with that reason showing.
- **empty is a failure** — an empty response reaches the loader and trips `EmptyPayload`, and
  the job fails. No watermark moves. This is the existing guarantee and it is the one that
  makes an unattended pull safe.

### 7.2 What each fetcher calls

| Fetcher | Reproduces | Upstream | Key |
|---|---|---|---|
| `fewsnet.SeasonsFetcher` | `get_seasons` | `GET https://fdw.fews.net/api/season/?country_code=<ISO2>&page_size=50` | none |
| `fewsnet.PhasesFetcher` | `get_ipc_phases` | `GET https://fdw.fews.net/api/ipcphase/?country_code=<ISO2>&start_date=…` | none |
| `hdx.IdpsFetcher` | `get_idps` | `GET https://hapi.humdata.org/api/v1/affected-people/idps` | `HDX_API_TOKEN` |
| `hdx.RefugeesFetcher` | `get_refugees` | `GET https://hapi.humdata.org/api/v1/affected-people/refugees` | `HDX_API_TOKEN` |
| `ipc.FoodSecurityFetcher` | `list_analyses` + `get_areas_by_analysis` | `GET https://api.ipcinfo.org/analyses`, then `/areas/{id}/{period}` | `IPC_API_KEY` |

Two notes that will otherwise be rediscovered painfully:

**The `unhcr` rows are fetched from HDX, not from UNHCR.** `RefugeeLoader` records
`source='unhcr'` because the figures are UNHCR's, but the tool behind it is HDX HAPI's
`get_refugees`. So `unhcr/refugees` needs `HDX_API_TOKEN`, and there is no UNHCR key at all.
Two keys cover all four API sources.

**FEWS NET wants ISO2.** `source_sync` keys on ISO3 and `/api/season/` takes
`country_code` as ISO 3166-1 alpha-2, so the FEWS NET fetcher carries a small ISO3→ISO2 map
for the nine countries in scope. It is a lookup, not a library: an unmapped ISO3 raises
rather than guessing a two-letter code.

**HAPI paginates.** `callHapiApi` passes no limit and the endpoint's default applies, so the
fetcher follows pages until a short one comes back and concatenates `data` before saving. The
5,686 Sudan IDP rows are more than one page.

### 7.3 IPC, which is the one with real logic

`plan()` calls `/analyses?country=<ISO3>`, compares the returned analysis ids against
`sync.known_ids`, and yields a Call only for ids not already held. For each, it fetches
`/areas/{id}/C` — the current-situation period, matching the `-C` suffix on every file
already in `mcp_cache/ipc/`.

**The period comes from the analysis record, not from the filename.** `load_external`
recovers IPC's period by regex over the filename, and the existing `ipc/CAF-62439499-C.geojson`
names carry no `YYYY-MM` for it to find. The fetcher has the analysis metadata in hand and
passes `period_date` in `context` directly, which is both correct and one less convention to
maintain. Cache filenames keep the existing `<ISO3>-<analysis_id>-C.geojson` shape so the
folder stays uniform and a hand-run `load_external --period` still works on them.

An analysis that publishes an empty `FeatureCollection` — a projection update, as the CAF and
SSD notes in `source_sync` already record — trips `EmptyPayload`. That job is marked failed
with the analysis id in the message, and, because `known_ids` is only advanced by a
successful load, it will be retried next time rather than silently skipped. A retried
analysis that is empty every time is a source fact, and the note column is where it belongs.

## 8. `manage.py refresh_external`

```
refresh_external <source> <dataset> [--iso3 SDN] [--variant ''] [--job N] [--dry-run]
```

The command is the feature; the button is a caller. Run it from a terminal and it does the
same thing, which is how it gets tested and how it will be scheduled if that is ever wanted.

1. Resolve the `source_sync` row and the fetcher registered for `(source, dataset)`.
2. Refuse if `requires` is unmet, naming the missing setting.
3. Take the lock (§9), or refuse, naming the job that holds it.
4. Mark the job `running`.
5. For each Call the fetcher plans, serially: request with a 60-second timeout, save the raw
   body to `mcp_cache/`, then `loaders.base.load(loader, payload, iso3, context=…)`.
6. Sum rows written; mark `succeeded`, or `failed` with the exception text.

Output goes to stdout line by line and is captured into `PullJob.log`, so the job page can
show it the way the updater page shows a pipeline run.

`--dry-run` fetches and saves but passes `dry_run=True` to the loader, which reports what it
would write and writes nothing — the loader already supports this.

## 9. The lock, and the IPC rule

> **Never pull two IPC countries in parallel.** Recorded incident: the connection closed and
> the server stayed down for the rest of the session. — `CLAUDE.md`

A button in a browser is precisely how that happens again: two tabs, two countries, two
clicks. The rule is therefore enforced in code rather than in documentation.

- A **pull** is refused while any job with the same `source` is `queued` or `running`.
- A **pull** is also refused while a rebuild is running — a rebuild reads the tables a pull
  is writing.
- A **rebuild** is refused while any job at all is in flight.

The check and the transition to `running` happen in one `select_for_update()` transaction, so
two simultaneous requests cannot both pass it. A refused request is a message on the page,
not an error.

A job left `running` by a container restart is stale. The list shows a job running longer
than 30 minutes as **stuck**, with a reset action — the same affordance, and the same reason,
as `reset_stuck_job` in `insights/admin.py`.

## 10. How the button runs the work

`subprocess.Popen([... "manage.py", "refresh_external", ...], start_new_session=True)`, the
pattern `insights/admin.py:379` established. `start_new_session` matters and the comment in
`docker-compose.yml` says why: a detached child that outlives its worker otherwise reparents
to gunicorn's arbiter, which misreads its exit code and halts the server. `init: true` is
already set on the `web` service and covers the reaping.

The admin view creates the job row, launches the process, and redirects with a message. The
list auto-refreshes while any job is in flight and stops when none is. The job page polls the
same endpoint for the log.

## 11. Settings and keys

Added to `config/settings.py`:

```python
IPC_API_KEY = os.environ.get("IPC_API_KEY") or ""
HDX_API_TOKEN = os.environ.get("HDX_API_TOKEN") or ""
```

`get(X) or ""`, not `get(X, "")`: an empty value in `.env` must fall back rather than be
treated as a set-but-empty key, which is the trap `CLAUDE.md` records and which would
otherwise produce a 403 from HAPI instead of a clear "key not set" refusal.

Both are added to `env.example` with a comment naming where each is obtained, and passed
through the `web` service's `environment:` block in `docker-compose.yml`. They are secrets:
they belong in `.env`, which is not committed, and they are never echoed into a job log.
Where a key is absent, the button is disabled and reads *needs `IPC_API_KEY` in .env* — the
row still lists its freshness, because that fact does not depend on a key.

## 12. Verification

Tests live in `external_data/tests/` and `mcp/tests/`, and none of them touch the network.

**Fetchers**
- each fetcher requests the URL and parameters its MCP tool does, with the key attached where
  one is required
- the raw response is written to the expected path under `MCP_CACHE_DIR` before the loader is
  called
- a paginated HAPI response is followed to the end and concatenated
- IPC plans a Call only for analysis ids absent from `known_ids`, and passes `period_date`
  from the analysis record
- a fetcher with an unmet `requires` raises before any request is made

**The command**
- a successful run advances `source_sync` and marks the job `succeeded` with a row count
- an empty response raises `EmptyPayload`, marks the job `failed`, and **leaves
  `last_pulled_at` and `high_water_date` exactly as they were** — the regression this whole
  design turns on
- an HTTP error is caught, the job fails with the status in its message, and the saved
  payload (if any) is still on disk
- `--dry-run` writes nothing

**The lock**
- a second pull on the same source while one runs is refused, and no process is launched
- a pull on a different source is allowed
- a rebuild is refused while a pull runs, and a pull while a rebuild runs
- a job older than the stale threshold is reportable and resettable

**The admin**
- the section appears under its own heading with all 36 rows
- an API-backed row renders an enabled button; `excel`, `kobo` and `acaps` rows render the
  disabled control with a reason
- POSTing the button as a staff user creates a queued job; as an anonymous user it is refused
- the rebuild button reports the number of pulls since the last rebuild

**By hand, once, against the real APIs:** pull `fewsnet/seasonal_calendar/TCD` (no key) and
`unhcr/refugees/TCD` (keyed, and years out of date), and confirm `external_status` moves. The
UNHCR rows reading "never" are the honest first target.

## 13. Sequencing

1. `requests` in requirements; the two settings; `env.example`; compose.
2. `external_data/fetchers/base.py` — contract, registry, the Call type, the save step. Tests.
3. `fewsnet.py` — the unkeyed, single-call case, end to end. Tests.
4. `mcp` app: `PullJob`, migration, the lock, `refresh_external`. Tests.
5. `hdx.py`, including pagination. Tests.
6. `ipc.py`, including the analyses diff and `period_date`. Tests.
7. The admin section: proxy model, list, buttons, job page.
8. The rebuild button and its counter.
9. `CLAUDE.md`: the refresh route for a person is now the admin section; the agent's
   fetch-save-load path is unchanged and stays documented for sources with no fetcher.

Steps 2–6 are usable from the command line before any admin work exists, which is the point
of the ordering: the feature is verifiable before it has a button.

## 14. Rollback

Remove `mcp` from `INSTALLED_APPS` and the section disappears; the data and `source_sync` are
untouched, because nothing in this design writes to them except loaders that already existed.
`mcp_pull_job` can be dropped with its migration. `external_data/fetchers/` is additive and
imported only by `refresh_external`. The MCP-through-Claude-Code path keeps working
throughout and is not modified.

## 15. Known limits, stated rather than discovered later

- **This does not use the Model Context Protocol.** The section is named for the family of
  sources and the office's vocabulary. The pulls are HTTPS requests to the same upstream APIs
  the MCP servers wrap. If one of those servers ever stops being a pass-through — adds
  filtering, reshaping or its own pagination — its fetcher will drift from its tool, and the
  fetcher's `tool = …` attribute is the breadcrumb for whoever checks.
- **Four sources have fetchers; four do not.** `excel`, `kobo` and `acaps` are file-based, and
  `ch` shares IPC's fetcher because Cadre Harmonisé analyses come from the IPC API.
- **No retry and no backoff.** A failed pull is a failed job with its error kept, and the
  operator presses the button again. Automatic retry against a source that has already gone
  down once under load is not obviously the safe default.
- **Rate limits are unknown.** None of the four publishes one that this project has hit, but
  the serial-only rule and the absence of a scheduler are what keep the volume low.
- **The updater page still reads file mtimes.** `updater/views.py:external_layers()` reports
  layer freshness from files on disk and a hand-written list, not from `source_sync`. After
  this feature the MCP section is the authoritative freshness view and the two will disagree
  in wording. Reconciling them is a small, separate job, deliberately not bundled here.
- **A pull does not move the dashboard.** That is the design, and the rebuild button is the
  answer. Someone who pulls and does not rebuild has fresher data in the database than on the
  map, which is exactly the state the second button exists to let them choose.
