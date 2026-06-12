"""Step 2: extract full text of every cataloged PDF into document_text.

Also fills report_date from page text (or file mtime as last resort) where the
filename gave nothing.
"""
from datetime import datetime, date

import fitz  # PyMuPDF

from common import ROOT_DIR, get_db, parse_date_from_text, iso

MAX_PAGES = 40  # RRP appeals run to 100+ pages; cap to keep DB lean


def main():
    con = get_db()
    cur = con.cursor()
    todo = cur.execute(
        """SELECT id, rel_path, report_date FROM documents
           WHERE id NOT IN (SELECT DISTINCT document_id FROM document_text)
           ORDER BY id"""
    ).fetchall()
    print(f"extracting text from {len(todo)} documents")
    n_err = 0
    for i, (doc_id, rel, report_date) in enumerate(todo):
        path = ROOT_DIR / rel
        try:
            pdf = fitz.open(path)
            pages = min(len(pdf), MAX_PAGES)
            first_text = ""
            for p in range(pages):
                text = pdf[p].get_text("text")
                if p == 0:
                    first_text = text
                cur.execute(
                    "INSERT OR REPLACE INTO document_text (document_id, page, text) VALUES (?,?,?)",
                    (doc_id, p + 1, text),
                )
            cur.execute(
                "UPDATE documents SET pages=?, extracted_at=? WHERE id=?",
                (len(pdf), datetime.now().isoformat(timespec="seconds"), doc_id),
            )
            if not report_date:
                d = parse_date_from_text(first_text)
                src = "text"
                if not d:
                    d = date.fromtimestamp(path.stat().st_mtime)
                    src = "mtime"
                cur.execute("UPDATE documents SET report_date=?, date_source=? WHERE id=?",
                            (iso(d), src, doc_id))
            pdf.close()
        except Exception as e:  # noqa: BLE001 - log and continue over corrupt PDFs
            n_err += 1
            print(f"  ERROR {rel}: {e}")
        if (i + 1) % 100 == 0:
            con.commit()
            print(f"  {i + 1}/{len(todo)}")
    con.commit()
    n_pages = cur.execute("SELECT COUNT(*) FROM document_text").fetchone()[0]
    print(f"done: {len(todo) - n_err} ok, {n_err} errors, {n_pages} pages stored")


if __name__ == "__main__":
    main()
