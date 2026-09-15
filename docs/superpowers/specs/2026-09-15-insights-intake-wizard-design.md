# Documents to insights: a guided intake, and the end of the `/work` peg

## 1. Why

Two problems, one screen between them.

**The insights admin has no path through it.** The Community Insights section lists five
screens — Insights, Insight folders, Insight uploads, Extraction jobs, and the codings
inline — and nothing says which order to drive them in. The sequence that actually works is:
register a folder or upload a file, run "Catalogue and queue for extraction", find the job it
made, run "Run extraction now", refresh the changelist until the numbers stop moving, then go
to the Insights table and filter by that job. Six screens and a refresh loop, none of which is
written down on the screens themselves. A person who does this once a month will not remember it.

**Extraction is invisible while it runs.** `ExtractionJobAdmin.run_extraction_now` launches a
detached process and tells the user to refresh a changelist. The progress that exists —
`documents_done` against `documents_total`, and a log file at
`mcp_cache/insights/job-<id>.log` — is written but never shown. The `updater` app has had a
live progress bar with a streaming log since it was built; the insights side has a changelist
and a browser refresh key.

**And the source of documents is pegged to one mount.** `docker-compose.yml` mounts the parent
folder at `/work` with the host side hardcoded to `..`; the admin folder browser offers that
path and `MEDIA_ROOT` and nothing else; and three separate user-facing error messages tell the
reader that "`/work` covers the whole SUDAN Ops folder". That sentence is true of exactly one
deployment. This platform is meant to run in other places, against other folders.

## 2. Goals

1. One front door for turning documents into insights, laid out in the order it is done, with
   every step visible on the page rather than remembered.
2. Bringing documents in must work from a **native file or folder window on the operator's own
   computer**, with no container path, no mount and no `.env` entry involved.
3. Extraction progress must be watchable while it runs, and closing the tab must not kill it.
4. A reviewer must be able to read everything a run produced and correct it **without leaving
   the review page**.
5. No deployment-specific path may appear in code or in a message shown to a user.

## 3. Non-goals

- **The `updater` app is not touched.** Spec `2026-09-10-community-insights-design.md` §14 calls
  for deleting it and absorbing the pipeline run into Admin. That remains open; see §12.
- **`s04_events` still deletes curated rows.** Out of scope here, as it was there.
- No change to the extraction contract, the four loader gates, the taxonomy, the public API or
  the dashboard.
- No job scheduler, queue backend or worker process. The detached-child model stays.

## 4. Decisions taken

| Decision | Why |
|---|---|
| The browse buttons are native `<input type="file">` and `<input type="file" webkitdirectory>` | A web page cannot read a folder on the operator's machine by path. `webkitdirectory` opens a real OS folder window and hands over the files inside. It uploads rather than reading in place — that is the trade, and it is what makes the wizard work in any deployment with no mount at all. |
| Files are uploaded **one HTTP request per file**, sequentially | Django 5.0's `DATA_UPLOAD_MAX_NUMBER_FILES` defaults to 100, so a 300-file POST is rejected outright. One request per file also gives per-file error reporting and a progress bar that is honest rather than interpolated. |
| Extraction progress is **polled**, not streamed | An SSE stream holds one of only 8 gunicorn threads (2 workers × 4 threads) for the whole length of an LLM run. Polling costs nothing, survives a slept tab and a proxy timeout, and resumes when the wizard is reopened. |
| The extraction child stays **detached** | `start_new_session=True` and compose's `init: true` exist because a gunicorn worker recycling mid-run used to kill extractions and could take the web server down through `Arbiter.reap_workers()`. Running extraction inside the request — the way `updater._stream_command` does — would mean closing the tab kills a paid-for run. |
| Inline editing reuses **`InsightPlaceForm` itself**, fetched per row | Place resolution is derived, never typed: the form's `clean()` refuses a state from the wrong country, and its `save()` leaves an untouched location exactly as the extractor wrote it, including rows below ADM2 the dropdowns cannot express. Reimplementing that in the review page would lose both guarantees. |
| `ExtractionJob`, `InsightFolder` and `InsightUpload` stay registered but come off the index | "Reset stuck job to queued" and the job log are the only recovery path when a container restart kills a running extraction. Unregistering them would be a regression. |

## 5. The two front doors

The Community Insights admin section lists exactly two entries:

| Entry | What it is |
|---|---|
| **Part 1 — Documents → insights** | The wizard: bring in → preview → extract → review & publish. |
| **Part 2 — Insights** | The statement table: type one by hand, search, audit anything published. |

`ExtractionJob`, `InsightFolder` and `InsightUpload` are hidden from the index by overriding
`ModelAdmin.get_model_perms` to return `{}` — the documented idiom for dropping a model from
the app list while leaving every URL, view, action and permission working. Deliberately *not*
`has_module_permission`, which also blocks the app index page and whose effect on the
changelist is not what is wanted here. They are linked from the wizard where
they are relevant: the job screen from the extract step's error banner, the folder screen from
the intake step as "or use a folder already on the server".

## 6. Part 1a — bringing documents in

### 6.1 The two buttons

```
Choose files    <input type="file" multiple accept=".pdf,.docx">
Choose a folder <input type="file" webkitdirectory>
```

Both open a native OS window. `webkitdirectory` is supported in Chrome, Edge, Firefox and
Safari; it returns **every** file in the folder, recursively, including `.DS_Store`, images and
spreadsheets.

**JavaScript filters to `.pdf` and `.docx` before anything is sent.** This is not cosmetic: a
folder of field photographs beside the reports would otherwise upload gigabytes to be thrown
away server-side. The skipped files are listed on the preview with their reason, so the filter
is visible rather than silent.

`File.webkitRelativePath` carries the folder's internal structure
(`DTM Round 12/Chad/report.pdf`). It is kept as the upload's label so the preview and the
review page can group by it.

### 6.2 The preview, in two stages

The preview is the step the operator asked for by name — "in view only one can see what files
will be read" — and it has two halves that answer two different questions.

**Stage 1 — before upload. What will be sent.** The moment the native window closes,
JavaScript already has the file list; nothing has left the machine. The page renders it
immediately: name, size, folder path, and every skipped file greyed out with its reason. The
operator can clear the selection and pick again at no cost.

**Stage 2 — during upload. What was actually read.** Each file is sent in its own request and
catalogued as it lands, and its row fills in live with one of:

- `12 pages` — catalogued, attached to the job;
- `already catalogued (identical file)` — `catalogue_file`'s sha1 dedup fired, the existing
  `Document` is attached to this job rather than a second one being made;
- `could not be read: <reason>` — a corrupt or password-protected PDF. **The batch continues.**

### 6.3 The endpoints

All four are mounted through `ExtractionJobAdmin.get_urls()` and wrapped in
`admin_site.admin_view`, the pattern `place-options/` and `folder-browse/` already use.

| Method + path | Does |
|---|---|
| `POST wizard/batch/` | Creates an `ExtractionJob` with `status="collecting"` and the batch label. Returns its id. |
| `POST wizard/batch/<id>/file/` | One file. Writes it under `MEDIA_ROOT/insights/<job id>/<relative path>`, creates an `InsightUpload` row, calls `catalogue_file`, attaches the `Document` to the job. Returns that file's outcome. |
| `POST wizard/batch/<id>/ready/` | Sets `documents_total` from the attached documents and `status="queued"`. Redirects to the extract step. |
| `GET  wizard/job/<id>/` | The wizard itself, showing whichever step the job's status puts it at. |

One `ExtractionJob` per batch. Today `InsightUploadAdmin.save_model` creates one job per
uploaded file, which makes a ten-file drop into ten jobs to drive separately; that behaviour is
kept for the single-upload screen and replaced for the wizard.

### 6.4 The other route in, unchanged

A deployment with a large archive already on a mounted share should not push it through a
browser. `InsightFolder` plus "Catalogue and queue for extraction" remains exactly as it is,
linked from the intake step as a secondary option. §9 makes its roots configurable.

## 7. Part 1a — the extract step

"Start extraction" runs the existing `run_extraction_now` logic: validate `get_extractor()`
once up front, refuse to launch a second extraction of an already-`running` job, set the job to
`running` and save **before** launching, then `Popen` a detached
`manage.py extract_insights --job N` with its output to `mcp_cache/insights/job-<id>.log`.

The page then polls `GET wizard/job/<id>/progress/` every two seconds. That endpoint returns:

```json
{"status": "running",
 "done": 7, "total": 22,
 "proposed": 41, "unverifiable": 3, "skipped_reviewed": 0,
 "log_tail": "...last 4 KB of job-7.log...",
 "last_change": "2026-09-15T10:14:02+00:00"}
```

`last_change` is the job's most recent write, used for the stall warning below. The log tail is
read from the end of the file with a seek, never by reading the whole file — a long run's log
grows without bound.

**Three end states, three behaviours:**

- `loaded` → the step completes and the wizard advances to review.
- `failed` → a red banner with the job's own log message. `extract_insights` already catches a
  transport/SDK failure, flushes the problems recorded before it, marks the job `failed` and
  re-raises as `CommandError`. Only the exception's type and message are ever recorded, never
  its repr and never the request object some SDK exceptions carry — which can carry the
  `Authorization` header, which carries `LLM_API_KEY`. The banner shows what the log holds and
  nothing more.
- `running` with no change for 10 minutes → an amber "no progress since HH:MM" notice with a
  **Reset to queued** button wired to the existing `reset_stuck_job` action. A process killed
  outright — `docker compose restart web` kills a detached child with no exception anywhere in
  this codebase to catch — cannot be detected, only reported. The notice says so; it does not
  reset anything by itself, because nothing tracks a pid and guessing wrong would let two
  extractions of one job run at once.

Closing the tab does not stop the run. Reopening `wizard/job/<id>/` rejoins it at whatever step
its status puts it at.

## 8. Part 1b — review and publish

Everything the job produced, `Insight.objects.filter(job=job)`, grouped by source document and
ordered by page. Each row is read-only: the quote in full, its themes, the resolved place, the
page, the confidence, and whether the place matched a polygon or is country-only.

**Edit expands the row in place.** The panel is fetched on click from
`GET wizard/insight/<id>/edit/`, which renders `InsightPlaceForm` plus the `InsightCoding`
inline for that one insight, and posts back to the same URL. Lazy-fetching is what keeps a
200-statement page light in read mode; rendering every form up front would not be.

Everything `InsightPlaceForm` guarantees holds unchanged here, because it *is* the form:

- the country / state / district dropdowns, with choices rebuilt server-side on every bound
  form — a `ChoiceField` filled in by JavaScript has no valid choices as far as the server is
  concerned, and without the rebuild every POST would fail;
- `clean()` refusing a state that is not in the selected country, the rule that once put
  Sudanese reporting on Amhara;
- `save()` re-deriving the five machine columns **only when the selection actually changed**,
  so a row placed at ADM3 is not silently dragged up to the ADM2 the dropdowns can express, and
  a `match_method` of `name` is not restamped `pcode` because someone fixed a typo.

`place_picker.js` is loaded once by the review page rather than per panel.

**Publishing is a decision per statement.** Checkboxes drive **Publish selected** and **Reject
selected**, which call the same code as `InsightAdmin.publish_selected` and `reject_selected` —
extracted to `insights/review.py` so there is one implementation and both callers use it. Both
stamp `reviewed_by` and `reviewed_at`. Nothing publishes itself, and there is no publish-all.

## 9. Ending the `/work` peg

`SOURCE_ROOT` is already read from the environment with a working default. The peg is in five
other places:

| Where | Now | After |
|---|---|---|
| `docker-compose.yml:141` | `- "..:/work:ro"` | `- "${SOURCE_HOST_DIR:-..}:/work:ro"` |
| `insights/admin_views._roots()` | hardcodes `SOURCE_ROOT` and `MEDIA_ROOT`, labelled `Source documents (/work)` | built from `settings.INSIGHT_DOCUMENT_ROOTS` |
| `InsightFolder.clean()` | "…`/work` covers the whole SUDAN Ops folder" | lists the roots this deployment actually has |
| `intake.catalogue_folder()` | the same sentence | the same fix |
| `admin_views.folder_browse()` | the same sentence | the same fix |

**The new setting:**

```python
# Folders the insights folder browser may offer, innermost first. A path-separator
# list (";" on Windows, ":" elsewhere) so a deployment can name several.
# `or` rather than a default argument: an empty value in .env must fall back to
# the default, not be read as an empty list.
INSIGHT_DOCUMENT_ROOTS = [
    Path(p) for p in (os.environ.get("INSIGHT_DOCUMENT_ROOTS") or "").split(os.pathsep) if p
] or [SOURCE_ROOT, MEDIA_ROOT]
```

A root is labelled by its own directory name, not by a literal written in the source. Roots
that do not exist at request time are dropped from the offer, as they are today.

**The guard does not weaken.** `folder_browse` still resolves a path before testing it, so
`..` is collapsed and `/work/../etc` is refused rather than passing a prefix comparison, and a
path outside every root is still a 400. It offers configured roots; it does not become a
filesystem browser. The wizard's own route needs none of this — a native upload has no
container path at all.

`/work` stays read-only. Uploads land under `MEDIA_ROOT` inside `/app`, as they do now.

## 10. Data model, settings and repository changes

- **`ExtractionJob.status` gains `collecting`** — files arriving, not yet queued. One
  `AlterField` migration for the changed `help_text`, which now reads
  `collecting / queued / running / loaded / failed`.
- **`ExtractionJob.label`** — a `TextField`, nullable: what the batch was
  (`folder: DTM Round 12`, `4 files`), so the wizard's job list is readable without opening each
  one. Not derived, because the folder a browser uploaded from is not a path the server can
  recover any other way.
- **`INSIGHT_DOCUMENT_ROOTS`** in settings, per §9.
- **`SOURCE_HOST_DIR`** documented in `env.example` beside the existing path settings.
- **`media/` is added to `.gitignore`.** `/app` is bind-mounted to the project folder, so every
  file uploaded through Admin currently lands inside the working tree as an untracked file
  waiting to be committed by accident. This is true today, before any of this work; the wizard
  makes it far easier to hit.
- Templates live in `insights/templates/insights/`, which `APP_DIRS = True` already finds.
  Wizard pages extend `admin/base_site.html` so they carry the admin's own chrome and login.

No change to `Insight`, `InsightCoding` or `InsightFolder`.

## 11. Verification

Tested with the Django test client alongside the existing `insights/tests/`:

1. **Batch open** creates a `collecting` job with its label.
2. **Per-file upload** catalogues a PDF and attaches it; a second upload of the *same content
   under a different name* returns `already catalogued` and attaches the existing `Document`
   rather than creating a second one.
3. **A corrupt file** returns its own error row, the request is a 200, and a good file uploaded
   after it still catalogues — the batch is not taken down.
4. **Ready** sets `documents_total` to the number of attached documents and the status to
   `queued`.
5. **The progress endpoint** reports a running job's counters, tails the log from the end, and
   reports `failed` with the job's log message after a failed run.
6. **The inline edit panel** renders `InsightPlaceForm` for one insight; posting a changed
   district re-derives `admin_pcode`, `admin_level`, `match_method`, `lat` and `lon`; posting
   with the place untouched leaves an ADM3 row's p-code and a `name` match_method exactly as
   they were.
7. **Publish and reject** stamp `reviewed_by` and `reviewed_at` and touch only the selected rows.
8. **`folder_browse`** offers the configured roots, refuses a path outside them, and refuses a
   traversal (`<root>/../etc`) — with `INSIGHT_DOCUMENT_ROOTS` overridden in the test, proving
   the setting is what drives it and `/work` is not.
9. **No user-facing string names a deployment's own path.** With `INSIGHT_DOCUMENT_ROOTS`
   overridden to a temporary directory, the messages raised by `InsightFolder.clean()`,
   `catalogue_folder()` and `folder_browse()` name that directory and do not contain `/work`.

The native pickers are browser behaviour and are not unit-testable. What is tested is that the
server does the right thing with what they send. The wizard is walked once in a real browser
before the branch is finished, per the verification loop this project already uses.

## 12. Known limits, stated rather than discovered later

- **Upload means copying.** A 300-PDF folder is a real upload over the operator's connection,
  and a slow link makes it slow. The mounted-folder route (§6.4) stays for archives already on a
  server; it is simply no longer the default.
- **A folder picked natively cannot be re-read later.** The browser gives file contents and a
  relative name, never a path the server could return to. A folder that must be re-scanned as it
  grows is an `InsightFolder`, not a wizard upload.
- **`webkitdirectory` is a prefixed non-standard attribute.** Every current browser supports it,
  but it is not in a finished specification and could in principle be removed. The single-file
  `multiple` input is standard and would remain.
- **A killed extraction still cannot be detected.** §7's stall notice reports a lack of
  progress; it does not know whether the process is gone or merely slow, because nothing tracks
  a pid. Automatic detection remains the job-machinery problem it already was.
- **The wizard does not supersede §14 of the community-insights spec.** That section says the
  `updater` app is deleted and its pipeline run becomes an Admin action "reusing the same
  job-and-progress machinery all three now need". This work builds that machinery for
  extraction only and leaves `/updater/` running. §14's absorption is still open, and is now
  cheaper: the progress endpoint and polling UI built here are what it would reuse. Its
  `STEP_BANDS` drift guard must still be carried across whenever that happens — losing it would
  silently freeze a progress bar when a pipeline step is renamed.
- **Two people can drive the same job at once.** The double-click guard refuses a second
  extraction of a `running` job, which covers the damaging case. Two reviewers publishing from
  the same review page will simply both succeed, last write winning on `reviewed_by` — the same
  behaviour the existing changelist actions have.
