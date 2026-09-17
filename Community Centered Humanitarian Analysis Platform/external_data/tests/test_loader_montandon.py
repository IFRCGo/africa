"""Montandon loaders: rows, clustering, the country trap, and where a point is.

The failure this file exists to prevent is the quiet one: an item carrying two
countries silently overwriting the first country's row on the second country's
pull. It went unnoticed in `movement_patterns` once already, where 234 rows
collapsed to 6.
"""
import json
from datetime import date
from pathlib import Path

from django.db import connection
from django.test import TestCase

from boundaries.models import AdminArea, BoundarySource
from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load
from external_data.models import HazardEvent, HazardImpact, SourceSync

FIXTURES = Path(__file__).parent / "fixtures"


def payload(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class EventLoaderTests(TestCase):
    def setUp(self):
        self.loader = LOADERS["montandon_events"]()
        SourceSync.objects.create(source="montandon", dataset="hazard_events",
                                  iso3="SDN", variant="")

    def load_sdn(self):
        return load(self.loader, payload("montandon_events_sdn.json"), "SDN",
                    context={"iso3": "SDN"})

    def test_it_writes_one_row_per_event(self):
        result = self.load_sdn()
        self.assertEqual(result.written, 3)
        self.assertEqual(HazardEvent.objects.count(), 3)

    def test_source_is_montandon_and_the_publisher_is_the_collection(self):
        """Writing 'gdacs' into source makes load() count row_count as zero
        forever, and the admin reports '0 rows' after every good pull."""
        self.load_sdn()
        self.assertEqual(set(HazardEvent.objects.values_list("source", flat=True)),
                         {"montandon"})
        self.assertEqual(
            set(HazardEvent.objects.values_list("collection", flat=True)),
            {"idmc-idu", "gdacs", "pdc"})

    def test_row_count_reaches_the_sync_row(self):
        result = self.load_sdn()
        self.assertEqual(result.sync.row_count, 3)

    def test_hazards_are_clustered_by_the_codebook(self):
        self.load_sdn()
        flood = HazardEvent.objects.get(event_id="idmc-idu-event-80585")
        self.assertEqual(flood.hazard_category, "hydrological")
        self.assertEqual(flood.hazard_sub, "floods")
        fire = HazardEvent.objects.get(event_id="gdacs-event-1027729")
        # nat-cli-wil-wil is climatological to UNDRR; the codebook wins.
        self.assertEqual(fire.hazard_category, "non_technological")
        self.assertEqual(fire.hazard_sub, "wildfires")

    def test_an_unknown_code_is_uncategorised_never_guessed(self):
        self.load_sdn()
        odd = HazardEvent.objects.get(event_id="pdc-event-unknown-code")
        self.assertEqual(odd.hazard_category, "uncategorised")
        self.assertEqual(odd.hazard_codes, ["ZZ9999", "XX"])

    def test_the_raw_codes_are_kept_so_the_clustering_can_be_audited(self):
        self.load_sdn()
        fire = HazardEvent.objects.get(event_id="gdacs-event-1027729")
        self.assertEqual(fire.hazard_codes, ["EN0205", "WF", "nat-cli-wil-wil"])

    def test_the_html_description_never_reaches_the_database(self):
        self.load_sdn()
        for value in HazardEvent.objects.values_list("title", flat=True):
            self.assertNotIn("<div>", value)
        self.assertFalse(
            [f.name for f in HazardEvent._meta.get_fields() if f.name == "description"])

    def test_a_two_country_item_does_not_overwrite_the_first_country(self):
        """The wildfire carries ["ETH", "SDN"]. Loading Ethiopia after Sudan
        must ADD a row, not rewrite Sudan's - iso3 is in the natural key."""
        self.load_sdn()
        SourceSync.objects.create(source="montandon", dataset="hazard_events",
                                  iso3="ETH", variant="")
        load(self.loader, payload("montandon_events_sdn.json"), "ETH",
             context={"iso3": "ETH"})
        fires = HazardEvent.objects.filter(event_id="gdacs-event-1027729")
        self.assertEqual(fires.count(), 2)
        self.assertEqual(set(fires.values_list("iso3", flat=True)), {"ETH", "SDN"})

    def test_only_items_naming_this_country_are_loaded_for_it(self):
        """The flood is SDN-only; an Ethiopia pull must not pick it up."""
        SourceSync.objects.create(source="montandon", dataset="hazard_events",
                                  iso3="ETH", variant="")
        load(self.loader, payload("montandon_events_sdn.json"), "ETH",
             context={"iso3": "ETH"})
        self.assertFalse(
            HazardEvent.objects.filter(event_id="idmc-idu-event-80585",
                                       iso3="ETH").exists())

    def test_loading_twice_is_a_no_op(self):
        self.load_sdn()
        self.load_sdn()
        self.assertEqual(HazardEvent.objects.count(), 3)

    def test_the_watermark_is_the_newest_event_date(self):
        result = self.load_sdn()
        self.assertEqual(result.high_water_date, date(2026, 8, 17))

    def test_an_empty_payload_is_a_failure_not_nothing_new(self):
        with self.assertRaises(EmptyPayload):
            load(self.loader, {"type": "FeatureCollection", "features": []}, "SDN",
                 context={"iso3": "SDN"})


class PointResolutionTests(TestCase):
    """A point is placed by PostGIS, after insert, at the deepest level.

    parse() is documented as pure, so the ST_Contains pass cannot live there;
    it is an after_insert hook, the same shape as _write_geometry.
    """

    def setUp(self):
        self.loader = LOADERS["montandon_events"]()
        SourceSync.objects.create(source="montandon", dataset="hazard_events",
                                  iso3="SDN", variant="")
        source = BoundarySource.objects.create(path="test/fixture.shp")
        # A state and a locality inside it, both containing the Tawila point.
        # The locality must win: "finest first, most precise wins".
        state = AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN",
            country_name="Sudan", level=1, pcode="SD-TEST-1", name="North Darfur",
            name_alt=[])
        locality = AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN",
            country_name="Sudan", level=2, pcode="SD-TEST-2", name="Tawila",
            name_alt=[])
        with connection.cursor() as cur:
            for pk, box in ((state.pk, "24.0 12.8, 26.0 12.8, 26.0 14.5, 24.0 14.5, 24.0 12.8"),
                            (locality.pk, "24.5 13.2, 25.2 13.2, 25.2 13.8, 24.5 13.8, 24.5 13.2")):
                cur.execute(
                    "UPDATE admin_areas SET geom = ST_GeomFromText(%s, 4326) WHERE id = %s",
                    [f"POLYGON(({box}))", pk])

    def test_a_point_inside_a_polygon_resolves_to_the_deepest_one(self):
        load(self.loader, payload("montandon_events_sdn.json"), "SDN",
             context={"iso3": "SDN"})
        flood = HazardEvent.objects.get(event_id="idmc-idu-event-80585")
        self.assertEqual(flood.admin_pcode, "SD-TEST-2")
        self.assertEqual(flood.admin_level, 2)
        self.assertEqual(flood.match_method, "point-in-polygon")

    def test_a_point_in_open_desert_stays_unmatched_and_draws_nothing(self):
        load(self.loader, payload("montandon_events_sdn.json"), "SDN",
             context={"iso3": "SDN"})
        fire = HazardEvent.objects.get(event_id="gdacs-event-1027729")
        self.assertIsNone(fire.admin_pcode)
        self.assertEqual(fire.match_method, "unmatched")


class SeverityAndImpactTests(TestCase):
    """Severity is applied onto events by corr_id and creates no rows of its own.

    A hazard item has its own STAC id and is not an event. Upserting them into
    hazard_events would double every row that has a severity.
    """

    def setUp(self):
        SourceSync.objects.create(source="montandon", dataset="hazard_events",
                                  iso3="SDN", variant="")
        load(LOADERS["montandon_events"](), payload("montandon_events_sdn.json"),
             "SDN", context={"iso3": "SDN"})

    def load_severity(self):
        return load(LOADERS["montandon_severity"](),
                    payload("montandon_hazards_sdn.json"), "SDN",
                    context={"iso3": "SDN"})

    def load_impacts(self):
        return load(LOADERS["montandon_impacts"](),
                    payload("montandon_impacts_sdn.json"), "SDN",
                    context={"iso3": "SDN"})

    def test_severity_creates_no_new_event_rows(self):
        before = HazardEvent.objects.count()
        self.load_severity()
        self.assertEqual(HazardEvent.objects.count(), before)

    def test_severity_lands_on_the_event_with_its_unit_and_label(self):
        self.load_severity()
        fire = HazardEvent.objects.get(event_id="gdacs-event-1027729", iso3="SDN")
        self.assertEqual(fire.severity_value, 0.5)
        self.assertEqual(fire.severity_unit, "GDACS Severity Score")
        self.assertEqual(fire.severity_label, "Green")

    def test_a_severity_whose_event_never_loaded_is_ignored(self):
        self.load_severity()
        self.assertFalse(
            HazardEvent.objects.filter(corr_id="20260101-SDN-NOSUCH-1-GCDB").exists())

    def test_severity_does_not_move_the_event_row_count(self):
        """counts_rows is False on this loader: the freshness table must keep
        reporting how many EVENTS are held."""
        result = self.load_severity()
        self.assertEqual(result.sync.row_count, 3)

    def test_impacts_are_written_and_joined_by_corr_id(self):
        self.load_impacts()
        flood = HazardImpact.objects.get(impact_type="displaced_internal")
        self.assertEqual(flood.value, 813)
        self.assertEqual(flood.category, "people")
        self.assertEqual(flood.corr_id, "20260817-SDN-900001-MH0600-1-GCDB")

    def test_impacts_do_not_move_the_event_row_count_either(self):
        result = self.load_impacts()
        self.assertEqual(result.sync.row_count, 3)

    def test_a_green_gdacs_fire_affecting_nobody_becomes_a_detection(self):
        """385 of the first 500 region-wide events are these. Everything is
        stored, but a detection draws only under its own sub-hazard."""
        self.load_severity()
        self.load_impacts()
        fire = HazardEvent.objects.get(event_id="gdacs-event-1027729", iso3="SDN")
        self.assertEqual(fire.significance, "detection")

    def test_a_flood_that_displaced_people_stays_an_event(self):
        self.load_severity()
        self.load_impacts()
        flood = HazardEvent.objects.get(event_id="idmc-idu-event-80585")
        self.assertEqual(flood.significance, "event")

    def test_an_idmc_event_with_no_severity_at_all_stays_an_event(self):
        """There is no idmc-idu-hazards collection, so these are always null -
        which must never be read as 'no alert'."""
        self.load_severity()
        self.load_impacts()
        flood = HazardEvent.objects.get(event_id="idmc-idu-event-80585")
        self.assertIsNone(flood.severity_label)
        self.assertEqual(flood.significance, "event")

    def test_an_empty_severity_payload_is_still_a_failure(self):
        with self.assertRaises(EmptyPayload):
            load(LOADERS["montandon_severity"](),
                 {"type": "FeatureCollection", "features": []}, "SDN",
                 context={"iso3": "SDN"})
