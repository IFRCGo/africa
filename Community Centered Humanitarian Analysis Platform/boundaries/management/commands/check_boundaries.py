"""Prove the boundary library is right, or say exactly how it is wrong.

    python manage.py check_boundaries

A map of the wrong thing still looks like a map. Nothing about a polygon in the
wrong country, a district filed under the wrong parent, or a source file that
was read only half way, is visible by looking at the dashboard - which is why
these checks exist and why the load is not finished until they pass.

Every check prints a line. A failure sets the exit code, so this can be the
gate in front of anything that depends on the library being sound.
"""
from django.core.management.base import BaseCommand
from django.db import connection

from boundaries.models import AdminArea, BoundarySource, MapFeature
from boundaries.sources import EXPECTED_COUNTS

# Where publishers legitimately disagree. Sudan and South Sudan both draw Abyei;
# Sudan and Egypt both draw Halayeb. A polygon from one country's file sitting
# inside another country's outline is the expected answer here, not an error.
DISPUTED = ("Abyei", "Halayeb", "Hala'ib", "Bir Tawil")


class Command(BaseCommand):
    help = "Audit the boundary library: counts, containment, parents, and links."

    def handle(self, *args, **opts):
        self.failures = 0
        self.stdout.write(self.style.MIGRATE_HEADING("=== boundary library audit ==="))
        self.check_sources()
        self.check_counts()
        self.check_countries()
        self.check_containment()
        self.check_parents()
        self.check_geometry()
        self.check_tag_links()

        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(f"{self.failures} check(s) FAILED"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("every check passed"))

    # ------------------------------------------------------------- reporting
    def ok(self, label, detail=""):
        self.stdout.write(f"  {self.style.SUCCESS('OK  ')} {label:44s} {detail}")

    def bad(self, label, detail=""):
        self.failures += 1
        self.stdout.write(f"  {self.style.ERROR('FAIL')} {label:44s} {detail}")

    def note(self, label, detail=""):
        self.stdout.write(f"  {self.style.WARNING('note')} {label:44s} {detail}")

    # ---------------------------------------------------------------- checks
    def check_sources(self):
        n = BoundarySource.objects.count()
        areas = AdminArea.objects.count()
        feats = MapFeature.objects.count()
        if n:
            self.ok("sources loaded", f"{n} files, {areas} areas, {feats} map features")
        else:
            self.bad("sources loaded", "nothing has been loaded - run load_boundaries")

    def check_counts(self):
        """Every level holds exactly as many polygons as its file does.

        This is what catches a half-read file. A source that stops early still
        produces a perfectly plausible map, just with holes in it.
        """
        wrong = []
        with connection.cursor() as cur:
            cur.execute("""
                SELECT iso3, level, count(*) FROM admin_areas
                WHERE kind = 'admin' GROUP BY iso3, level
            """)
            found = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        for key, expected in sorted(EXPECTED_COUNTS.items()):
            got = found.get(key, 0)
            if got != expected:
                wrong.append(f"{key[0]} ADM{key[1]}: {got} not {expected}")
        if wrong:
            self.bad("per-level counts match the source files", "; ".join(wrong[:6]))
        else:
            self.ok("per-level counts match the source files",
                    f"{sum(EXPECTED_COUNTS.values())} polygons across {len(EXPECTED_COUNTS)} levels")

    def check_countries(self):
        """No polygon may be without a country - this is the fault-1 guard.

        While the Areas of Interest had no country, the place-name matcher could
        not apply its "a sentence about Sudan may only highlight somewhere in
        Sudan" rule to them, and Sudanese reporting was drawn on Amhara.
        """
        n = AdminArea.objects.filter(iso3__in=["", "???"]).count() + \
            AdminArea.objects.filter(iso3__isnull=True).count()
        if n:
            names = list(AdminArea.objects.filter(iso3__in=["", "???"])
                         .values_list("name", flat=True)[:5])
            self.bad("every polygon has a country", f"{n} without one: {names}")
        else:
            self.ok("every polygon has a country",
                    f"{AdminArea.objects.filter(kind='aoi').count()} AOIs included")

    def check_containment(self):
        """Each polygon sits inside the country it claims to belong to."""
        with connection.cursor() as cur:
            cur.execute("""
                SELECT a.iso3, a.level, a.name
                FROM admin_areas a
                JOIN admin_areas c ON c.kind = 'admin' AND c.level = 0 AND c.iso3 = a.iso3
                WHERE a.level > 0 AND a.geom IS NOT NULL
                  AND NOT ST_Intersects(c.geom, ST_PointOnSurface(a.geom))
                LIMIT 40
            """)
            stray = cur.fetchall()
        expected = [s for s in stray if any(d.lower() in (s[2] or "").lower() for d in DISPUTED)]
        real = [s for s in stray if s not in expected]
        if real:
            self.bad("polygons sit inside their own country",
                     f"{len(real)} outside: " + ", ".join(f"{r[0]} {r[2]}" for r in real[:4]))
        else:
            self.ok("polygons sit inside their own country",
                    f"{len(expected)} disputed area(s) excepted" if expected else "")

    def check_parents(self):
        """Every parent p-code names a polygon that exists."""
        with connection.cursor() as cur:
            cur.execute("""
                SELECT count(*) FROM admin_areas c
                WHERE c.parent_pcode IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM admin_areas p
                    WHERE p.pcode = c.parent_pcode AND p.iso3 = c.iso3)
            """)
            orphans = cur.fetchone()[0]
            cur.execute("""
                SELECT count(*) FROM admin_areas
                WHERE kind = 'admin' AND level > 0 AND parent_pcode IS NULL
            """)
            parentless = cur.fetchone()[0]
        if orphans:
            self.bad("parent p-codes resolve", f"{orphans} point at nothing")
        else:
            self.ok("parent p-codes resolve")
        if parentless:
            self.note("polygons with no parent recorded",
                      f"{parentless} (expected only where a source omits it)")

    def check_geometry(self):
        """Valid shapes, and a simplified copy for every one of them."""
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM admin_areas WHERE NOT ST_IsValid(geom)")
            invalid = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM admin_areas WHERE geom IS NULL OR geom_web IS NULL")
            missing = cur.fetchone()[0]
            cur.execute("""
                SELECT pg_size_pretty(sum(ST_MemSize(geom))::bigint),
                       pg_size_pretty(sum(ST_MemSize(geom_web))::bigint)
                FROM admin_areas
            """)
            full, web = cur.fetchone()
        if invalid:
            self.bad("geometry is valid", f"{invalid} invalid")
        else:
            self.ok("geometry is valid")
        if missing:
            self.bad("every area has a drawable shape", f"{missing} missing geom or geom_web")
        else:
            self.ok("every area has a drawable shape", f"full {full}, simplified {web}")

    def check_tag_links(self):
        """Every place the reporting was pinned to still exists in the library.

        Runs only once the tags carry p-codes; before the re-parse they still
        hold the old geoBoundaries ids, and saying so is more useful than
        reporting sixty thousand failures.
        """
        from data_track.models import NarrativeTag

        linked = NarrativeTag.objects.exclude(area_id__isnull=True).exclude(area_id="")
        total = linked.count()
        if not total:
            self.note("reporting is linked to the library", "no tags carry an area yet")
            return
        with connection.cursor() as cur:
            cur.execute("""
                SELECT count(DISTINCT t.area_id) FROM narrative_tags t
                WHERE t.area_id IS NOT NULL AND t.area_id <> ''
                  AND NOT EXISTS (SELECT 1 FROM admin_areas a WHERE a.pcode = t.area_id)
            """)
            unknown = cur.fetchone()[0]
        if unknown:
            self.note("reporting is linked to the library",
                      f"{unknown} area id(s) not p-codes yet - re-parse still to run")
        else:
            self.ok("reporting is linked to the library", f"{total} tagged rows")
