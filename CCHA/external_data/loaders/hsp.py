"""The Humanitarian Service Point Mapping export -> humanitarian_service_points rows.

The export is a Kobo form with 1,051 columns and six rows, one per country. Almost
all of those columns are binary: eleven for the services offered, and 931 for the
districts they are offered in - the union of every country's district roster, so
each country's own districts are a slice of the same wide sheet.

Two shapes come out of it:

  country-wide     five countries answered "yes, the same services everywhere", so
                   their rows are the cross product of the services they ticked and
                   the districts they ticked
  named-location   South Sudan answered "no", so its three locations live on the
                   'location' sheet, each with its own service list

`max_hsps` is NOT a count of service points - its values are the size of each
country's district roster (70, 135, 78, 92, 189, 367). The reported count is the
separate "How many humanitarian service points (HSPs) are there?" column, which
only South Sudan filled in.
"""
import re
from datetime import date

SERVICE_PREFIX = "Services offered (applies to ALL locations)/"
DISTRICT_PREFIX = "Districts where these services are offered/"
LOCATION_SERVICE_PREFIX = "Services offered at THIS location/"

COUNTRY_TO_ISO3 = {
    "Chad": "TCD", "Uganda": "UGA", "South Sudan": "SSD",
    "Ethiopia": "ETH", "Sudan": "SDN", "Egypt": "EGY",
    "Central African Republic": "CAF", "Libya": "LBY", "Eritrea": "ERI",
}

# 'Humanitarian_Service_Points_Mapping_..._2026-09-08-11-46-14.xlsx'
_EXPORT_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-\d{2}-\d{2}-\d{2}")


def export_date(filename):
    """The export timestamp from the filename - the only date this source carries."""
    m = _EXPORT_DATE.search(str(filename))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _ticked(value):
    """Kobo writes 1/0; be tolerant of the string forms an export can produce."""
    return value in (1, "1", True, "yes", "Yes", "TRUE", "True")


def _cell(row, i):
    return row[i] if i < len(row) else None


def parse_country_rows(rows, source_file, reported):
    """The main sheet -> one row per (country x service x district).

    Skips any country that answered "no" to same-services: its detail lives on the
    'location' sheet and is read by parse_location_rows instead. Emitting both would
    double-count South Sudan.
    """
    header = [str(h or "") for h in rows[0]]
    services = [(i, h[len(SERVICE_PREFIX):]) for i, h in enumerate(header)
                if h.startswith(SERVICE_PREFIX)]
    districts = [(i, h[len(DISTRICT_PREFIX):]) for i, h in enumerate(header)
                 if h.startswith(DISTRICT_PREFIX)]

    i_country = header.index("Country")
    i_same = next((i for i, h in enumerate(header)
                   if h.startswith("Are the SAME services")), None)
    i_count = next((i for i, h in enumerate(header)
                    if h.startswith("How many humanitarian service points")), None)
    i_uuid = header.index("_uuid") if "_uuid" in header else None

    out = []
    for row in rows[1:]:
        country = _cell(row, i_country)
        if not country:
            continue
        same_raw = _cell(row, i_same) if i_same is not None else None
        same = None if same_raw is None else str(same_raw).strip().lower() == "yes"
        if same is False:
            continue                      # handled by the location sheet

        picked_services = [s for i, s in services if _ticked(_cell(row, i))]
        picked_districts = [d for i, d in districts if _ticked(_cell(row, i))]
        count = _cell(row, i_count) if i_count is not None else None
        uuid = _cell(row, i_uuid) if i_uuid is not None else None

        for district in picked_districts:
            for service in picked_services:
                out.append({
                    "date_reported": reported,
                    "country": str(country),
                    "iso3": COUNTRY_TO_ISO3.get(str(country), ""),
                    "service": service,
                    "scope": "country-wide",
                    "location_name": district,
                    "admin_pcode": None, "admin_level": None,
                    "match_method": "unmatched", "lat": None, "lon": None,
                    "same_services_everywhere": same,
                    "hsp_count": int(count) if str(count or "").isdigit() else None,
                    "kobo_uuid": uuid,
                    "source_file": source_file,
                })
    return out


def parse_location_rows(rows, main_rows, source_file, reported):
    """The 'location' sheet -> one row per (named location x service).

    Only South Sudan has these. The sheet names the district but not the country,
    so the country is taken from the parent submission the rows point at.
    """
    if not rows:
        return []
    header = [str(h or "") for h in rows[0]]
    services = [(i, h[len(LOCATION_SERVICE_PREFIX):]) for i, h in enumerate(header)
                if h.startswith(LOCATION_SERVICE_PREFIX)]
    i_district = header.index("District") if "District" in header else None
    i_region = header.index("Province / Region") if "Province / Region" in header else None
    i_parent = header.index("_parent_index") if "_parent_index" in header else None
    i_uuid = (header.index("_submission__uuid")
              if "_submission__uuid" in header else None)

    main_header = [str(h or "") for h in main_rows[0]]
    i_country = main_header.index("Country")
    i_count = next((i for i, h in enumerate(main_header)
                    if h.startswith("How many humanitarian service points")), None)

    out = []
    for row in rows[1:]:
        district = _cell(row, i_district) if i_district is not None else None
        if not district:
            continue
        # _parent_index is 1-based over the submissions, so it indexes main_rows
        # directly once the header row is counted.
        parent = _cell(row, i_parent) if i_parent is not None else None
        country, count = "", None
        if isinstance(parent, int) and 0 < parent < len(main_rows):
            country = _cell(main_rows[parent], i_country) or ""
            if i_count is not None:
                count = _cell(main_rows[parent], i_count)

        for i, service in services:
            if not _ticked(_cell(row, i)):
                continue
            out.append({
                "date_reported": reported,
                "country": str(country),
                "iso3": COUNTRY_TO_ISO3.get(str(country), ""),
                "service": service,
                "scope": "named-location",
                "location_name": str(district),
                "admin_pcode": None,
                "admin_level": None,
                "match_method": "unmatched",
                "lat": None, "lon": None,
                "same_services_everywhere": False,
                "hsp_count": int(count) if str(count or "").isdigit() else None,
                "kobo_uuid": _cell(row, i_uuid) if i_uuid is not None else None,
                "source_file": source_file,
                "_region": _cell(row, i_region) if i_region is not None else None,
            })
    return out
