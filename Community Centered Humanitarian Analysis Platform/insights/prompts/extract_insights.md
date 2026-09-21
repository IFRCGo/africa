# Extracting community insights from a document

You are reading humanitarian documents to find **what communities themselves said**.

## What to extract

A **community insight** is a statement about a community's situation, quoted
**verbatim** from the document. Two kinds count, and you must label which:

- `community` — the document is reporting what people said: a quote, a focus-group
  or key-informant finding, a participatory assessment, a perception survey result.
- `secondary_analysis` — an analyst's own description of a community's hazards,
  needs or vulnerabilities.

**Label the voice honestly, whatever the topic.** Widening what you read for does
not blur these two. A focus-group finding is `community`; a survey statistic in
the analyst's own prose is `secondary_analysis`, even when both sit in the same
paragraph about the same people.

## Read the document for all of this

Read for each of the following. **Coverage is opportunistic: a topic the document
does not cover yields nothing, and that is still the correct answer.** Do not pad
a thin document to fill these headings — a weekly sitrep that holds two statements
should return two statements, and most sitreps contain no community voice at all.

| What to look for | Where it goes |
|---|---|
| movement numbers | a `movements[]` entry with `value` and `unit` |
| where people came from, where they are going | `movements[]`, both ends named |
| why they moved, why they are returning | the movement tag as `subject`, the cause as `driver` |
| hazards they are exposed to | `hazard` codings |
| who is vulnerable, and why | the group as `subject`, the cause as `driver` |
| coping mechanisms adopted | `coping` codings |
| needs | `need` codings, and `barrier` for what blocks access |
| any other stated quantity | a `figures[]` entry |

### The role on a coding

Each coding carries a `role`, and this is how a reason is recorded:

- `subject` — what the statement is about. The default; omit it if unsure.
- `driver` — the cause. A quote coded `movement_pattern:return_movement` as
  subject and `hazard:armed_conflict` as driver says *why* they are returning.
- `barrier` — what blocks access. `need:health` as subject with
  `vulnerability:statelessness_documentation` as barrier says they cannot reach
  the clinic without papers.

## The rules that matter

1. **Quote verbatim.** Copy the sentence exactly as printed, including its
   punctuation. Do not paraphrase, tidy, translate or join two separate passages.
   Every quote is checked against the stored page text and a quote that does not
   match is discarded.

   The page text you are given is **markdown** converted from the original PDF or
   Word file: headings carry `#`, emphasis carries `*`, and a table row is a line
   of `|` cells. Quote the document's **words**, not its markup — leave the `**`
   and the `|` out of what you copy. The check folds markup from both sides
   before comparing, so the words are what has to match. Do not quote across a
   table row break: each row is its own statement.
2. **Give the page number the quote is printed on.**
3. **Never invent a number.** Leave `people_affected` null unless the passage
   states a figure. Most do not.
4. **Keep the original language.** Set `quote_language` (`en`, `fr`, `ar`). Do not
   translate.
5. **Name the place as the document writes it** in `place_name_as_written`. Do not
   convert it to a p-code and do not guess a finer location than the text gives.
6. **REQUIRED: Set the country code.** Every insight must include `iso3`, an
   ISO3 country code (e.g. `ETH`, `SDN`, `TCD`). A missing or blank `iso3`
   causes the **entire payload file to be rejected**, not just that insight.
   Typically: the country the document is about, or the country containing the
   place named in `place_name_as_written`. Note: `Document.country_focus` is
   free text and must not be copied blindly to `iso3`.
7. **A figure is only ever an attribute of a quoted sentence, and you must copy
   its span.** Give `figure_as_written` exactly as printed — `"65 percent"`,
   `"0.7 million"`, `"two-fifths of refugee households (44 percent)"` — alongside
   the parsed `value` and `unit`. The span is checked against your quote and the
   figure is discarded if it is not there. If the number is not printed in the
   passage you are quoting, there is no figure. `unit` is one of `people`,
   `percent`, `households`; a corridor's `unit` is `people` or `households` only,
   never a share.
8. **Name only the ends the text names.** Do not infer an origin or a destination
   from surrounding context. A corridor with one end stated and the other genuinely
   absent is recorded with one end; a corridor with neither is not a corridor.
   Give each end its own `iso3` — on a cross-border movement the two differ, and
   neither is assumed from the document's country.

## Codings

Each insight carries the themes read out of it. `dimension` must be one of
`hazard`, `vulnerability`, `need`, `coping`, `movement_pattern`. `tag` should be a
key from `data_pipeline/taxonomy.json` under that dimension — read that file. If
nothing fits, put your own words in `tag` anyway: it will be recorded as `other`
with your suggestion kept for a reviewer, which is how the vocabulary grows.

## Output

Write one JSON file per document to `data_pipeline/mcp_cache/insights/<stem>.json`:

```json
{
  "source": {"rel_path": "<as in the documents table>", "sha1": "…", "report_date": "YYYY-MM-DD"},
  "producer": {"agent": "claude-code", "model": "claude-opus-5"},
  "insights": [
    {
      "quote": "…verbatim…",
      "quote_language": "en",
      "page": 7,
      "voice_type": "community",
      "place_name_as_written": "Afar",
      "iso3": "ETH",
      "codings": [
        {"dimension": "movement_pattern", "tag": "cross_border_arrival", "role": "subject"},
        {"dimension": "hazard", "tag": "armed_conflict", "role": "driver"},
        {"dimension": "need", "tag": "health", "role": "subject"}
      ],
      "figures": [
        {"figure_as_written": "65 percent", "value": 65, "unit": "percent",
         "measures": "highly or extremely vulnerable",
         "applies_to": "female-headed households"}
      ],
      "movements": [
        {"origin_name_as_written": "Sudan", "origin_iso3": "SDN",
         "dest_name_as_written": "Egypt", "dest_iso3": "EGY",
         "flow_type": "cross_border",
         "value_as_written": "0.7 million", "value": 700000, "unit": "people"}
      ],
      "people_affected": null,
      "severity": 4,
      "confidence": "high"
    }
  ]
}
```

`severity` is 1–5 on the same scale the events timeline uses, or null.
`confidence` is `high`, `medium` or `low`.

**An empty `insights` list is rejected as a failed run.** If a document genuinely
holds nothing, do not write a file for it.

Then, in Django Admin, open the extraction job and run **Load payloads**.
