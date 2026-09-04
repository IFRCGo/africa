"""`python manage.py build_aoi_ipc` - recompute the IPC phase of each Area of Interest.

This is a helper, not part of the normal pipeline. Run it after an analyst has
refreshed the IPC pulls in data_pipeline/mcp_cache/. It takes each IPC analysis
area, works out which IFRC Area of Interest its centre falls inside
(point-in-polygon), keeps the worst phase per area, and writes:

    mcp_cache/aoi_ipc_phases.json   the small cache step 6 reads
    dashboard/data/aoi_ipc.geojson        the map layer itself

Afterwards run `manage.py run_pipeline --only s06,s07` so every other layer is
rebuilt from the same caches.
"""
from django.core.management.base import BaseCommand

from data_pipeline.steps import _build_aoi_ipc


class Command(BaseCommand):
    help = "Recompute the IPC phase of each IFRC Area of Interest from the cached IPC pulls."

    def handle(self, *args, **options):
        _build_aoi_ipc.run()
