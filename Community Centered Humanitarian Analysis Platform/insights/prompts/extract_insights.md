# Extracting community insights from a document

You are reading humanitarian documents to find **what communities themselves said**.

## What to extract

A **community insight** is a statement about a community's situation, quoted
**verbatim** from the document. Two kinds count, and you must label which:

- `community` — the document is reporting what people said: a quote, a focus-group
  or key-informant finding, a participatory assessment, a perception survey result.
- `secondary_analysis` — an analyst's own description of a community's hazards,
  needs or vulnerabilities.

**Most sitreps contain no community voice at all. Returning only
`secondary_analysis` passages, or a short list, is the correct answer for such a
document. Do not pad.**

## The rules that matter

1. **Quote verbatim.** Copy the sentence exactly as printed, including its
   punctuation. Do not paraphrase, tidy, translate or join two separate passages.
   Every quote is checked against the stored page text and a quote that does not
   match is discarded.
2. **Give the page number the quote is printed on.**
3. **Never invent a number.** Leave `people_affected` null unless the passage
   states a figure. Most do not.
4. **Keep the original language.** Set `quote_language` (`en`, `fr`, `ar`). Do not
   translate.
5. **Name the place as the document writes it** in `place_name_as_written`. Do not
   convert it to a p-code and do not guess a finer location than the text gives.

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
        {"dimension": "hazard", "tag": "flooding"},
        {"dimension": "need", "tag": "health"}
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
