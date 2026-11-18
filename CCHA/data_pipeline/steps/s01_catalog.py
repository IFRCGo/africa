"""Step 1 of 7 - catalogue every source PDF into the `documents` table.

What it does, in order:
  * walks the two UNHCR folders looking for *.pdf
  * skips any file already stored (matched on its path), so re-running is safe
  * works out the report series (family), the country and the report date
  * saves one Document row per new file, with a sha1 fingerprint of the file

Nothing is read out of the PDF itself here - that is step 2. This step is fast
and is what the updater page counts when it says "3 new PDFs".
"""
import hashlib

from django.db.models import Count, Q

from data_pipeline.common import SOURCE_COLLECTIONS, SOURCE_ROOT, classify, parse_date_from_name
from data_track.models import Document


def sha1_of(path, chunk=1 << 20):
    """Fingerprint a file by reading it 1 MB at a time (never loads it all)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def run():
    """Catalogue new PDFs. Returns nothing; prints a short summary."""
    # One database query gives us every path we have already seen.
    seen = set(Document.objects.values_list("rel_path", flat=True))

    new_rows = []
    n_seen = 0
    for collection, base in SOURCE_COLLECTIONS.items():
        if not base.exists():
            print(f"  source folder missing, skipped: {base}")
            continue
        for pdf in sorted(base.rglob("*.pdf")):
            # Forward slashes keep the path identical on Windows and in Docker.
            rel = pdf.relative_to(SOURCE_ROOT).as_posix()
            if rel in seen:
                n_seen += 1
                continue

            # Folders are named by year ("2024"), which we use as a sanity check.
            year_folder = int(pdf.parent.name) if pdf.parent.name.isdigit() else None
            family, country = classify(pdf.name)
            report_date = parse_date_from_name(pdf.stem, year_folder)
            date_source = "filename" if report_date else None
            if report_date and year_folder and abs(report_date.year - year_folder) > 1:
                # The filename date disagrees wildly with the folder year, so
                # distrust it and let step 2 find the date in the page text.
                report_date, date_source = None, None

            new_rows.append(
                Document(
                    file_name=pdf.name,
                    rel_path=rel,
                    source_collection=collection,
                    year_folder=year_folder,
                    family=family,
                    country_focus=country,
                    report_date=report_date,
                    date_source=date_source,
                    file_size=pdf.stat().st_size,
                    sha1=sha1_of(pdf),
                )
            )

    # bulk_create writes all the new rows in a few statements instead of one
    # statement per file - much faster when a whole year is added at once.
    Document.objects.bulk_create(new_rows, batch_size=500)

    print(f"cataloged {len(new_rows)} new, {n_seen} already present")

    # A small table so you can see at a glance which series are covered and
    # how many documents still have no date after this step.
    stats = (
        Document.objects.values("family")
        .annotate(docs=Count("id"), no_date=Count("id", filter=Q(report_date=None)))
        .order_by("-docs")
    )
    print(f"{'family':28} {'docs':>5} {'no-date':>8}")
    for row in stats:
        print(f"{row['family'] or '-':28} {row['docs']:>5} {row['no_date']:>8}")
