"""Which folders a source document may be read from, and how to say so.

THE ONE PLACE THAT ANSWERS THIS. It used to be answered in four: a tuple in
admin_views._roots, and the same sentence about "/work" written out by hand in
InsightFolder.clean, catalogue_folder and folder_browse. A sentence written
four times is a sentence that goes stale three times, and every copy of it
named a path that only exists in one deployment.

WHY THERE IS A ROOT LIST AT ALL. folder_browse lists directories inside the
container and hands them to a form that will read every PDF in one. Without a
boundary that is a filesystem browser for anyone with a staff account. The
roots are the boundary; they are configured per deployment and nothing outside
them is listed or accepted.
"""
from pathlib import Path

from django.conf import settings


def roots():
    """[(label, resolved path)] for every configured root that exists.

    A root that has moved or is not mounted is dropped rather than offered and
    then failed on - the same behaviour the two hardcoded roots had.

    The label is the directory's own name. Deliberately not a literal written
    here: "Source documents (/work)" was true of one deployment and a lie in
    every other.
    """
    found = []
    for candidate in settings.INSIGHT_DOCUMENT_ROOTS:
        path = Path(candidate).resolve()
        if path.is_dir():
            found.append((path.name or str(path), path))
    return found


def contains(path):
    """True if `path` is a root or sits inside one.

    Resolve first, compare second. That ordering is the guard: a path holding
    `..` is collapsed before it is checked, so `<root>/../etc` is tested as
    `/etc` and refused, rather than passing a comparison that only looked at
    the start of a string.
    """
    path = Path(path).resolve()
    for _, root in roots():
        if path == root or root in path.parents:
            return True
    return False


def sentence():
    """One sentence naming the folders, for an error a person has to act on."""
    configured = [str(path) for _, path in roots()]
    if not configured:
        return (
            "No document folders are reachable on this deployment. Set "
            "INSIGHT_DOCUMENT_ROOTS and make sure the folders it names are mounted."
        )
    return "Folders must live under one of: " + ", ".join(configured) + "."
