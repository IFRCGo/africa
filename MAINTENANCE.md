# Maintaining the Sudan PoP MVT Tracker

## Routine update (new documents arrive)

1. Drop the new PDFs into the year folders of the two source collections
   (`UNHCR Regional Population Movement pdfs\2026`, `UNHCR Sudan only pdfs\2026`, …).
   The existing download scripts (`Download-Sudan-Weekly-Maps.ps1`, `Download-CORE-2026.ps1`)
   can keep feeding these folders.
2. Run the pipeline — it is **incremental**, only files it has never seen
   (matched by path, verified by SHA-1) are processed:

   ```powershell
   cd "PoP MVT Tracker\pipeline"
   python run_all.py
   ```

3. Review the new data (optional but recommended — see "Auditing" below).
4. Publish:

   ```powershell
   cd "PoP MVT Tracker"
   git add -A
   git commit -m "Data update <date>"
   git push          # the Pages workflow redeploys the platform automatically
   ```

## Tuning without re-reading PDFs

Parsing, events and export can be re-run from the archived text in seconds:

```powershell
python run_all.py --reparse
```

Use this after editing:

| file              | controls                                                            |
|-------------------|---------------------------------------------------------------------|
| `taxonomy.json`   | the toggle categories — add keywords/tags, re-run, they appear in the platform |
| `gazetteer.json`  | locations, coordinates, movement corridors                          |
| `s04_events.py`   | the CURATED list — add new milestone events here as the crisis evolves |
| `s03_parse.py`    | extraction patterns and per-country plausibility bounds (`ARRIVAL_BOUNDS`) |

## Auditing the data

Every figure stores its parser (`method`), `confidence` and the source `snippet`.
Open `database/sudan_story.db` in DB Browser for SQLite, or:

```sql
-- where did a number come from?
SELECT d.file_name, f.value, f.method, f.snippet
FROM population_figures f JOIN documents d ON d.id = f.document_id
WHERE f.country = 'Chad' AND f.metric = 'cumulative_arrivals'
ORDER BY f.report_date DESC LIMIT 10;

-- documents the parser dated by file-modified time (weakest evidence) — worth checking
SELECT file_name, report_date FROM documents WHERE date_source = 'mtime';

-- corridor series as the platform sees it (after export cleaning, look in platform/data/flows.json)
```

If a wrong value appears on the platform, find it with the query above, then either
tighten the bound/pattern in `s03_parse.py` or, for a one-off, delete the row and
re-run `python s05_export.py`. (Note: a full `--reparse` rebuilds deleted rows, so
prefer fixing the parser.)

## Database care

- The DB is the archival master — it is committed to git, so every data update is
  versioned and recoverable. Nothing else needs backing up.
- If it is ever corrupted or you want a clean rebuild from the PDFs:
  delete `database/sudan_story.db` and run `python run_all.py` (≈ 5 minutes).
- The source PDFs can be deleted/archived at any time; the full text remains in
  `document_text`.

## Things that need a human

- **Curated events**: the extractor catches incident sentences automatically, but
  defining milestones (a city falling, a famine declaration) deserve a hand-written
  entry in `s04_events.py` with a severity rating.
- **New document layouts**: if UNHCR redesigns a series (it happened twice with the
  returns dashboards), spot-check new files and extend the matching parser in
  `s03_parse.py`. The content-based detection means old layouts keep working.
- **Estimate revisions**: big jumps (like Egypt 500K → 1.2M) are accepted only when
  later reports confirm them, so a genuine revision shows up after the next 1–2
  documents arrive — this lag is by design.
