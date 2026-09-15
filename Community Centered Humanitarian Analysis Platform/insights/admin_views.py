"""The two JSON endpoints the Admin pickers call.

Both are mounted inside the admin site (see get_urls in insights/admin.py) and
wrapped in `admin_site.admin_view`, so they are staff-only and carry the admin's
own login redirect. Neither belongs in insights/urls.py: that file is the public
read API, and nothing here is public.

    place-options/   the states of a country, or the districts of a state
    folder-browse/   the directories under a mounted root

WHY NOT REUSE /api/boundaries/layer/. That endpoint streams whole polygons - a
single Egyptian ADM3 request is 5,716 geometries. Filling a dropdown needs a
p-code and a name, so this asks for a p-code and a name.

WHY THE FOLDER BROWSER IS SERVER-SIDE. A browser's own directory input returns a
path on the reviewer's own machine - `C:\\Users\\...\\DTM Round 12` - which does
not exist inside this container and never will. The only paths that mean
anything to InsightFolder are paths in here, so the listing is done in here.
"""
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse

from insights.forms import district_choices, state_choices
from insights.intake import SUFFIXES


def place_options(request):
    """[{pcode, name}] for one level under one parent.

    level=1 treats `parent` as an iso3, level=2 as a state's p-code - which is
    the same asymmetry state_choices and district_choices already encode, for the
    reason given there: a country is identified by its iso3 everywhere in this
    project, and by its p-code only inside the boundary table.
    """
    parent = request.GET.get("parent") or ""
    level = request.GET.get("level") or ""

    if level == "2":
        rows = district_choices(parent)
    elif level == "1":
        rows = state_choices(parent)
    else:
        return JsonResponse({"error": "level must be 1 or 2"}, status=400)

    # Both helpers lead with the blank choice the form needs; the browser builds
    # its own blank option, so it is dropped here rather than rendered twice.
    return JsonResponse({
        "areas": [{"pcode": pcode, "name": name} for pcode, name in rows if pcode],
    })


def _roots():
    """The directories a folder may be chosen from, in the order offered.

    SOURCE_ROOT is /work, the read-only mount covering the whole SUDAN Ops
    folder - which is where the source documents actually are. MEDIA_ROOT is
    where an InsightUpload lands. There is no third place a document can be, and
    listing anything else would be handing out a filesystem browser.
    """
    candidates = [
        ("Source documents (/work)", Path(settings.SOURCE_ROOT)),
        ("Uploaded files", Path(settings.MEDIA_ROOT)),
    ]
    return [(label, path.resolve()) for label, path in candidates if path.is_dir()]


def _within_a_root(path, roots):
    """True if `path` is a root or sits inside one.

    Resolve first, compare second. That ordering is the guard: a path containing
    `..` is collapsed before it is checked, so `/work/../etc` is tested as `/etc`
    and refused, rather than passing a string comparison that only looked at the
    prefix.
    """
    for _, root in roots:
        if path == root or root in path.parents:
            return True
    return False


def folder_browse(request):
    """One directory's subdirectories, or the list of roots when none is asked for."""
    roots = _roots()
    body = {"roots": [{"label": label, "path": str(path)} for label, path in roots]}

    raw = request.GET.get("path") or ""
    if not raw:
        return JsonResponse(body)

    try:
        path = Path(raw).resolve()
    except (OSError, ValueError):
        return JsonResponse({"error": "That path cannot be read."}, status=400)

    if not _within_a_root(path, roots):
        return JsonResponse(
            {"error": "Folders must live under a mounted root - /work covers the "
                      "whole SUDAN Ops folder."},
            status=400,
        )
    if not path.is_dir():
        return JsonResponse({"error": f"{path} is not a directory."}, status=400)

    entries, documents = [], 0
    try:
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child)})
            elif child.suffix.lower() in SUFFIXES:
                documents += 1
    except PermissionError:
        return JsonResponse({"error": f"{path} cannot be read."}, status=400)

    body.update({
        "path": str(path),
        # Only offered when it is still inside a root, so the "up" link cannot
        # walk out of the mount either.
        "parent": (str(path.parent)
                   if _within_a_root(path.parent, roots) and path.parent != path
                   else None),
        "entries": entries,
        # Counted in this folder only, not recursively: /work holds thousands of
        # PDFs and a recursive walk on every click would make the picker crawl.
        # It answers "is this the folder?", which is all it needs to.
        "document_count": documents,
    })
    return JsonResponse(body)
