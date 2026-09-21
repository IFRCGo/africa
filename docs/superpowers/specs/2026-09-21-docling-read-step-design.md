# Reading documents properly: a Docling conversion step between intake and the model

## 1. Why

**The model has never read a PDF. It reads PyMuPDF's guess at one.**

`insights/intake.py:_pages_of()` opens each file at upload time and calls
`page.get_text("text")` for a PDF, or joins `Docx(...).paragraphs` for a Word file. Those
strings become `DocumentText` rows, and `extract_insights.py` reads them straight back out and
posts them to the model as `--- page N ---` blocks. Nothing about the original document's
structure survives that trip:

- **Reading order is the PDF's internal order, not the page's.** A two-column situation report
  interleaves the columns. A sidebar lands in the middle of a paragraph. The model then quotes
  a sentence that never existed as a sentence, and `verify.quote_is_verbatim` dutifully
  confirms it, because the mangled string is exactly what we stored.
- **Tables collapse into loose runs of numbers.** The displacement tables that carry the actual
  figures come out as a column of digits with no row or column labels attached to them. This is
  the single largest source of figures the model either misreads or declines to extract.
- **A scanned report yields nothing, silently.** `get_text("text")` on a page with no text
  layer returns `""`. The document is catalogued, attached to a job, sent to the model, costs
  money, and produces zero insights. Nothing in the job log distinguishes "this report had
  nothing to say" from "we could not read a word of it".

Docling parses layout before it emits text: reading order, headings, lists, and tables as
tables. With OCR on it also reads the scanned reports we currently discard in silence.

**And step 2 of the wizard is a promise the wizard does not keep.** `wizard.py:STEPS` calls it
"Check what will be read", and `step_links()` gives it no URL at all — the comment says the
preview *is* the intake page. What that preview shows is the list of filenames the browser
handed over. It never shows a word of text. A person cannot presently check what will be read,
because what will be read is not produced until the model is already being paid.

## 2. Goals

1. The text the model reads is Docling's, for every document Docling can convert.
2. Conversion is a **visible, named step the operator triggers** — "Read these documents" —
   between choosing files and paying for extraction, watchable while it runs and surviving a
   closed tab exactly as extraction already does.
3. Step 2 shows the **actual converted text**, per document, before the extract button is live.
4. A document Docling cannot convert falls back to PyMuPDF and is **visibly badged** as having
   done so. One bad file never stops a batch.
5. `verify.quote_is_verbatim` keeps working against markdown — a quote the model returns
   without markup still matches a stored line that carries it.
6. Nothing already published changes meaning: `quote_sha1`, the natural key on `Insight`, is
   byte-for-byte what it is today.

## 3. Non-goals

- **The extraction contract, the four loader gates, the taxonomy, the review page and the
  public API are untouched.** `insights/extractors/` is not opened at all. The model's input is
  better text in the same shape.
- **The pipeline (`data_pipeline/steps/`) is untouched.** `s02_extract_text` keeps using
  PyMuPDF for the UNHCR archive. Only `family="insight_source"` documents go through Docling.
- No GPU, no queue backend, no worker process. The detached-child model stays.
- No re-conversion of documents already catalogued by past jobs. Existing rows stay as they
  are until somebody deliberately re-reads their batch, and §9 refuses even that where
  insights already depend on the old text.

## 4. Decisions taken

| Decision | Why |
|---|---|
| Docling runs **inside the web image**, not as a sidecar | Operator's call. A plain import, no network hop, no second service to keep alive. Paid for in image size (§11) and in RAM shared with gunicorn. |
| **OCR is always on** | Operator's call. Scanned reports are the largest silent loss today, and a per-page "was this empty?" retry would convert some documents twice for an inconsistent result. Every page takes the slow path; this is why conversion is a background job and not part of upload. |
| Per document, **Docling first, PyMuPDF only if Docling fails** | Operator's call. The fallback is never sticky: re-running the read step attempts Docling again on every document, including ones that fell back last time. |
| Intake **keeps its PyMuPDF pass** as a placeholder | Not a hedge on the rule above — a hazard fix. `data_pipeline/steps/s02_extract_text.py:31` selects `Document.objects.filter(texts__isnull=True)`, so a document left textless between intake and conversion would be picked up by any pipeline run and fail there on a `media/…` path it cannot resolve. Intake's text is also what `document_date.infer` reads a report date out of. Docling **replaces** those rows; the model never sees them when Docling succeeds. |
| Conversion is its **own management command, launched detached** | `batch_file` is one synchronous HTTP request per file. With OCR on, a 40-page report is minutes. Conversion inside the upload request would time out the browser and lose the batch. |
| The converted markdown is **written to disk before it is loaded** | The rule CLAUDE.md already states for external data — fetch, save, then load. A re-read can be served from `mcp_cache/insights/converted/` without paying for OCR twice. |
| Markdown folding lives **inside `quote_is_verbatim` only** | `quote_sha1` is a unique-constraint natural key (`insights/models.py:248`). Widening `normalise()` would change the hash of every future quote, so a re-extraction would insert duplicates beside published rows instead of matching them. Folding the haystack and the needle at comparison time costs nothing and migrates nothing. |
| Conversion **refuses a document that already has insights** | Replacing page text under an existing `Insight` would invalidate the quote it was verified against, with no way to tell afterwards. Refused per document, with a reason in the log — not per job, because a `Document` can belong to several jobs. |
| Conversion records live in the **`insights` app**, not `data_track` | Same reason `ExtractionJob.documents` does: additive, and `data_track` stays a pipeline-owned table. Conversion is per document, not per page, so it does not belong on `DocumentText` anyway. |

## 5. The read path, before and after

Today:

```
pick files ──▶ batch_file ──▶ catalogue_file ──▶ _pages_of()  ──▶ DocumentText
                                                  PyMuPDF                 │
                                                                          ▼
                                                            extract_insights ──▶ model
```

After:

```
pick files ──▶ batch_file ──▶ catalogue_file ──▶ _pages_of()  ──▶ DocumentText
                                                  PyMuPDF          (placeholder)
                                                                          │
              ┌───────────────────────────────────────────────────────────┘
              ▼
   "Read these documents"  ──▶ convert_documents --job N  ──▶ Docling ──▶ converted/<sha1>.json
              (step 2)                    detached                │              (on disk)
                                                                  ▼
                                                        DocumentText replaced
                                                                  │
                                       preview ◀──────────────────┤
                                                                  ▼
                                                    extract_insights ──▶ model
```

## 6. `insights/convert.py` — the conversion unit

One public function, testable without the wizard:

```python
def convert_document(document, path, reload_only=False) -> Conversion
```

It returns a `Conversion` row (§10) and never raises for a bad document — a failure is a
result, in the same spirit as `verify.quote_is_verbatim` returning `False` for a missing page.

1. **Refuse if insights depend on this document's text.**
   `Insight.objects.filter(document=document).exclude(status="rejected").exists()` → return a
   `Conversion` with `engine="skipped"` and a reason. Nothing is written.
2. **Serve from cache when asked.** With `reload_only`, read
   `mcp_cache/insights/converted/<sha1>.json` and go straight to step 5. Absent file → recorded
   as a failure, not an exception.
3. **Convert.** `DocumentConverter` with `PdfPipelineOptions(do_ocr=True)`,
   `artifacts_path=settings.DOCLING_ARTIFACTS_PATH`, `ocr_options.lang=settings.DOCLING_OCR_LANGS`,
   `document_timeout=settings.DOCLING_TIMEOUT_SECONDS`, and
   `page_range=(1, settings.DOCLING_MAX_PAGES)` — the same 40-page ceiling
   `s02_extract_text.MAX_PAGES` has held since the pipeline was built, which matters far more
   here because every page is OCR'd.
4. **Split per page** (§7) and write both artifacts: `<sha1>.json`
   (`{"engine", "docling_version", "converted_at", "pages": [{"page": n, "markdown": …}]}`,
   the re-loadable one) and `<sha1>.md` (the whole document, for a person to open).
5. **Replace the rows, atomically.** Inside one `transaction.atomic()`: delete this document's
   `DocumentText`, `bulk_create` the new pages, update `Document.pages`, and write the
   `Conversion` row. Atomic because a crash between the delete and the create leaves the
   document textless — which is exactly the `s02` hazard §4 exists to avoid.
6. **Re-date if the document has no date.** When `document.report_date is None`, re-run
   `document_date.infer(path, pages, _pdf_metadata(path))` over the converted pages and write
   the result if it is confident (`guess.date and not guess.needs_person`), with
   `date_source=guess.source`. This is the payoff for OCR on a scanned report: intake could not
   read a date out of an empty string, and now it can.

On any exception from Docling: the existing PyMuPDF rows are left exactly where they are, and
a `Conversion` is written with `engine="pymupdf"`, `ok=False` and `message=f"{type(exc).__name__}: {exc}"`
— type and message only, never the repr, the same rule `extract_insights.py` already keeps.

## 7. Per-page markdown, and page numbers

Page numbers are load-bearing: the model cites them, `verify` looks the page up, and the
review page groups by them. Docling gives page provenance on every item
(`ProvenanceItem.page_no`), and `docling_core`'s markdown serializer takes a page filter:

```python
MarkdownDocSerializer(doc=doc, params=MarkdownParams(pages={n})).serialize().text
```

So page *n* of the stored text is exactly the items Docling placed on page *n* of the PDF, in
reading order. Two consequences to state rather than discover:

- **An item spanning a page break appears on both pages.** `iterate_items` yields an item if
  *any* of its provenances matches the page filter, so a table running from page 3 to page 4 is
  serialised into both. This is harmless and mildly helpful: a quote from it verifies against
  whichever page the model cites.
- **A DOCX has no page provenance,** so the existing convention holds unchanged — the whole
  body is page 1, as `_pages_of()` already does, with the same comment explaining why.

`Document.pages` is updated to the converted page count, which for a document past the 40-page
ceiling will be lower than the file's true length. That is already true of every pipeline
document and is what the preview shows.

## 8. The step: "Read these documents"

Step 2 stops being the intake page's scroll target and becomes a page of its own,
`wizard_read.html`, modelled directly on `wizard_extract.html` — the same polling loop, the
same log tail, the same stall warning. Its label in `wizard.STEPS` changes from "Check what
will be read" to **"Read these documents"**, because it is now an action a person takes rather
than a thing they are invited to have already done.

- **Before:** the documents in the batch, and one button, "Read these documents".
- **During:** `done / total`, the tail of `job-<id>-convert.log`, and the current filename.
- **After:** one block per document — the engine badge (**Docling** / **raw text — Docling
  failed**, with the failure message), the page count, and the converted markdown rendered in a
  scrollable panel. Then **"Continue to extract"**.

That button is what moves the job to `queued`. Conversion finishing does **not** do it: if
completion set `queued` directly, reopening the job would route straight past the preview to
step 3, and step 2 would once again be a step nobody can stand on.

New endpoints on `DocumentsToInsightsAdmin.get_urls()`, alongside the existing ones:

| Name | Does |
|---|---|
| `insights_wizard_read` | `POST` — launches `convert_documents --job N` detached, same `Popen(start_new_session=True)` as `wizard.extract` |
| `insights_wizard_read_done` | `POST` — `converted` → `queued`, the Continue button |

`wizard.progress` is unchanged in shape; it picks its log file from the job's status
(`log_path(job, stage)`), so one polling endpoint serves both steps.

The command behind the button is `manage.py convert_documents --job N`, mirroring
`extract_insights --job N` line for line: the same per-document loop, the same
`_flush_problems` discipline, the same `CommandError` on a run-level failure so a direct
`docker compose exec` invocation exits non-zero. It takes one extra flag,
`--reload-from-cache`, which loads `converted/<sha1>.json` for every document instead of
calling Docling — the "load without re-fetching" half of the rule §4 borrows from the external
data route, and the fastest way to rebuild `DocumentText` after a database reset.

## 9. Job states

`ExtractionJob.status` is a free-text field with a `help_text` that lists the vocabulary
(`insights/models.py:147`). Three values are added and one existing meaning is narrowed:

| Status | Means | Step |
|---|---|---|
| `collecting` | files still arriving | 1 |
| `collected` | **new** — files in, not yet read | 2 |
| `converting` | **new** — Docling is running | 2 |
| `converted` | **new** — read, waiting for the operator to look | 2 |
| `convert_failed` | **new** — the read run itself died; press Read again | 2 |
| `queued` | **narrowed** — converted and ready to extract | 3 |
| `running`, `failed`, `loaded` | unchanged | 3, 3, 4 |

Callers that must change because they create `queued` jobs directly:
`wizard.batch_ready` (→ `collected`), `intake.catalogue_folder` (→ `collected`),
`InsightUploadAdmin` at `insights/admin.py:268` (→ `collected`), and
`InsightFolderAdmin`'s success message at `:217`, which currently says "queued".
`ExtractionJobAdmin.reset_stuck_job` gains the second case: `converting` → `collected`.

`documents_done` is reused for conversion progress — the stages are strictly sequential and
`extract_insights.py` already resets it to `0` at the top of its own run, so no counter is
added. `convert_documents` resets it the same way.

A per-document Docling failure does **not** fail the job. `convert_failed` is only for a run
that died outright (the command raised, or the process was killed) — recovered exactly as a
stuck extraction is.

## 10. Data model

One new model, in `insights/models.py`:

```python
class Conversion(models.Model):
    """What happened when we tried to read one document, and with what."""
    document   = models.OneToOneField("data_track.Document", on_delete=models.CASCADE,
                                      related_name="conversion")
    job        = models.ForeignKey(ExtractionJob, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="conversions")
    engine     = models.TextField()        # docling / pymupdf / skipped
    ok         = models.BooleanField(default=False)
    pages      = models.IntegerField(default=0)
    markdown_path = models.TextField(null=True, blank=True)
    docling_version = models.TextField(null=True, blank=True)
    message    = models.TextField(null=True, blank=True)
    converted_at = models.DateTimeField(auto_now=True)
```

`OneToOneField`: a document has one current state of being-read, and a re-read overwrites it.
`job` is `SET_NULL` so deleting a batch does not erase the record of how its documents were
read. `data_track` is not touched.

**After migrating, `docker compose restart web`.** CLAUDE.md's standing warning applies with
full force here: gunicorn never autoreloads, and a worker that booted before the table existed
will not see it.

## 11. Settings, build and cost

`config/settings.py`, following the house rule (`get(X) or default`, so an empty `.env` value
falls back rather than reading as empty):

| Setting | Default | For |
|---|---|---|
| `DOCLING_ENABLED` | `True` | Off ⇒ the read step reports "Docling is disabled" per document and leaves PyMuPDF text. Keeps the test suite and a thin deployment honest. |
| `DOCLING_OCR_LANGS` | `en` | Comma-separated, passed to EasyOCR. Arabic and French reports are in scope for this deployment; adding them is a `.env` edit, not a code change. |
| `DOCLING_MAX_PAGES` | `40` | Mirrors `s02_extract_text.MAX_PAGES`. |
| `DOCLING_TIMEOUT_SECONDS` | `900` | Per document. A pathological scan must not hold a batch for ever. |
| `DOCLING_ARTIFACTS_PATH` | `/opt/docling/models` | Where the build baked the weights. |

`Dockerfile`, in this order so Docker caches the expensive layers:

1. `pip install torch --index-url https://download.pytorch.org/whl/cpu` **before** the
   requirements file. Docling depends on torch, and the default PyPI wheel drags in the CUDA
   runtime — around 2GB of GPU libraries that cannot be used in this container.
2. `docling` added to `requirements.txt`, pinned exactly like every other line there.
3. `RUN HOME=/opt/docling docling-tools models download` — layout, tableformer and the OCR
   weights baked into the image, roughly 500MB. Without this the *first* click on "Read these
   documents" downloads them inside a detached subprocess, with no progress anywhere a person
   can see it, and fails outright on a machine with no internet.

Expect the web image to go from roughly 400MB to 2.5–3.5GB, and a no-cache rebuild to take
minutes rather than seconds. Code-only rebuilds are unaffected — they land after these layers.

Runtime cost, to be measured in verification rather than asserted: OCR on CPU is the dominant
term, and a 40-page report should be assumed to take minutes, not seconds.

## 12. Quote verification against markdown

`verify.py` gains one private function and one line in `quote_is_verbatim`:

```python
def _fold_markup(text):
    """Drop the markers Docling's markdown adds, so a quote of the words matches."""
```

It removes emphasis runs (`**`, `__`, `*`, `_`), leading heading hashes and list bullets,
table pipes (replaced with a space, so cells do not weld together), and link syntax, keeping
the link text. Applied to **both** the needle and the page text, after `normalise()`.

`normalise()` itself, and therefore `quote_sha1()`, is **unchanged** — that is the whole point
of putting the fold here. `insights/contract.py:86` and `:140`, which compare a written value
against the quote with `normalise`, are also unaffected.

`insights/prompts/extract_insights.md` gains one sentence: the page text is markdown, and a
quote should carry the document's words, not its markup.

## 13. Verification

Existing tests that must be updated, with what breaks:

| File | Why |
|---|---|
| `test_wizard_steps.py` | `step_links` now gives step 2 a URL and routes four new statuses |
| `test_wizard_batch.py` | `batch_ready` produces `collected`, not `queued` |
| `test_wizard_extract.py` | extraction launches from `queued`, which now means converted |
| `test_intake.py` | `catalogue_folder` produces `collected` |
| `test_verify.py` | folding is new behaviour on an existing function |

New tests:

- `test_convert.py` — a fake converter injected via `DOCLING_ENABLED`/a seam in `convert.py`,
  covering: rows replaced per page; the atomic delete-and-create; a raising converter leaving
  the PyMuPDF rows intact with `ok=False`; a document with a published insight refused; a null
  `report_date` re-inferred; `reload_only` served from the JSON without calling Docling.
- `test_convert_command.py` — one bad document does not stop the batch; `documents_done`
  advances; the log file is written; a run-level failure lands on `convert_failed`.
- `test_wizard_read.py` — the step 2 page renders per-document badges; Continue moves
  `converted` → `queued`; the read button is refused on a `running` job.
- `test_verify.py` additions — a quote without markup matches a stored line carrying `**`;
  a table-cell quote matches across a pipe; `quote_sha1` output is byte-identical to today's
  for a fixed set of strings (the regression guard on §4's promise).

And one manual check that no unit test can stand in for, on a real document from the archive:
run the read step on a two-column report and on a scanned one, and read the preview. The
scanned one producing text at all is the result this whole change exists for.

## 14. Known limits, stated rather than discovered later

- **OCR text is not the document's text.** A quote verified against OCR output is verified
  against a machine's reading of an image. `verify` cannot tell the difference, and neither can
  the review page. The engine badge on step 2 is the only signal a reviewer gets, which is why
  it is on the preview rather than buried in a log.
- **Conversion and extraction both hold RAM in the `web` container.** Docling's models are
  loaded per process; a conversion running while a pipeline run is in progress will be the
  largest memory consumer in the container. Nothing here serialises them.
- **A document past `DOCLING_MAX_PAGES` is truncated,** exactly as pipeline documents already
  are, and the preview shows the truncated page count rather than announcing the truncation.
- **Re-reading a document with published insights is refused, permanently.** The only way to
  re-read it is to reject its insights first. This is deliberate — the alternative is a
  published quote whose page text no longer contains it — but it means an early batch
  extracted from bad PyMuPDF text cannot be silently upgraded.
- **Docling's own version matters to reproducibility.** `Conversion.docling_version` records
  it, because a later version reading the same PDF differently would move quotes out from
  under their page numbers, and nothing else would say why.

## 15. Documentation to update

`CLAUDE.md` §"2. Extract community insights from documents": the route in is now **five** steps,
not four, and the sentence about what the model reads is currently wrong — it will be Docling
markdown, not PyMuPDF text. The `.env` keys in §11 belong in `env.example` beside
`IPC_API_KEY` and `HDX_API_TOKEN`.
