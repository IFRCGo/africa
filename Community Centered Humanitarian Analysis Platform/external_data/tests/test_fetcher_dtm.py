"""IOM DTM snapshots: a CKAN listing, then one workbook per unheld resource.

THE WATERMARK HERE IS `known_ids`, NOT A DATE. DTM publishes each snapshot as a
new resource rather than by editing an old one, and there is no date parameter
to narrow by. The first pull takes all eight; every later pull takes the ones
it has not seen, which is usually none.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync

SNAPSHOT_URL = ("https://data.humdata.org/dataset/44594ae2/resource/{id}/"
                "download/dtm_sdn_idps_returnees_snapshot_{n}_public.xlsx")

PACKAGE = {"result": {"resources": [
    {"id": "res-008", "format": "XLSX", "url": SNAPSHOT_URL.format(id="res-008", n="008"),
     "name": "DTM Sudan Displacement and Return Snapshot (8).xlsx"},
    {"id": "res-007", "format": "XLSX", "url": SNAPSHOT_URL.format(id="res-007", n="007"),
     "name": "DTM Sudan Displacement and Return Snapshot (7).xlsx"},
    # The older family: a different layout, explicitly out of scope.
    {"id": "res-smu", "format": "XLSX",
     "url": "https://data.humdata.org/dataset/44594ae2/resource/res-smu/"
            "download/dtm_sdn_smu-22-_-30092025_v02_public.xlsx",
     "name": "Sudan - Countrywide Mobility Update 22 (Bi-Weekly)"},
    # A PDF sitting in the same dataset.
    {"id": "res-pdf", "format": "PDF",
     "url": "https://data.humdata.org/x/snapshot.pdf", "name": "snapshot.pdf"},
]}}


def sync(known=None):
    """The row migration 0018 already seeded, with known_ids set for this test.

    update_or_create, not create: the seed migration runs against the test
    database too, so the row exists before any test does. This is the same
    pattern test_fetcher_montandon uses against its own seed migration.
    """
    row, _ = SourceSync.objects.update_or_create(
        source="dtm", dataset="displacement_snapshot", iso3="SDN", variant="",
        defaults={"known_ids": known or []})
    return row


def plan(row):
    fetcher = fetcher_for("dtm", "displacement_snapshot", "")()
    with patch("external_data.fetchers.dtm.http_get_json", return_value=PACKAGE):
        return list(fetcher.plan(row))


class RegistrationTests(TestCase):
    def test_registered(self):
        self.assertIsNotNone(fetcher_for("dtm", "displacement_snapshot", ""))

    def test_it_needs_no_key(self):
        """CKAN downloads are open; verified against the live host 2026-09-25."""
        self.assertEqual(
            missing_keys(fetcher_for("dtm", "displacement_snapshot", "")), [])


class PlanTests(TestCase):
    def test_a_first_pull_takes_every_snapshot(self):
        self.assertEqual(len(plan(sync())), 2)

    def test_the_older_mobility_updates_are_never_yielded(self):
        urls = [c.url for c in plan(sync())]
        self.assertFalse(any("smu" in u for u in urls))

    def test_non_xlsx_resources_are_never_yielded(self):
        urls = [c.url for c in plan(sync())]
        self.assertFalse(any(u.endswith(".pdf") for u in urls))

    def test_a_held_resource_is_skipped(self):
        calls = plan(sync(known=["res-008"]))
        self.assertEqual([c.context["resource_id"] for c in calls], ["res-007"])

    def test_nothing_is_yielded_when_everything_is_held(self):
        self.assertEqual(plan(sync(known=["res-008", "res-007"])), [])

    def test_the_call_is_an_xlsx_one_routed_to_the_snapshot_loader(self):
        call = plan(sync(known=["res-007"]))[0]
        self.assertEqual(call.format, "xlsx")
        self.assertEqual(call.loader_dataset, "displacement_snapshot")
        self.assertFalse(call.paginated)
        self.assertEqual(call.cache_path,
                         Path("dtm_snapshots/SDN-res-008.json"))

    def test_the_context_carries_what_the_payload_does_not(self):
        """The workbook does not name the resource it came from."""
        call = plan(sync(known=["res-007"]))[0]
        self.assertEqual(call.context["resource_id"], "res-008")
        self.assertIn("res-008", call.context["resource_url"])

    def test_params_record_states_the_filter(self):
        fetcher = fetcher_for("dtm", "displacement_snapshot", "")()
        record = fetcher.params_record()
        self.assertEqual(record["tool"], "package_show")
        self.assertIn("snapshot", record["resource_filter"])


class EmptyCatalogueTests(TestCase):
    """REVIEW FOCUS 3. 'Nothing new' is only true when something is held."""

    EMPTY = {"result": {"resources": [
        {"id": "res-pdf", "format": "PDF",
         "url": "https://data.humdata.org/x/report.pdf", "name": "report.pdf"}]}}

    def plan(self, row):
        fetcher = fetcher_for("dtm", "displacement_snapshot", "")()
        with patch("external_data.fetchers.dtm.http_get_json", return_value=self.EMPTY):
            return list(fetcher.plan(row))

    def test_a_first_pull_finding_no_snapshots_raises(self):
        with self.assertRaises(ValueError) as caught:
            self.plan(sync())
        self.assertIn("none of them is a snapshot", str(caught.exception))

    def test_a_later_pull_finding_no_snapshots_is_merely_nothing_new(self):
        """Once eight are held, an empty listing is a bad day at HDX and the
        rows we have are still right. It must not fail the job."""
        self.assertEqual(self.plan(sync(known=["res-008"])), [])


from api_calls.views import FILE_SOURCES, refresh_argv


class AdminRowTests(TestCase):
    """No code in api_calls changes. That is the design working: CLAUDE.md
    warns that a second rule for 'which command refreshes this row' is how a
    row starts failing in batch while its own button works."""

    def row(self):
        return SourceSync.objects.get(source="dtm", dataset="displacement_snapshot")

    def test_the_seed_migration_created_the_row(self):
        self.assertEqual(self.row().iso3, "SDN")

    def test_refresh_argv_resolves_it_with_no_new_rule(self):
        self.assertEqual(
            refresh_argv(self.row(), 42),
            ["refresh_external", "dtm", "displacement_snapshot", "--job", "42",
             "--iso3", "SDN"])

    def test_it_is_not_a_file_source_so_the_button_says_pull_now(self):
        """The bytes come over HTTPS, so the API wording on the confirmation
        page is the truthful one."""
        self.assertNotIn("dtm", FILE_SOURCES)


class NothingNewTests(TestCase):
    """A pull that finds nothing new must SAY so, and must still count as an attempt.

    models.SourceSync documents "last_pulled_at moves on every attempt". For an
    id-keyed source every pull after the first yields no Calls at all, so the
    loader - which is the only thing that writes last_pulled_at - never runs.
    Without this the DTM row reads "never pulled" for ever, and rejoins the
    "pull everything out of date" batch on every press.
    """

    def run_pull(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        with patch("external_data.fetchers.dtm.http_get_json", return_value=PACKAGE):
            call_command("refresh_external", "dtm", "displacement_snapshot",
                         "--iso3", "SDN", stdout=out)
        return out.getvalue()

    def test_a_pull_with_nothing_new_says_so(self):
        sync(known=["res-008", "res-007"])
        self.assertIn("already up to date", self.run_pull())

    def test_it_still_counts_as_an_attempt(self):
        row = sync(known=["res-008", "res-007"])
        self.assertIsNone(row.last_pulled_at)
        self.run_pull()
        row.refresh_from_db()
        self.assertIsNotNone(row.last_pulled_at)

    def test_a_row_with_nothing_new_stops_being_stale(self):
        """Otherwise the batch re-pulls it every time, for ever."""
        from api_calls.views import stale_rows
        sync(known=["res-008", "res-007"])
        self.run_pull()
        self.assertNotIn(
            "dtm", [r.source for r in stale_rows()])


class NarrowedFlagTests(TestCase):
    def test_a_call_is_never_marked_narrowed(self):
        """`narrowed` says "an empty answer here means nothing new". That is
        true of a date-filtered request and false of this one: every Call is
        for a resource the catalogue JUST said exists, so an empty parse is a
        fault and must reach EmptyPayload rather than being swallowed."""
        call = plan(sync(known=["res-007"]))[0]
        self.assertFalse(call.narrowed)
