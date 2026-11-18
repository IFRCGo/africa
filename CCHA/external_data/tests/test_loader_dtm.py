"""IOM DTM displacement snapshots: the matrix table, then the loader."""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from external_data.models import DisplacementBreakdown


class BreakdownModelTests(TestCase):
    def row(self, **over):
        base = dict(date=date(2026, 7, 28), iso3="SDN", metric="returnees",
                    dest_pcode="SD09045", dest_level=2, dimension="displaced_in",
                    key="SD03", value=29890, source="dtm",
                    source_dataset="iom-dtm-snapshot")
        return DisplacementBreakdown(**{**base, **over})

    def test_a_cell_can_be_written(self):
        self.row().save()
        self.assertEqual(DisplacementBreakdown.objects.count(), 1)

    def test_the_same_cell_twice_collides(self):
        self.row().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.row(value=1).save()

    def test_two_origins_for_one_place_and_date_coexist(self):
        self.row().save()
        self.row(key="SD15", value=10485).save()
        self.assertEqual(DisplacementBreakdown.objects.count(), 2)

    def test_outside_sudan_is_a_key_like_any_other(self):
        """It is never null, which is why this table needs no nulls_distinct."""
        self.row().save()
        self.row(key="OUTSIDE_SDN", value=17270).save()
        self.assertEqual(
            DisplacementBreakdown.objects.get(key="OUTSIDE_SDN").value, 17270)

    def test_idps_and_returnees_at_one_place_do_not_collide(self):
        """Both metrics describe the same locality on the same date."""
        self.row().save()
        self.row(metric="idps", dimension="origin").save()
        self.assertEqual(DisplacementBreakdown.objects.count(), 2)

    def test_households_is_a_dimension_not_a_second_movement_pattern(self):
        """MovementPattern's key has no `unit`, so an individuals row and a
        households row for one place and date would overwrite each other."""
        self.row(dimension="households", key="total", value=12165).save()
        self.assertEqual(
            DisplacementBreakdown.objects.get(dimension="households").value, 12165)


from external_data.loaders import LOADERS
from external_data.loaders.base import load
from external_data.loaders.dtm_snapshot import parse_sheet_date
from external_data.models import MovementPattern, SourceSync

# The 18 states, exactly as DTM's headers spell them. Used to build fixtures;
# the loader NEVER hardcodes these - it harvests them from the admin1 sheets.
STATES = ["Aj Jazirah", "Blue Nile", "Central Darfur", "East Darfur", "Gedaref",
          "Kassala", "Khartoum", "North Darfur", "North Kordofan", "Northern",
          "Red Sea", "River Nile", "Sennar", "South Darfur", "South Kordofan",
          "West Darfur", "West Kordofan", "White Nile"]
CODES = ["SD15", "SD08", "SD06", "SD05", "SD12", "SD11", "SD01", "SD02", "SD13",
         "SD17", "SD10", "SD16", "SD14", "SD03", "SD07", "SD04", "SD18", "SD09"]


def idp_admin1(title="DTM SUDAN: IDP Master List 30-Jul-2026", rows=None):
    """The admin1 IDP sheet. This is the sheet that carries name->pcode."""
    head = ["STATE OF DISPLACEMET", "STATE CODE", "IDPs", "HHs"] + STATES + \
           ["SUDANESE", "NON SUDANESE"]
    hxl = ["#adm1+name", "#adm1+pcode", "#affected+idps+ind", "#affected+idps+hh"] + \
          [None] * (len(STATES) + 2)
    if rows is None:
        # ALL EIGHTEEN STATES, because the real sheet has all eighteen and this
        # sheet is where the loader harvests name->pcode from. A fixture with
        # one row would leave 'Aj Jazirah' and 'Sennar' unresolvable, and the
        # loader would correctly refuse to treat their columns as origins.
        rows = []
        for state, code in zip(STATES, CODES):
            if state == "Khartoum":
                # 100 IDPs, 60 from Aj Jazirah and 40 from Sennar, all Sudanese.
                origins = [0] * len(STATES)
                origins[STATES.index("Aj Jazirah")] = 60
                origins[STATES.index("Sennar")] = 40
                rows.append([state, code, 100, 20] + origins + [100, 0])
            else:
                rows.append([state, code, 0, 0] + [0] * len(STATES) + [0, 0])
    # Row 0 is the title; rows 1-2 are the banner rows DTM leaves blank.
    return [[title], [], [], head, hxl] + rows


def ret_admin2(title="DTM SUDAN: Return Master List  28-Jul-2026", rows=None):
    head = ["State of Return", "State Code", "Locality Of Return", "Locality Code",
            "INDs", "HHs"] + STATES + ["Returned from outside Sudan", "Total"]
    hxl = ["#adm1+name", "#adm1+pcode", "#adm2+name", "#adm2+pcode",
           "#affected+rets+ind", "#affected+rets+hh"] + [None] * (len(STATES) + 2)
    if rows is None:
        # Um Rimta, snapshot 008, TRANSCRIBED VERBATIM from the published
        # workbook: 60,680 returned, of whom 17,270 from outside Sudan. The
        # seven origin cells plus the outside cell sum to the total exactly,
        # as all 648 returnee rows in the real files do - which is what makes
        # this fixture able to prove the invariant rather than just satisfy it.
        d = [0] * len(STATES)
        for state, n in [("White Nile", 29890), ("Aj Jazirah", 10485),
                         ("Northern", 2210), ("River Nile", 595),
                         ("Red Sea", 150), ("North Kordofan", 50),
                         ("Kassala", 30)]:
            d[STATES.index(state)] = n
        rows = [["White Nile", "SD09", "Um Rimta", "SD09045", 60680, 12165]
                + d + [17270, 60680]]
    return [[title], [], head, hxl] + rows


def payload(**sheets):
    """A transcriber-shaped payload. Defaults to one admin1 IDP + one admin2 returnee."""
    if not sheets:
        sheets = {"IDPs Masterlist (ADMIN1)": idp_admin1(),
                  "Returnees Masterlist (ADMIN2)": ret_admin2()}
    return {"source_url": "https://example.org/snap.xlsx",
            "fetched_at": "2026-09-25T00:00:00Z", "sha1": "0" * 40,
            "sheets": sheets}


CONTEXT = {"resource_id": "res-008", "resource_url": "https://example.org/snap.xlsx"}


class LoaderRegistrationTests(TestCase):
    def test_registered_under_its_dataset(self):
        self.assertIn("displacement_snapshot", LOADERS)

    def test_its_source_is_dtm_not_hdx(self):
        """§6 of the spec: sharing `hdx` would inflate the existing IDP bubbles."""
        self.assertEqual(LOADERS["displacement_snapshot"].source, "dtm")


class ParseTests(TestCase):
    def parse(self, p=None, iso3="SDN"):
        return LOADERS["displacement_snapshot"]().parse(p or payload(), iso3, CONTEXT)

    def test_one_row_per_locality_per_sheet(self):
        # 18 states on the admin1 IDP sheet + 1 locality on the admin2 returnee sheet.
        self.assertEqual(len(self.parse()), 19)

    def test_the_returnee_total_lands_as_a_movement_pattern_field(self):
        row = next(r for r in self.parse() if r["metric"] == "returnees")
        self.assertEqual(row["value"], 60680)
        self.assertEqual(row["admin_pcode"], "SD09045")
        self.assertEqual(row["place_name"], "Um Rimta")
        self.assertEqual(row["admin_level"], 2)
        self.assertEqual(row["date"], date(2026, 7, 28))
        self.assertEqual(row["source"], "dtm")
        self.assertEqual(row["source_dataset"], "iom-dtm-snapshot")

    def test_origin_states_resolve_to_pcodes_harvested_from_the_sheets(self):
        row = next(r for r in self.parse() if r["metric"] == "returnees")
        cells = {(c["dimension"], c["key"]): c["value"] for c in row["_breakdown"]}
        self.assertEqual(cells[("displaced_in", "SD09")], 29890)   # White Nile
        self.assertEqual(cells[("displaced_in", "SD15")], 10485)   # Aj Jazirah

    def test_the_outside_sudan_column_survives_as_its_sentinel(self):
        """This single column is the reason the feature exists."""
        row = next(r for r in self.parse() if r["metric"] == "returnees")
        cells = {(c["dimension"], c["key"]): c["value"] for c in row["_breakdown"]}
        self.assertEqual(cells[("displaced_in", "OUTSIDE_SDN")], 17270)

    def test_zero_cells_are_dropped(self):
        """185 x 18 would be mostly zeros; only the non-zero cells are rows."""
        row = next(r for r in self.parse() if r["metric"] == "returnees")
        keys = {c["key"] for c in row["_breakdown"] if c["dimension"] == "displaced_in"}
        # Seven origin states carry a number; the other eleven columns are zero.
        self.assertEqual(keys, {"SD09", "SD15", "SD17", "SD16", "SD10", "SD13",
                                "SD11", "OUTSIDE_SDN"})

    def test_households_ride_along_as_a_dimension(self):
        row = next(r for r in self.parse() if r["metric"] == "returnees")
        hh = [c for c in row["_breakdown"] if c["dimension"] == "households"]
        self.assertEqual(hh, [{"dimension": "households", "key": "total",
                               "value": 12165}])

    def test_the_idp_nationality_split_is_its_own_dimension(self):
        row = next(r for r in self.parse() if r["admin_pcode"] == "SD01")
        cells = {(c["dimension"], c["key"]): c["value"] for c in row["_breakdown"]}
        self.assertEqual(cells[("nationality", "SUDANESE")], 100)

    def test_the_read_me_tab_is_skipped_without_being_named(self):
        """It carries no HXL row, so it contributes nothing and names nothing."""
        p = payload(**{"Read Me": [["DISCLAIMER"], ["DTM Sudan is a suite..."]],
                       "IDPs Masterlist (ADMIN1)": idp_admin1(),
                       "Returnees Masterlist (ADMIN2)": ret_admin2()})
        self.assertEqual(len(self.parse(p)), len(self.parse()))

    def test_kind_comes_from_the_tag_not_the_title(self):
        """Snapshot 004's IDP sheets are really titled 'Return Master List'."""
        p = payload(**{"IDPs Masterlist (ADMIN1)":
                       idp_admin1(title="DTM SUDAN: Return Master List  31/3/2026")})
        row = next(r for r in self.parse(p) if r["admin_pcode"] == "SD01")
        self.assertEqual(row["metric"], "idps")
        self.assertEqual(row["date"], date(2026, 3, 31))

    def test_the_two_sheets_keep_their_own_dates(self):
        """Snapshot 005 is IDPs at 28 Apr and returnees at 4 Jun 2026."""
        p = payload(**{
            "IDPs Masterlist (ADMIN1)":
                idp_admin1(title="DTM SUDAN: IDP Master List 28-Apr-2026"),
            "Returnees Masterlist (ADMIN2)":
                ret_admin2(title="DTM SUDAN: Return Master List  4/6/2026")})
        dates = {r["metric"]: r["date"] for r in self.parse(p)}
        self.assertEqual(dates["idps"], date(2026, 4, 28))
        self.assertEqual(dates["returnees"], date(2026, 6, 4))


class DateRuleTests(TestCase):
    def test_both_published_formats_parse(self):
        self.assertEqual(parse_sheet_date("DTM SUDAN: IDP Master List 30-Jul-2026"),
                         date(2026, 7, 30))
        self.assertEqual(parse_sheet_date("DTM SUDAN: Return Master List  31/3/2026"),
                         date(2026, 3, 31))

    def test_an_unparseable_date_raises_rather_than_defaulting(self):
        """REVIEW FOCUS 1. A row misdated by a fallback is indistinguishable
        from real data once it is in the table."""
        with self.assertRaises(ValueError) as caught:
            parse_sheet_date("DTM SUDAN: IDP Master List Q3 2026")
        self.assertIn("no parseable date", str(caught.exception))

    def test_an_empty_title_raises(self):
        with self.assertRaises(ValueError):
            parse_sheet_date("")

    def test_the_filename_is_never_consulted(self):
        """No fallback: snapshot 006's filename `2026_24_05_` is ambiguous."""
        with self.assertRaises(ValueError):
            parse_sheet_date("dtm_sdn_snapshot_006_public.xlsx")


class GuardTests(TestCase):
    def parse(self, p):
        return LOADERS["displacement_snapshot"]().parse(p, "SDN", CONTEXT)

    def test_a_workbook_with_no_state_codes_raises(self):
        """REVIEW FOCUS 2. Without the name->pcode pairs every breakdown column
        is unrecognised, and the totals would load with an empty matrix."""
        rows = ret_admin2()
        # Blank the adm1 code column on the HXL row, so no sheet offers pairs.
        rows[3][1] = None
        with self.assertRaises(ValueError) as caught:
            self.parse(payload(**{"Returnees Masterlist (ADMIN2)": rows}))
        self.assertIn("name->pcode", str(caught.exception))

    def test_a_non_numeric_cell_raises_naming_the_column(self):
        """REVIEW FOCUS 4. Coercing 'n/a' to 0 would surface as a
        reconciliation failure pointing at a different column."""
        d = [0] * len(STATES)
        d[STATES.index("White Nile")] = "n/a"
        rows = ret_admin2(rows=[["White Nile", "SD09", "Um Rimta", "SD09045",
                                 60680, 12165] + d + [17270, 60680]])
        with self.assertRaises(ValueError) as caught:
            self.parse(payload(**{"IDPs Masterlist (ADMIN1)": idp_admin1(),
                                  "Returnees Masterlist (ADMIN2)": rows}))
        message = str(caught.exception)
        self.assertIn("White Nile", message)
        self.assertIn("SD09045", message)

    def test_a_broken_returnee_sum_raises(self):
        d = [0] * len(STATES)
        d[STATES.index("White Nile")] = 1        # should be 29890
        rows = ret_admin2(rows=[["White Nile", "SD09", "Um Rimta", "SD09045",
                                 60680, 12165] + d + [17270, 60680]])
        with self.assertRaises(ValueError) as caught:
            self.parse(payload(**{"IDPs Masterlist (ADMIN1)": idp_admin1(),
                                  "Returnees Masterlist (ADMIN2)": rows}))
        self.assertIn("SD09045", str(caught.exception))
        self.assertIn("60,680", str(caught.exception))

    def test_a_broken_nationality_sum_raises(self):
        origins = [0] * len(STATES)
        origins[STATES.index("Aj Jazirah")] = 100
        rows = idp_admin1(rows=[["Khartoum", "SD01", 100, 20] + origins + [90, 0],
                                ["Aj Jazirah", "SD15", 0, 0] + [0] * len(STATES) + [0, 0]])
        with self.assertRaises(ValueError) as caught:
            self.parse(payload(**{"IDPs Masterlist (ADMIN1)": rows}))
        self.assertIn("SUDANESE", str(caught.exception))


class LoadTests(TestCase):
    def setUp(self):
        # Seeded by migration 0018, which runs against the test database too.
        SourceSync.objects.update_or_create(
            source="dtm", dataset="displacement_snapshot", iso3="SDN", variant="")

    def load(self, p=None):
        return load(LOADERS["displacement_snapshot"](), p or payload(), "SDN",
                    context=CONTEXT)

    def test_totals_land_in_movement_patterns_under_source_dtm(self):
        self.load()
        row = MovementPattern.objects.get(source="dtm", metric="returnees")
        self.assertEqual(row.value, 60680)
        self.assertEqual(row.admin_pcode, "SD09045")

    def test_matrix_cells_land_in_the_breakdown_table(self):
        self.load()
        self.assertEqual(
            DisplacementBreakdown.objects.get(dimension="displaced_in",
                                              key="OUTSIDE_SDN").value, 17270)

    def test_loading_twice_changes_no_row_count_in_either_table(self):
        """REVIEW FOCUS 5. after_insert is hand-written, so the breakdown
        table's idempotence is not inherited from load()."""
        self.load()
        movements = MovementPattern.objects.count()
        breakdowns = DisplacementBreakdown.objects.count()
        self.load()
        self.assertEqual(MovementPattern.objects.count(), movements)
        self.assertEqual(DisplacementBreakdown.objects.count(), breakdowns)

    def test_a_revised_figure_overwrites_rather_than_duplicating(self):
        self.load()
        d = [0] * len(STATES)
        for state, n in [("White Nile", 30000), ("Aj Jazirah", 10485),
                         ("Northern", 2210), ("River Nile", 595),
                         ("Red Sea", 150), ("North Kordofan", 50),
                         ("Kassala", 30)]:
            d[STATES.index(state)] = n
        revised = payload(**{
            "IDPs Masterlist (ADMIN1)": idp_admin1(),
            "Returnees Masterlist (ADMIN2)": ret_admin2(
                rows=[["White Nile", "SD09", "Um Rimta", "SD09045", 60790, 12165]
                      + d + [17270, 60790]])})
        self.load(revised)
        self.assertEqual(
            DisplacementBreakdown.objects.get(dimension="displaced_in",
                                              key="SD09").value, 30000)

    def test_the_watermark_records_the_resource_not_a_date_alone(self):
        self.load()
        sync = SourceSync.objects.get(source="dtm", dataset="displacement_snapshot")
        self.assertIn("res-008", sync.known_ids)
        self.assertEqual(sync.high_water_date, date(2026, 7, 30))

    def test_the_existing_hapi_idp_series_is_untouched(self):
        """§6: sharing `source='hdx'` would inflate the dashboard's IDP bubbles."""
        MovementPattern.objects.create(
            date=date(2026, 6, 30), iso3="SDN", admin_pcode="SD09045",
            admin_level=2, place_name="Um Rimta", metric="idps",
            population_group="idps", value=999, unit="individuals",
            source="hdx", source_dataset="iom-dtm")
        self.load()
        self.assertEqual(MovementPattern.objects.filter(source="hdx").count(), 1)
        self.assertEqual(MovementPattern.objects.get(source="hdx").value, 999)

    def test_a_breakdown_failure_rolls_the_totals_back_too(self):
        """One file is one transaction."""
        broken = payload(**{
            "IDPs Masterlist (ADMIN1)": idp_admin1(),
            "Returnees Masterlist (ADMIN2)": ret_admin2(
                rows=[["White Nile", "SD09", "Um Rimta", "SD09045", 60680, 12165]
                      + [0] * len(STATES) + [1, 60680]])})
        with self.assertRaises(ValueError):
            self.load(broken)
        self.assertEqual(MovementPattern.objects.filter(source="dtm").count(), 0)


class StaleCellTests(TestCase):
    """A revised snapshot must not leave the origins it no longer names.

    after_insert only upserts, so a cell whose origin MOVED between two
    publications would survive as a phantom: the popup would list an origin
    DTM has withdrawn, and `from` would sum past the published total.
    """

    def setUp(self):
        SourceSync.objects.update_or_create(
            source="dtm", dataset="displacement_snapshot", iso3="SDN", variant="")

    def load(self, p):
        return load(LOADERS["displacement_snapshot"](), p, "SDN", context=CONTEXT)

    def snapshot(self, moved_to):
        """Um Rimta's 29,890 attributed to `moved_to` instead of White Nile.

        `moved_to` must be a state the row does not otherwise name, or the
        two entries collide and the row stops summing to its own total -
        which the loader correctly refuses, as it did on the first attempt.
        """
        d = [0] * len(STATES)
        for state, n in [(moved_to, 29890), ("Aj Jazirah", 10485),
                         ("Northern", 2210), ("River Nile", 595),
                         ("Red Sea", 150), ("North Kordofan", 50),
                         ("Kassala", 30)]:
            d[STATES.index(state)] = n
        return payload(**{
            "IDPs Masterlist (ADMIN1)": idp_admin1(),
            "Returnees Masterlist (ADMIN2)": ret_admin2(
                rows=[["White Nile", "SD09", "Um Rimta", "SD09045", 60680, 12165]
                      + d + [17270, 60680]])})

    def test_an_origin_the_revision_drops_does_not_survive(self):
        self.load(self.snapshot("White Nile"))          # 29,890 from SD09
        self.load(self.snapshot("Sennar"))              # revised: now SD14
        keys = set(DisplacementBreakdown.objects
                   .filter(dest_pcode="SD09045", dimension="displaced_in")
                   .values_list("key", flat=True))
        self.assertNotIn("SD09", keys)
        self.assertIn("SD14", keys)

    def test_the_breakdown_still_sums_to_the_published_total_after_a_revision(self):
        self.load(self.snapshot("White Nile"))
        self.load(self.snapshot("Sennar"))
        total = sum(DisplacementBreakdown.objects
                    .filter(dest_pcode="SD09045", date=date(2026, 7, 28),
                            dimension="displaced_in")
                    .values_list("value", flat=True))
        self.assertEqual(total, 60680)

    def test_another_date_at_the_same_place_is_untouched(self):
        """The sweep is per (place, date, metric) - not per place."""
        self.load(self.snapshot("White Nile"))
        june = payload(**{
            "IDPs Masterlist (ADMIN1)": idp_admin1(),
            "Returnees Masterlist (ADMIN2)": ret_admin2(
                title="DTM SUDAN: Return Master List  30-Jun-2026",
                rows=[["White Nile", "SD09", "Um Rimta", "SD09045", 100, 20]
                      + [0] * len(STATES) + [100, 100]])})
        self.load(june)
        self.assertTrue(DisplacementBreakdown.objects.filter(
            dest_pcode="SD09045", date=date(2026, 7, 28), key="SD09").exists())


class EmptyWorkbookTests(TestCase):
    """A workbook whose values never got computed must not write zeros over good data.

    The spec claimed data_only=True made this impossible. It does not: openpyxl
    yields None for an uncomputed formula, _number turns None into 0, and a
    sheet of zeros satisfies every invariant (0 == 0) while still producing
    p-code-bearing rows, so EmptyPayload never fires either.
    """

    def test_a_sheet_whose_every_total_is_zero_raises(self):
        rows = ret_admin2(rows=[
            ["White Nile", "SD09", "Um Rimta", "SD09045", None, None]
            + [None] * len(STATES) + [None, None],
            ["White Nile", "SD09", "Rabak", "SD09046", None, None]
            + [None] * len(STATES) + [None, None]])
        with self.assertRaises(ValueError) as caught:
            LOADERS["displacement_snapshot"]().parse(
                payload(**{"IDPs Masterlist (ADMIN1)": idp_admin1(),
                           "Returnees Masterlist (ADMIN2)": rows}), "SDN", CONTEXT)
        self.assertIn("every", str(caught.exception).lower())

    def test_a_sheet_with_one_real_figure_among_zeros_is_fine(self):
        """17 of Sudan's 18 states legitimately report 0 IDPs in the fixture."""
        out = LOADERS["displacement_snapshot"]().parse(payload(), "SDN", CONTEXT)
        self.assertTrue(any(r["value"] for r in out))
