"""Step 1: catalog every source PDF into the documents table."""
import hashlib
from datetime import datetime, date

from common import SOURCE_COLLECTIONS, ROOT_DIR, get_db, classify, parse_date_from_name, iso


def sha1_of(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def main():
    con = get_db()
    cur = con.cursor()
    n_new = n_seen = 0
    for collection, base in SOURCE_COLLECTIONS.items():
        for pdf in sorted(base.rglob("*.pdf")):
            rel = str(pdf.relative_to(ROOT_DIR))
            if cur.execute("SELECT 1 FROM documents WHERE rel_path=?", (rel,)).fetchone():
                n_seen += 1
                continue
            year_folder = int(pdf.parent.name) if pdf.parent.name.isdigit() else None
            family, country = classify(pdf.name)
            d = parse_date_from_name(pdf.stem, year_folder)
            date_source = "filename" if d else None
            if d and year_folder and abs(d.year - year_folder) > 1:
                d, date_source = None, None  # filename date wildly off the folder year: distrust it
            cur.execute(
                """INSERT INTO documents (file_name, rel_path, source_collection, year_folder,
                       family, country_focus, report_date, date_source, file_size, sha1)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pdf.name, rel, collection, year_folder, family, country,
                 iso(d), date_source, pdf.stat().st_size, sha1_of(pdf)),
            )
            n_new += 1
    con.commit()

    stats = cur.execute(
        "SELECT family, COUNT(*), SUM(report_date IS NULL) FROM documents GROUP BY family ORDER BY 2 DESC"
    ).fetchall()
    print(f"cataloged {n_new} new, {n_seen} already present")
    print(f"{'family':28} {'docs':>5} {'no-date':>8}")
    for fam, n, nd in stats:
        print(f"{fam:28} {n:>5} {nd or 0:>8}")


if __name__ == "__main__":
    main()
