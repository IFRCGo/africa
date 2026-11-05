"""Step 2 of 7 - read the text of every catalogued PDF into `document_text`.

This is the archival step: once a page of text is stored, the analysis can be
re-run for ever, even if the original PDF is deleted.

It also fills in any missing report date, by looking for one in the first page
of text and, as a last resort, using the file's own modification date.

This is the slowest step (it opens every PDF), which is why it prints a running
"done/total" count - the updater page turns those lines into the progress bar.
"""
from datetime import date, datetime

import fitz  # PyMuPDF: the library that reads PDFs

from django.db import transaction

from data_pipeline.common import SOURCE_ROOT, parse_date_from_text
from data_track.models import Document, DocumentText

# Some appeal documents run past 100 pages. We keep the first 40, which always
# contain the figures and narrative, and keep the database a sensible size.
MAX_PAGES = 40


def run():
    """Extract text from every document that has none yet."""
    # "texts" is the related name on the DocumentText model, so this reads:
    # every document that has no page rows at all.
    todo = list(
        Document.objects.filter(texts__isnull=True).order_by("id")
        .values_list("id", "rel_path", "report_date")
    )
    print(f"extracting text from {len(todo)} documents")

    n_err = 0
    for i, (doc_id, rel, report_date) in enumerate(todo):
        path = SOURCE_ROOT / rel
        try:
            pdf = fitz.open(path)
            pages = min(len(pdf), MAX_PAGES)
            page_rows = []
            first_text = ""
            for page_number in range(pages):
                text = pdf[page_number].get_text("text")
                if page_number == 0:
                    first_text = text
                # Pages are numbered from 1 for humans, so add 1.
                page_rows.append(DocumentText(document_id=doc_id, page=page_number + 1, text=text))

            # Work out the date if step 1 could not read one from the filename.
            new_date, new_source = report_date, None
            if not report_date:
                new_date = parse_date_from_text(first_text)
                new_source = "text"
                if not new_date:
                    new_date = date.fromtimestamp(path.stat().st_mtime)
                    new_source = "mtime"

            # transaction.atomic means: either all of this is saved, or none of
            # it is. That keeps a half-extracted document out of the database.
            with transaction.atomic():
                DocumentText.objects.bulk_create(page_rows, batch_size=200)
                fields = {
                    "pages": len(pdf),
                    "extracted_at": datetime.now().isoformat(timespec="seconds"),
                }
                if new_source:
                    fields["report_date"] = new_date
                    fields["date_source"] = new_source
                Document.objects.filter(id=doc_id).update(**fields)

            pdf.close()
        except Exception as e:  # a corrupt or password-protected PDF: log and carry on
            n_err += 1
            print(f"  ERROR {rel}: {e}")

        # Progress line every 100 documents (the updater turns these into %).
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(todo)}")

    n_pages = DocumentText.objects.count()
    print(f"done: {len(todo) - n_err} ok, {n_err} errors, {n_pages} pages stored")
