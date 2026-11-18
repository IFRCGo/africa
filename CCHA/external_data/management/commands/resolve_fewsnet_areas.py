"""`python manage.py resolve_fewsnet_areas <phases.json> --iso3 ETH`

Give FEWS NET's food-security rows a shape, by matching them to the boundary
library rather than by fetching more geometry.

THE PROBLEM. FEWS NET's classification endpoint returns a phase per unit code and
no geometry, so Ethiopia - which IPC has not analysed since May 2021 - had current
food-security data that could not be drawn. Its geographic-unit endpoint does carry
a centroid, but only a centroid, and paging 12,812 units to collect them is a lot
of fetching for a layer of dots.

THE BETTER ROUTE. Each classification already names its place in full -
"Abaala, Kilbati, Afar, Ethiopia" - and the boundary library already holds
Ethiopia's woredas and zones with their polygons. Matching on that name gives the
real boundary, so Ethiopia shades like every other country instead of being
scattered as points, and it costs no extra pulls at all.

MATCHING IS TRIED DEEPEST FIRST AND RECORDED. A woreda match is the true unit; a
zone match is a coarser answer and is only taken when the woreda cannot be found.
Anything still unmatched is reported by name and left without geometry, because a
guess placed on a map is indistinguishable from a fact.
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


def _norm(name):
    """Compare place names without punctuation, case or spacing getting in the way."""
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class Command(BaseCommand):
    help = "Match FEWS NET classification units to boundary-library polygons."

    def add_arguments(self, parser):
        parser.add_argument("path", help="A recorded get_ipc_phases payload")
        parser.add_argument("--iso3", required=True)
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("results", payload) if isinstance(payload, dict) else payload
        iso3 = options["iso3"]

        # fnid -> the admin names FEWS NET spells out, finest first.
        # "Abaala, Kilbati, Afar, Ethiopia" -> ["Abaala", "Kilbati", "Afar"]
        hierarchy = {}
        for r in records:
            fnid = r.get("fnid")
            full = r.get("geographic_unit_full_name") or ""
            if not fnid or not full:
                continue
            parts = [p.strip() for p in full.split(",") if p.strip()]
            if len(parts) > 1:
                parts = parts[:-1]          # drop the country
            hierarchy.setdefault(fnid, parts)
        if not hierarchy:
            raise CommandError(
                f"{path.name}: no unit names found - nothing to match against."
            )

        # The library's polygons for this country, by level and normalised name.
        with connection.cursor() as cur:
            cur.execute("""
                SELECT pcode, name, level FROM admin_areas
                 WHERE iso3 = %s AND kind = 'admin' AND geom IS NOT NULL
            """, [iso3])
            by_level = {}
            for pcode, name, level in cur.fetchall():
                by_level.setdefault(level, {}).setdefault(_norm(name), pcode)

            cur.execute("""
                SELECT DISTINCT area_id FROM food_security
                 WHERE iso3 = %s AND source = 'fewsnet' AND geom IS NULL
            """, [iso3])
            wanted = [r[0] for r in cur.fetchall()]

        deepest = sorted(by_level, reverse=True)
        plan, unmatched = {}, []
        for fnid in wanted:
            names = hierarchy.get(fnid) or []
            hit = None
            # The first name is the unit itself; the ones after it are its
            # parents. Try the unit at the deepest level that knows it, then walk
            # outwards - a zone is a coarser but still true answer.
            for depth, nm in enumerate(names):
                key = _norm(nm)
                for level in deepest:
                    if key in by_level.get(level, {}):
                        hit = (by_level[level][key], level, depth)
                        break
                if hit:
                    break
            if hit:
                plan[fnid] = hit
            else:
                unmatched.append(names[0] if names else fnid)

        levels = {}
        for _, level, depth in plan.values():
            levels[(level, depth)] = levels.get((level, depth), 0) + 1
        self.stdout.write(f"{path.name}: {len(wanted)} unplaced areas")
        self.stdout.write(f"  matched {len(plan)}")
        for (level, depth), n in sorted(levels.items()):
            what = "the unit itself" if depth == 0 else f"its parent ({depth} up)"
            self.stdout.write(f"    {n:>5} at ADM{level}, matched on {what}")
        if unmatched:
            self.stdout.write(f"  {len(unmatched)} unmatched, e.g. {sorted(set(unmatched))[:5]}")
        if options["dry_run"] or not plan:
            return

        # Copy the polygon onto the row. The boundary library keeps the geometry;
        # this duplicates it so the food-security layer can be drawn from one
        # table, the same way IPC's own areas are.
        with connection.cursor() as cur:
            for fnid, (pcode, level, _depth) in plan.items():
                cur.execute("""
                    UPDATE food_security f
                       SET admin_pcode = %s,
                           geom     = a.geom,
                           geom_web = a.geom_web
                      FROM admin_areas a
                     WHERE a.iso3 = %s AND a.pcode = %s AND a.level = %s
                       AND a.kind = 'admin'
                       AND f.iso3 = %s AND f.source = 'fewsnet' AND f.area_id = %s
                """, [pcode, iso3, pcode, level, iso3, fnid])
        self.stdout.write(self.style.SUCCESS(f"  placed {len(plan)} areas on real boundaries"))
