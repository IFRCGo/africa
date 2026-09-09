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

Idempotent - update_or_create throughout, so running it twice is a no-op.
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from data_pipeline.steps.s06_mcp_layers import CROSSINGS, REF_COUNTRIES, SEASONAL
from external_data.models import (BorderCrossing, MovementPattern, SeasonalCalendar,
                                  SourceSync)

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
