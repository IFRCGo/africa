"""`python manage.py seed_external` - move the hand-typed dictionaries into tables.

Three dictionaries in data_pipeline/steps/s06_mcp_layers.py are data pretending to
be code: CROSSINGS, SEASONAL and REF_COUNTRIES. This command copies them into the
database once, after which they are deleted from that file.

They are not all the same kind of thing, and the seeding treats them differently:

  CROSSINGS      genuinely curated. No API publishes "the crossings that matter to
                 this operation". Stays source='curated' permanently.
  REF_COUNTRIES  real UNHCR figures, transcribed by hand. Becomes source='unhcr'
                 movement rows, and the per-country caveats become source_sync
                 notes - Egypt's especially, which is the difference between a
                 caveated number and a misleading one.
  SEASONAL       claims in its own comment to come from FEWS NET get_seasons, and
                 does not: it is five bands somebody typed for Sudan. Seeded as
                 source='curated' so the real pull can replace it, after which
                 these rows are deleted.

A fourth list joined them later, PLACE_COORDINATES, which was never in s06: it
is the starting content of the place_coordinates table - coordinates for places
that have no polygon at all. See the comment above it.

Idempotent - update_or_create throughout, so running it twice is a no-op. The
exception is PLACE_COORDINATES, which uses get_or_create so that running it
twice cannot undo a coordinate corrected in the admin.
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from external_data.models import (BorderCrossing, MovementPattern, PlaceCoordinate,
                                  SeasonalCalendar, SourceSync)

# ---------------------------------------------------------------------------
# THE THREE DICTIONARIES, MOVED HERE FROM s06_mcp_layers.py.
#
# In the pipeline step they were data pretending to be code: every run rebuilt
# the dashboard from Python literals no source could be checked against. Seeding
# is the only thing that still reads them, so they live with it. After this
# command has run once the database is where they are maintained, and s06 reads
# the tables.
# ---------------------------------------------------------------------------

CROSSINGS = [
    {"name": "El Geneina – Adré", "country": "Chad", "lon": 22.20, "lat": 13.47,
     "corridor": "sudan-chad", "return_corridor": "chad-sudan-return"},
    {"name": "Tiné", "country": "Chad", "lon": 22.30, "lat": 14.94,
     "corridor": "sudan-chad", "return_corridor": "chad-sudan-return"},
    {"name": "Um Dukhun – Am Dafok", "country": "Central African Republic", "lon": 23.45, "lat": 11.00,
     "corridor": "sudan-car", "return_corridor": None},
    {"name": "Wadi Halfa – Argeen / Ashkeet", "country": "Egypt", "lon": 31.55, "lat": 21.95,
     "corridor": "sudan-egypt", "return_corridor": "egypt-sudan-return"},
    {"name": "Qustul – Ashkeet", "country": "Egypt", "lon": 31.50, "lat": 22.00,
     "corridor": "sudan-egypt", "return_corridor": "egypt-sudan-return"},
    {"name": "Sudan–Libya desert route (Dongola–Kufra)", "country": "Libya", "lon": 24.40, "lat": 20.30,
     "corridor": "sudan-libya", "return_corridor": "libya-sudan-return"},
    {"name": "Joda – Renk", "country": "South Sudan", "lon": 32.41, "lat": 11.90,
     "corridor": "sudan-south_sudan", "return_corridor": "south_sudan-sudan-return"},
    {"name": "Gallabat – Metema", "country": "Ethiopia", "lon": 36.16, "lat": 12.97,
     "corridor": "sudan-ethiopia", "return_corridor": None},
    {"name": "Hamdayet", "country": "Ethiopia", "lon": 36.35, "lat": 14.30,
     "corridor": "sudan-ethiopia", "return_corridor": None},
]

# ---------------------------------------------------------------------------
# NOT ONE OF THE THREE. These arrived later and for a different reason: they are
# the FIRST rows of place_coordinates, seeded here because this command is where
# this project puts curated starting values.
#
# Egypt's Kobo submission lists Qustul and Arkeen under "Districts where these
# services are offered", and neither is a district - they are the Egyptian side
# of the two Sudan crossings. No p-code exists for either, so load_hsps left both
# at lat=None and the dashboard, which draws only rows that have a coordinate,
# showed neither. These two points are what fixes that.
#
# THE TABLE IS WHERE THEY LIVE NOW, not this list: PlaceCoordinate is editable at
# /admin/external_data/placecoordinate/ precisely because no loader writes it, so
# a corrected coordinate is typed there and picked up by the next load_hsps. This
# list only seeds a database that has never had them - see _seed_place_coordinates
# for why it is the one seed here that will not overwrite an existing row.
PLACE_COORDINATES = [
    {"iso3": "EGY", "name": "Qustul", "lat": 22.233333, "lon": 31.616667,
     "note": "22°14'00\" N, 31°37'00\" E. Border reception point at the "
             "Sudan frontier, not an administrative district, so no polygon "
             "carries it."},
    {"iso3": "EGY", "name": "Arkeen", "lat": 22.004175, "lon": 31.146239,
     "note": "22°00'15.03\" N, 31°08'46.46\" E. Also spelled Argeen. "
             "Border reception point at the Sudan frontier, not an "
             "administrative district."},
]

REF_COUNTRIES = {
    "Chad":        {"2022": 403846, "2023": 923323, "2024": 1109357, "anchor": [21.9, 13.9]},
    "South Sudan": {"2022": 290740, "2023": 359581, "2024": 487652,  "anchor": [32.9, 10.5]},
    "Egypt":       {"2022": 25476,  "2023": 26213,  "2024": 27696,   "anchor": [31.0, 24.0],
                    "note": "UNHCR-registered only; actual Sudanese presence far larger (gov. est. >1M)"},
    "Ethiopia":    {"2022": 48020,  "2023": 77424,  "2024": 90442,   "anchor": [36.5, 12.6]},
    "Central African Republic": {"2022": 478, "2023": 21816, "2024": 29932, "anchor": [22.8, 9.5]},
    "Libya":       {"2022": 1133,   "2023": 975,    "2024": 199388,  "anchor": [23.3, 24.2]},
    "Uganda":      {"2022": 2871,   "2023": 14971,  "2024": 65367,   "anchor": [32.4, 2.5]},
}

SEASONAL = {
    "source": "FEWS NET seasonal calendar for Sudan (get_seasons API).",
    "items": [
        {"label": "Lean / hunger season", "months": [5, 6, 7, 8, 9, 10], "color": "#e67e22",
         "note": "FEWS NET nutrition lean season (May–Oct)"},
        {"label": "Rainy / growing season", "months": [6, 7, 8, 9, 10], "color": "#3498db",
         "note": "Main agricultural season (cultivation)"},
        {"label": "Main (rainfed) harvest", "months": [11, 12, 1], "color": "#27ae60",
         "note": "Traditional & mechanized rainfed harvest (Nov–Jan)"},
        {"label": "Irrigated harvest", "months": [3], "color": "#9ccc65",
         "note": "Irrigated harvest (March)"},
        {"label": "Post-harvest / dry season", "months": [1, 2, 3, 4], "color": "#c9a14a",
         "note": "Dry post-harvest period (Jan–Apr)"},
    ],
}

# The crossings name the far-side country; these are its ISO3 codes.
COUNTRY_TO_ISO3 = {
    "Chad": "TCD", "Central African Republic": "CAF", "Egypt": "EGY",
    "Libya": "LBY", "South Sudan": "SSD", "Ethiopia": "ETH", "Uganda": "UGA",
    "Sudan": "SDN",
}


class Command(BaseCommand):
    help = "Seed the curated crossings, the Sudan calendar and the UNHCR totals."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"border crossings: {self._seed_crossings()}")
        self.stdout.write(f"seasonal bands:   {self._seed_seasonal()}")
        self.stdout.write(f"refugee rows:     {self._seed_refugees()}")
        self.stdout.write(f"place coords:     {self._seed_place_coordinates()}")

    def _seed_crossings(self):
        for c in CROSSINGS:
            BorderCrossing.objects.update_or_create(
                name=c["name"],
                defaults={
                    "country": c["country"],
                    "iso3": COUNTRY_TO_ISO3.get(c["country"], ""),
                    "lon": c["lon"],
                    "lat": c["lat"],
                    "corridor": c.get("corridor"),
                    # Already None in the source for the crossings with no observed
                    # return movement; kept None rather than coerced to "".
                    "return_corridor": c.get("return_corridor"),
                    "source": "curated",
                },
            )
        return BorderCrossing.objects.count()

    def _seed_place_coordinates(self):
        """get_or_create, NOT update_or_create - the one seed here that differs.

        The other three restore their dictionary over whatever is in the table,
        which is right for them: a loader owns those rows and the dictionary is
        the record of what was typed. place_coordinates is the opposite. It
        exists so a coordinate can be corrected in the admin, and re-seeding over
        a correction would make this list the authority again - the table would
        be a cache of the code rather than its own record, which is precisely the
        arrangement it was created to avoid.

        So: this fills an empty table and then never touches it. Deleting a row
        and re-running is how you get the seeded value back.
        """
        for p in PLACE_COORDINATES:
            PlaceCoordinate.objects.get_or_create(
                iso3=p["iso3"], name=p["name"],
                defaults={"lat": p["lat"], "lon": p["lon"],
                          "note": p["note"], "source": "curated"},
            )
        return PlaceCoordinate.objects.count()

    def _seed_seasonal(self):
        for i, item in enumerate(SEASONAL["items"]):
            months = item["months"]
            SeasonalCalendar.objects.update_or_create(
                source="curated", iso3="SDN", admin_pcode=None,
                purpose="NutritionIndicator", label=item["label"],
                defaults={
                    "country_name": "Sudan",
                    "source_ref": "hand-typed",
                    "season_type": _season_type(item["label"]),
                    # The dict lists every month a band covers; the table stores
                    # its span. Contiguous in all five cases, checked by eye.
                    "start_month": months[0],
                    "end_month": months[-1],
                    "description": item.get("note", ""),
                    "aliases": [],
                    "display_order": i,
                },
            )
        return SeasonalCalendar.objects.filter(source="curated").count()

    def _seed_refugees(self):
        written = 0
        for country, d in REF_COUNTRIES.items():
            iso3 = COUNTRY_TO_ISO3.get(country)
            if not iso3:
                continue
            for year in ("2022", "2023", "2024"):
                if year not in d:
                    continue
                MovementPattern.objects.update_or_create(
                    source="unhcr", metric="refugees", iso3=iso3, admin_pcode=None,
                    place_name=country, date=date(int(year), 7, 1),
                    population_group="sudanese_refugees",
                    defaults={
                        "admin_level": 0,
                        "value": d[year],
                        "unit": "individuals",
                        "source_dataset": "get_refugees",
                    },
                )
                written += 1

            sync, _ = SourceSync.objects.get_or_create(
                source="unhcr", dataset="refugees", iso3=iso3, variant="",
            )
            sync.tool = "get_refugees"
            sync.high_water_date = date(2024, 7, 1)
            sync.row_count = MovementPattern.objects.filter(
                source="unhcr", metric="refugees", iso3=iso3
            ).count()
            # The ceiling first, so a refresh that correctly returns nothing reads
            # as "already current" rather than "broken", then the country's own
            # caveat where there is one.
            note = "UNHCR publishes this annually; latest release 2024."
            if d.get("note"):
                note = f"{note} {d['note']}"
            sync.notes = note
            sync.save()
        return written


def _season_type(label):
    """The kind of season, read from the label the dict already uses."""
    low = label.lower()
    if "lean" in low or "hunger" in low:
        return "Lean"
    if "harvest" in low:
        return "Harvest"
    if "rain" in low or "growing" in low:
        return "Rainy"
    return "Dry"
