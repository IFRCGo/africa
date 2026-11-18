"""Download one document from a link, and decide what it is from its bytes.

WHY THE TYPE IS READ OFF THE CONTENT, NOT THE URL. The links an analyst
actually pastes are download endpoints: HDX's end in "?download=1", ReliefWeb's
in an attachment id, and plenty carry no extension at all. But catalogue_file
dispatches _pages_of and pdf_metadata on `path.suffix.lower()` alone, so a name
without the right suffix sends a PDF to python-docx - a stack trace where there
should have been a sentence. The bytes are authoritative, and the name this
returns is rebuilt to agree with them.

WHY A ZIP IS NOT ENOUGH TO CALL SOMETHING A DOCX. An XLSX has the same magic
bytes. The test for a Word file is therefore the part of the archive that only
a Word file has: word/document.xml.

This module does not touch the database and knows nothing about jobs. It takes
a URL and gives back a name and bytes, which is all wizard.batch_url needs to
hand the same helper that catalogues an upload.
"""
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

SCHEMES = {"http", "https"}
MAX_BYTES = 100 * 1024 * 1024
TIMEOUT = 60
CHUNK = 1 << 16

# Some humanitarian file stores answer a bare client with a consent page rather
# than the file, so the request says who it is.
USER_AGENT = "CCHA-insights-wizard/1.0"

_FILENAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.IGNORECASE)


class BadLink(ValueError):
    """The link cannot be fetched, or what came back could not be taken.

    Reported on its own row as "failed", with this message and no exception
    type in front of it - every one of these is a sentence for a person.
    """


class NotADocument(Exception):
    """The link resolved, but what came back is not a PDF or Word file.

    Distinct from BadLink because nothing went wrong: this is the same outcome
    as a .jpg sitting in a chosen folder, and it is reported the same way -
    "skipped", not "failed".
    """


def fetch(url):
    """Return (file_name, payload) for a link to a PDF or DOCX.

    Raises BadLink for a URL this will not fetch or a download it will not
    finish, NotADocument when the bytes are something else, and requests' own
    exceptions for a connection that fails.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in SCHEMES:
        raise BadLink(
            f"{parsed.scheme or 'That'} links cannot be fetched - paste an "
            f"http:// or https:// address.")
    if not parsed.netloc:
        raise BadLink("That is not a web address.")

    # Streamed with a ceiling because this request holds a gunicorn worker for
    # its whole life: without one, a single enormous link occupies a worker
    # until it finishes or the proxy gives up.
    with requests.get(url, stream=True, timeout=TIMEOUT,
                      headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        payload = bytearray()
        for block in response.iter_content(CHUNK):
            payload.extend(block)
            if len(payload) > MAX_BYTES:
                raise BadLink(
                    f"That file is larger than {MAX_BYTES // (1 << 20)} MB. "
                    f"Download it and add it as a file instead.")
        disposition = response.headers.get("Content-Disposition", "")
        content_type = response.headers.get("Content-Type", "")

    payload = bytes(payload)
    suffix = _suffix_of(payload)
    if suffix is None:
        raise NotADocument(_why_not(payload, content_type))
    return _name_for(url, disposition, suffix), payload


def _suffix_of(payload):
    """".pdf", ".docx", or None for anything else."""
    if payload.startswith(b"%PDF-"):
        return ".pdf"
    if payload.startswith(b"PK\x03\x04") and _is_word(payload):
        return ".docx"
    return None


def _is_word(payload):
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _why_not(payload, content_type):
    """The sentence the skipped row carries.

    The overwhelmingly common miss is a report's landing page pasted instead of
    the attachment on it, so that case gets its own wording and says what to do
    about it.
    """
    looks_like_html = (
        "html" in content_type.lower()
        or payload.lstrip()[:512].lower().startswith((b"<!doctype html", b"<html"))
    )
    if looks_like_html:
        return ("That link is a web page, not a PDF or Word document - open it "
                "and paste the link to the attachment itself.")
    return "What that link returned is not a PDF or Word document."


def _name_for(url, disposition, suffix):
    """A bare file name carrying the suffix the bytes earned.

    Content-Disposition first because it is the server's own name for the file
    and the only honest one when the path is an id. Whatever wins, only the
    basename survives: this becomes Document.file_name and the name storage
    writes, so a value with a directory in it must not get that far.
    """
    found = _FILENAME.search(disposition)
    # Percent-decoded either way: RFC 5987's filename*=UTF-8'' form is how a
    # French or Arabic report title arrives, and file_name is what a reviewer
    # reads on the review page - "Rapport%20Tchad" is not a title.
    name = unquote(found.group(1).strip()) if found else ""
    if not name:
        name = unquote(urlparse(url).path)
    # Both separators, because the name may have come off a Windows server.
    stem = Path(name.replace("\\", "/")).name
    stem = Path(stem).stem.strip() or "document"
    return f"{stem}{suffix}"
