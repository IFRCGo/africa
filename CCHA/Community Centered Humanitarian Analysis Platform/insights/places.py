"""Turn 'Afar' plus 'ETH' into a polygon, or admit that we could not.

WHAT lat/lon MEAN HERE. They are copied from AdminArea.center_lat/center_lon, a
point guaranteed to be inside the polygon - a LABEL POSITION, not an address.
The dashboard popup says so. This is the same care HumanitarianServicePoint takes
in its own docstring about not reading its dots as building locations, and for
the same reason: the finest truthful placement the source supports.

`match_method` records how far we got - 'pcode', 'name' or 'unmatched' - because
"somewhere in Afar" and "we do not know where" are different findings and only
this column tells them apart afterwards.
"""
import unicodedata

from boundaries.models import AdminArea

UNMATCHED = {"admin_pcode": None, "admin_level": None,
             "match_method": "unmatched", "lat": None, "lon": None}


def _key(text):
    """Normalize text for comparison: lowercase, collapse whitespace, fold accents and hyphens.

    Francophone boundary names carry diacritics (OUADDAÏ, Mambéré-Kadéï) with no
    alternates, while English-language humanitarian reports drop them and write
    hyphens as spaces. This normalisation bridges that gap so accented boundary
    names match their accent-dropped English variants.

    Trade-off: two genuinely distinct places differing only by an accent or hyphen
    within one country would now collide. This is judged vanishingly unlikely for
    admin boundary names.
    """
    # Replace hyphens with spaces before whitespace collapsing
    text = str(text).strip().replace('-', ' ').lower()
    # Fold accents: decompose with NFKD, then drop combining marks (category Mn)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Collapse whitespace
    return " ".join(text.split())


def _hit(area, method):
    return {
        "admin_pcode": area.pcode,
        "admin_level": area.level,
        "match_method": method,
        "lat": area.center_lat,
        "lon": area.center_lon,
    }


def resolve(iso3, place_name):
    """Best placement for a place named the way a source wrote it.

    Returns UNMATCHED rather than raising. An unplaced insight is a normal
    outcome: camps, settlements and neighbourhoods are not in the library.
    """
    if not place_name or not iso3:
        return dict(UNMATCHED)

    candidates = list(
        AdminArea.objects.filter(iso3=iso3, kind=AdminArea.KIND_ADMIN)
        .only("pcode", "level", "name", "name_alt", "center_lat", "center_lon")
        .order_by("level")
    )
    if not candidates:
        return dict(UNMATCHED)

    wanted = _key(place_name)

    # A p-code is checked first: when a payload gives one it is a stronger claim
    # than a name, and it is the only match that cannot be a coincidence.
    for area in candidates:
        if _key(area.pcode) == wanted:
            return _hit(area, "pcode")

    for area in candidates:
        names = [area.name, *(area.name_alt or [])]
        if any(_key(n) == wanted for n in names if n):
            return _hit(area, "name")

    return dict(UNMATCHED)
