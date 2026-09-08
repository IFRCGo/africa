"""Which file holds what, and how to read its attribute table.

THE REGISTRY IS EXPLICIT ON PURPOSE
Nothing here is inferred from a filename. A loader that guesses "this looks like
Ethiopia's ADM2" will one day guess wrong and file 92 polygons under the wrong
country, and nobody will notice, because a map of the wrong thing still looks
like a map. Every file is listed below with its country, its level and its
publisher, or it is not loaded at all.

FOUR PUBLISHERS, FOUR ATTRIBUTE SCHEMAS
The office's files come from four different mapmakers, and each names its
columns differently. Same information, four spellings:

    itos_lower   adm2_name, adm2_pcode        OCHA ITOS - most countries
    ocha_upper   ADM2_EN,   ADM2_PCODE        South Sudan (IMWG / NBS 2023)
    caf_camel    admin2Name, admin2Pcod       CAR (SIGCAF / REACH)
    gadm         NAME_2,    ID_2              Sudan ADM3 only - no p-codes at all

Each adapter below turns one record into the same small dictionary, so the
loader never has to know which kind of file it is reading.

ENCODINGS ARE NOT A DETAIL
Most of these files ship a .cpg saying UTF-8. The CAR files ship nothing, and
they are cp1252: read them as UTF-8 and every accented name in the country -
Mbaiki, Ndele, Ouanda-Djalle, Bossembele - decodes to rubbish or throws. We read
the .cpg where there is one, fall back to cp1252 where there is not, and always
decode strictly, so a wrong guess is a loud failure rather than a quiet
corruption that ends up in the place-name matcher.
"""
import os

# --------------------------------------------------------------------- levels
# How hard to simplify a polygon before sending it to a browser, by level. A
# country outline can lose 500 m of detail without anyone noticing; a village
# boundary cannot. Degrees, so roughly 550 / 220 / 110 / 55 m.
SIMPLIFY_TOLERANCE = {0: 0.005, 1: 0.005, 2: 0.002, 3: 0.001, 4: 0.0005}
DEFAULT_TOLERANCE = 0.002

# Coordinates go to the browser at five decimal places, about a metre. Beyond
# that is bytes spent on precision no screen can show.
COORD_PRECISION = 5


# ------------------------------------------------------------------- adapters
# Each returns: name, pcode, parent_pcode, alt names, and the ancestors' names
# (for the "Sudan > North Darfur > El Fasher" path).

def _clean(v):
    """DBF pads with spaces and uses empty strings for null. Normalise both."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _alts(rec, prefix, lang):
    """The alternate-language spellings a source carries, as [{name, lang}].

    OCHA files hold up to three: typically the Arabic or French form of the
    same place. They cost nothing to keep and they are the reason a report
    written in French can still be placed.
    """
    out = []
    for i in (1, 2, 3):
        v = _clean(rec.get(f"{prefix}_name{i}") or rec.get(f"{prefix}Al_{i}"))
        if v:
            out.append({"name": v, "lang": _clean(rec.get(f"lang{i}")) or lang})
    return out


def itos_lower(rec, level):
    """OCHA ITOS: adm2_name / adm2_pcode, with adm0..admN all present."""
    p = f"adm{level}"
    lang = _clean(rec.get("lang"))
    return {
        "name": _clean(rec.get(f"{p}_name")),
        "pcode": _clean(rec.get(f"{p}_pcode")) or _clean(rec.get("adm0_pcode")),
        "parent_pcode": _clean(rec.get(f"adm{level - 1}_pcode")) if level else None,
        "ref_name": _clean(rec.get(f"{p}_ref_n")),
        "name_alt": _alts(rec, p, lang),
        "ancestors": [_clean(rec.get(f"adm{i}_name")) for i in range(level)],
        "area_sqkm": rec.get("area_sqkm"),
        "valid_on": rec.get("valid_on"),
        "version": _clean(rec.get("version")),
        "center_lat": rec.get("center_lat"),
        "center_lon": rec.get("center_lon"),
    }


def ocha_upper(rec, level):
    """Older OCHA layout: ADM2_EN / ADM2_PCODE. Used by the South Sudan files."""
    p = f"ADM{level}"
    return {
        "name": _clean(rec.get(f"{p}_EN")),
        "pcode": _clean(rec.get(f"{p}_PCODE")),
        "parent_pcode": _clean(rec.get(f"ADM{level - 1}_PCODE")) if level else None,
        "ref_name": None,
        "name_alt": [],
        "ancestors": [_clean(rec.get(f"ADM{i}_EN")) for i in range(level)],
        "area_sqkm": rec.get("AREA_SQKM"),
        "valid_on": rec.get("validOn") or rec.get("date"),
        "version": None,
        "center_lat": None,
        "center_lon": None,
    }


def caf_camel(rec, level):
    """CAR (SIGCAF / REACH): admin2Name / admin2Pcod - camel case, truncated."""
    p = f"admin{level}"
    return {
        "name": _clean(rec.get(f"{p}Name")),
        "pcode": _clean(rec.get(f"{p}Pcod")),
        "parent_pcode": _clean(rec.get(f"admin{level - 1}Pcod")) if level else None,
        "ref_name": _clean(rec.get(f"{p}RefN")),
        "name_alt": [
            {"name": v, "lang": "fr"}
            for v in (_clean(rec.get(f"{p}AltN")), _clean(rec.get(f"{p}Al_1")))
            if v
        ],
        "ancestors": [_clean(rec.get(f"admin{i}Name")) for i in range(level)],
        "area_sqkm": None,
        "valid_on": None,
        "version": None,
        "center_lat": None,
        "center_lon": None,
    }


def gadm(rec, level):
    """GADM: NAME_3 / ID_3. No p-codes exist, so one is synthesised.

    Used for exactly one file - Sudan's ADM3, the only source the office holds
    below locality level for Sudan. Its parent names do not match OCHA's
    spellings ("Al Jazirah" against "Aj Jazirah"), so the loader resolves its
    parent by geometry instead. See load_boundaries.link_parents_spatially.
    """
    iso = _clean(rec.get("ISO")) or "SDN"
    return {
        "name": _clean(rec.get(f"NAME_{level}")),
        "pcode": f"{iso}-GADM{level}:{rec.get(f'ID_{level}')}",
        "parent_pcode": None,                       # resolved spatially, later
        "ref_name": _clean(rec.get(f"VARNAME_{level}")),
        "name_alt": [
            {"name": v, "lang": None}
            for v in [_clean(rec.get(f"NL_NAME_{level}")), _clean(rec.get(f"VARNAME_{level}"))]
            if v
        ],
        "ancestors": [_clean(rec.get(f"NAME_{i}")) for i in range(level)],
        "area_sqkm": None,
        "valid_on": None,
        "version": None,
        "center_lat": None,
        "center_lon": None,
    }


ADAPTERS = {
    "itos_lower": itos_lower,
    "ocha_upper": ocha_upper,
    "caf_camel": caf_camel,
    "gadm": gadm,
}


# ------------------------------------------------------------------- registry
# (relative path without .shp, iso3, country, level, schema, publisher, valid_on)
# Paths are relative to the admin boundary source folder (see settings).

_ITOS = "OCHA ITOS"

ADMIN_SOURCES = [
    # --- Sudan -------------------------------------------------------------
    ("sdn_admin_boundaries.shp/sdn_admin0", "SDN", "Sudan", 0, "itos_lower", _ITOS),
    ("sdn_admin_boundaries.shp/sdn_admin1", "SDN", "Sudan", 1, "itos_lower", _ITOS),
    ("sdn_admin_boundaries.shp/sdn_admin2", "SDN", "Sudan", 2, "itos_lower", _ITOS),
    # The only sub-locality geometry the office holds for Sudan, and a different
    # publisher from the three above - hence its own schema and a spatial parent.
    ("sdn_adm3/sdn_adm3", "SDN", "Sudan", 3, "gadm", "GADM"),
    # --- Chad --------------------------------------------------------------
    ("tcd_admin_boundaries.shp/tcd_admin0", "TCD", "Chad", 0, "itos_lower", _ITOS),
    ("tcd_admin_boundaries.shp/tcd_admin1", "TCD", "Chad", 1, "itos_lower", _ITOS),
    ("tcd_admin_boundaries.shp/tcd_admin2", "TCD", "Chad", 2, "itos_lower", _ITOS),
    # --- Ethiopia ----------------------------------------------------------
    ("eth_admin_boundaries.shp/eth_admin0", "ETH", "Ethiopia", 0, "itos_lower", _ITOS),
    ("eth_admin_boundaries.shp/eth_admin1", "ETH", "Ethiopia", 1, "itos_lower", _ITOS),
    ("eth_admin_boundaries.shp/eth_admin2", "ETH", "Ethiopia", 2, "itos_lower", _ITOS),
    ("eth_admin_boundaries.shp/eth_admin3", "ETH", "Ethiopia", 3, "itos_lower", _ITOS),
    # --- Egypt -------------------------------------------------------------
    ("egy_admin_boundaries.shp/egy_admin0", "EGY", "Egypt", 0, "itos_lower", _ITOS),
    ("egy_admin_boundaries.shp/egy_admin1", "EGY", "Egypt", 1, "itos_lower", _ITOS),
    ("egy_admin_boundaries.shp/egy_admin2", "EGY", "Egypt", 2, "itos_lower", _ITOS),
    ("egy_admin_boundaries.shp/egy_admin3", "EGY", "Egypt", 3, "itos_lower", _ITOS),
    # --- Libya -------------------------------------------------------------
    # Note: Libya's ADM1 is three regions. The 22 units the dashboard used to
    # call Libyan "states" are ADM2 here, which is what they actually are.
    ("lby_admin_boundaries.shp/lby_admin0", "LBY", "Libya", 0, "itos_lower", _ITOS),
    ("lby_admin_boundaries.shp/lby_admin1", "LBY", "Libya", 1, "itos_lower", _ITOS),
    ("lby_admin_boundaries.shp/lby_admin2", "LBY", "Libya", 2, "itos_lower", _ITOS),
    # --- Uganda ------------------------------------------------------------
    ("uga_admin_boundaries.shp/uga_admin0", "UGA", "Uganda", 0, "itos_lower", _ITOS),
    ("uga_admin_boundaries.shp/uga_admin1", "UGA", "Uganda", 1, "itos_lower", _ITOS),
    ("uga_admin_boundaries.shp/uga_admin2", "UGA", "Uganda", 2, "itos_lower", _ITOS),
    ("uga_admin_boundaries.shp/uga_admin3", "UGA", "Uganda", 3, "itos_lower", _ITOS),
    ("uga_admin_boundaries.shp/uga_admin4", "UGA", "Uganda", 4, "itos_lower", _ITOS),
    # --- Eritrea -----------------------------------------------------------
    # Eritrea already appears as a country on tag rows but has never had a
    # polygon, so its reporting could not be placed anywhere.
    ("eri_admin_boundaries.shp/eri_admin0", "ERI", "Eritrea", 0, "itos_lower", _ITOS),
    ("eri_admin_boundaries.shp/eri_admin1", "ERI", "Eritrea", 1, "itos_lower", _ITOS),
    ("eri_admin_boundaries.shp/eri_admin2", "ERI", "Eritrea", 2, "itos_lower", _ITOS),
    # --- Central African Republic ------------------------------------------
    ("car_admin_boundaries.shp/CAF_admbnda_adm0_200k_sigcaf_reach_itos",
     "CAF", "Central African Republic", 0, "caf_camel", "SIGCAF / REACH / OCHA"),
    ("car_admin_boundaries.shp/caf_admbnda_adm1_200k_sigcaf_reach_itos_Ocha",
     "CAF", "Central African Republic", 1, "caf_camel", "SIGCAF / REACH / OCHA"),
    ("car_admin_boundaries.shp/caf_admbnda_adm2_200k_sigcaf_reach_itos_Ocha",
     "CAF", "Central African Republic", 2, "caf_camel", "SIGCAF / REACH / OCHA"),
    ("car_admin_boundaries.shp/caf_admbnda_adm3_200k_sigcaf_reach_itos_ocha",
     "CAF", "Central African Republic", 3, "caf_camel", "SIGCAF / REACH / OCHA"),
    ("car_admin_boundaries.shp/caf_admbnda_adm4_reach_ocha",
     "CAF", "Central African Republic", 4, "caf_camel", "SIGCAF / REACH / OCHA"),
    # --- South Sudan -------------------------------------------------------
    ("ssd_admbnda_imwg_nbs_20230829_shp/ssd_admbnda_imwg_nbs_20230829_SHP/"
     "ssd_admbnda_adm0_imwg_nbs_20230829", "SSD", "South Sudan", 0, "ocha_upper", "IMWG / NBS"),
    ("ssd_admbnda_imwg_nbs_20230829_shp/ssd_admbnda_imwg_nbs_20230829_SHP/"
     "ssd_admbnda_adm1_imwg_nbs_20230829", "SSD", "South Sudan", 1, "ocha_upper", "IMWG / NBS"),
    ("ssd_admbnda_imwg_nbs_20230829_shp/ssd_admbnda_imwg_nbs_20230829_SHP/"
     "ssd_admbnda_adm2_imwg_nbs_20230829", "SSD", "South Sudan", 2, "ocha_upper", "IMWG / NBS"),
    ("ssd_admbnda_imwg_nbs_20230829_shp/ssd_admbnda_imwg_nbs_20230829_SHP/"
     "ssd_admbnda_adm3_imwg_nbs_20230829", "SSD", "South Sudan", 3, "ocha_upper", "IMWG / NBS"),
]

# What the §5.1 table of the spec says each file should contain. The audit
# compares the database against this, so a half-read file is caught rather than
# quietly producing a map with holes in it.
EXPECTED_COUNTS = {
    ("SDN", 0): 1, ("SDN", 1): 19, ("SDN", 2): 189, ("SDN", 3): 237,
    ("TCD", 0): 1, ("TCD", 1): 23, ("TCD", 2): 70,
    ("ETH", 0): 1, ("ETH", 1): 13, ("ETH", 2): 92, ("ETH", 3): 1082,
    ("EGY", 0): 1, ("EGY", 1): 27, ("EGY", 2): 365, ("EGY", 3): 5716,
    ("LBY", 0): 1, ("LBY", 1): 3, ("LBY", 2): 22,
    ("UGA", 0): 1, ("UGA", 1): 4, ("UGA", 2): 135, ("UGA", 3): 208, ("UGA", 4): 1520,
    ("ERI", 0): 1, ("ERI", 1): 6, ("ERI", 2): 58,
    ("CAF", 0): 1, ("CAF", 1): 17, ("CAF", 2): 73, ("CAF", 3): 176, ("CAF", 4): 202,
    ("SSD", 0): 1, ("SSD", 1): 10, ("SSD", 2): 79, ("SSD", 3): 512,
}


# ------------------------------------------------- physical and extra layers
# (relative path without .shp, layer name, kind, iso3 or None, publisher)
FEATURE_SOURCES_PHYSICAL = [
    ("10m_rivers_lake_centerlines", "rivers", "river", None, "Natural Earth"),
    ("ne_10m_lakes", "lakes", "lake", None, "Natural Earth"),
    ("World water body limits polygons", "waterbodies", "waterbody", None, "IFRC / ICRC"),
    ("OCHA National and Regional Capital", "capitals", "capital", None, "OCHA"),
    ("IFRC_Regions", "ifrc_regions", "region", None, "IFRC"),
    # The separator in this filename is an em dash, not a hyphen. Written as an
    # escape so that it survives editors and terminals that would helpfully
    # "fix" it into something the filesystem then cannot find.
    ("ICRC Admin Boarders WD Internal — icrc_admin0_borders_wd_internal",
     "icrc_admin0", "border", None, "ICRC"),
]

# Held in the same folder as the admin boundaries. Loaded and available; not
# wired into the dashboard in this pass.
FEATURE_SOURCES_OPS = [
    ("sdn_road2021/SDN_Road2021/SDN_Road2021", "roads", "road", "SDN", "OCHA Sudan"),
    ("tcd_a_hlt_districtssanitaires_msp_2020/tcd_a_hlt_districtsSanitaires_msp_2020",
     "health_districts", "health_district", "TCD", "MSP Tchad"),
    ("tcd_p_hum_refugeesidps_ocha/tcd_p_hum_refugeesidps_ocha",
     "displacement_sites", "site", "TCD", "OCHA Chad"),
    ("eth_refugee_camps_unhcr_2019/Eth_refugee_camps_unhcr_2019",
     "refugee_camps", "camp", "ETH", "UNHCR"),
    ("unhcr_refugee_11jan21/UNHCR_Refugee_11Jan21", "refugee_sites", "site", None, "UNHCR"),
]


def read_encoding(base_path):
    """Which character set is this .dbf in?

    The publisher usually says, in a .cpg (or .cst) file beside the data. When
    nobody says, cp1252 is the right guess for this corpus: the only files
    without a .cpg are the CAR ones, and they are cp1252. Never UTF-8 as a
    fallback - that is the guess that turns 'Ndele' into an exception or, worse,
    into mojibake that then enters the place-name index.
    """
    for ext in (".cpg", ".CPG", ".cst", ".CST"):
        if os.path.exists(base_path + ext):
            declared = open(base_path + ext, encoding="ascii", errors="replace").read().strip()
            if declared:
                return declared
    return "cp1252"


def check_wgs84(base_path):
    """Refuse anything that is not in plain latitude and longitude.

    Everything downstream - the browser, the containment tests, the p-code
    joins - assumes degrees on WGS84. A projected file would load without
    complaint and put the country somewhere off the coast of Africa, so this is
    a hard stop rather than a warning.
    """
    prj_path = base_path + ".prj"
    if not os.path.exists(prj_path):
        raise ValueError(f"{base_path}: no .prj, so the projection cannot be confirmed")
    prj = open(prj_path, encoding="ascii", errors="replace").read()
    if "WGS_1984" not in prj and "WGS 84" not in prj:
        raise ValueError(f"{base_path}: not WGS84 - refusing to load\n  {prj[:120]}")
    if "PROJCS" in prj:
        raise ValueError(f"{base_path}: projected coordinates, expected degrees")
    return prj.strip()
