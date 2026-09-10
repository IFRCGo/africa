"""`python manage.py load_fewsnet_units <file.json>` - place FEWS NET phases on the map.

WHY THIS IS SEPARATE FROM THE PHASES. FEWS NET's classification endpoint gives a
phase per unit code and no geometry at all, so Ethiopia - which IPC has not
analysed since 2021 - had real, current food-security data that could not be
drawn. Its geographic-unit endpoint carries a centroid for each of those codes,
which is enough to show the country.

A POINT, NOT A DISTRICT, AND THE MAP SHOULD NOT PRETEND OTHERWISE. FEWS NET does
not publish the polygon through this API, so each area becomes a dot at the centre
of its zone. That is a weaker statement than IPC's shaded areas and it is drawn as
a dot precisely so nobody reads it as a boundary.

    docker compose exec web python manage.py load_fewsnet_units \\
        data_pipeline/mcp_cache/fewsnet_units/ETH.json --iso3 ETH
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Attach FEWS NET unit centroids to food_security rows that have no geometry."

    def add_arguments(self, parser):
        parser.add_argument("path", help="A recorded get_geographic_units payload")
        parser.add_argument("--iso3", required=True, help="Country the units belong to")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("results", payload) if isinstance(payload, dict) else payload

        # fnid -> centroid, for the unit type the classifications actually use.
        centroids = {}
        for u in records:
            c = u.get("centroid")
            fnid = u.get("fnid")
            if not fnid or not c or len(c) != 2:
                continue
            centroids[fnid] = (float(c[0]), float(c[1]))
        if not centroids:
            raise CommandError(
                f"{path.name}: no unit centroids found. A payload without them cannot "
                "place anything, and recording that as success would leave the layer "
                "silently empty."
            )

        iso3 = options["iso3"]
        with connection.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT area_id FROM food_security
                 WHERE iso3 = %s AND source = 'fewsnet' AND geom IS NULL
            """, [iso3])
            wanted = [r[0] for r in cur.fetchall()]

        matched = [a for a in wanted if a in centroids]
        self.stdout.write(f"{path.name}: {len(centroids)} unit centroids")
        self.stdout.write(f"  {len(matched)} of {len(wanted)} unplaced areas can be placed")
        missing = [a for a in wanted if a not in centroids]
        if missing:
            self.stdout.write(f"  {len(missing)} still unplaced, e.g. {missing[:3]}")
        if options["dry_run"] or not matched:
            return

        with connection.cursor() as cur:
            for area_id in matched:
                lon, lat = centroids[area_id]
                cur.execute("""
                    UPDATE food_security
                       SET geom     = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                           geom_web = ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                     WHERE iso3 = %s AND source = 'fewsnet' AND area_id = %s
                """, [lon, lat, lon, lat, iso3, area_id])
        self.stdout.write(self.style.SUCCESS(f"  placed {len(matched)} areas"))
