"""The runner: fetch, save, load, record - and what it must not do on failure.

The HTTP layer is patched at external_data.fetchers.base.http_get_json, which is
the single door every fetcher goes through. Nothing here touches the network.
"""
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from external_data.models import SeasonalCalendar, SourceSync
from mcp.models import PullJob

FIXTURES = Path(__file__).parent / "fixtures"


def _seasons_payload():
    return json.loads((FIXTURES / "fewsnet_seasons_TCD.json").read_text(encoding="utf-8"))


class SuccessTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")

    def test_a_successful_pull_writes_rows_and_advances_the_watermark(self):
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
        self.sync.refresh_from_db()
        self.assertIsNotNone(self.sync.last_pulled_at)

    def test_the_raw_payload_is_saved_before_it_is_loaded(self):
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        saved = Path(settings.MCP_CACHE_DIR) / "fewsnet_seasons" / "TCD.json"
        self.addCleanup(saved.unlink, True)
        self.assertTrue(saved.is_file())

    def test_the_job_records_the_row_count_and_finishes(self):
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar",
                         "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.rows_written, 6)
        self.assertIsNotNone(job.finished_at)

    def test_params_are_written_back_onto_the_row(self):
        """source_sync.params is empty on every row today. After a pull it says
        what was asked, which is what its help text has always promised."""
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar", "--iso3", "TCD")
        self.sync.refresh_from_db()
        self.assertEqual(self.sync.params["tool"], "get_seasons")


class FailureTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="fewsnet", dataset="seasonal_calendar", iso3="TCD", variant="")

    def test_an_empty_payload_fails_the_job_and_leaves_the_watermark_alone(self):
        """THE REGRESSION THIS DESIGN TURNS ON. An MCP or API error serialised as
        [] must never be recorded as a successful, up-to-date pull."""
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json", return_value=[]):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.sync.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNone(self.sync.last_pulled_at)
        self.assertEqual(self.sync.row_count, 0)

    def test_an_http_failure_is_recorded_on_the_job(self):
        from external_data.fetchers.base import FetchError
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with patch("external_data.fetchers.base.http_get_json",
                   side_effect=FetchError("503 Service Unavailable")):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("503", job.message)

    def test_a_secret_never_reaches_the_job_message(self):
        """HAPI puts its token in the query string, so it lands in exception text.
        Without this test, "never echoed into a log" is a wish."""
        from external_data.fetchers.base import FetchError, redact
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD",
                                     status="queued")
        with override_settings(HDX_API_TOKEN="TOKENVALUE"), \
             patch("external_data.fetchers.base.http_get_json",
                   side_effect=FetchError(redact("failed app_identifier=TOKENVALUE"))):
            with self.assertRaises(CommandError):
                call_command("refresh_external", "fewsnet", "seasonal_calendar",
                             "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertNotIn("TOKENVALUE", job.message)

    def test_a_row_with_no_fetcher_is_refused_by_name(self):
        SourceSync.objects.create(source="excel", dataset="idps", iso3="SDN",
                                  variant="sudan-idps-workbook")
        with self.assertRaises(CommandError) as caught:
            call_command("refresh_external", "excel", "idps", "--iso3", "SDN",
                         "--variant", "sudan-idps-workbook")
        self.assertIn("no fetcher", str(caught.exception).lower())

    def test_a_missing_key_is_refused_before_anything_is_called(self):
        """The command's own key check, tested on a fetcher of its own rather
        than on IPC's: what is under test is the refusal, not the source."""
        from external_data.fetchers import FETCHERS, register
        from external_data.fetchers.base import Call, Fetcher

        class _Keyed(Fetcher):
            source = "keyedsource"
            dataset = "keyeddataset"
            variant = ""
            tool = "get_keyed"
            requires = ("IPC_API_KEY",)

            def plan(self, sync):
                yield Call(url="https://example.org/x", params={},
                           cache_path=Path("x.json"),
                           loader_dataset="seasonal_calendar")

        register(_Keyed)
        self.addCleanup(FETCHERS.pop, ("keyedsource", "keyeddataset", ""), None)
        SourceSync.objects.create(source="keyedsource", dataset="keyeddataset",
                                  iso3="SDN")

        with override_settings(IPC_API_KEY=""), \
             patch("external_data.fetchers.base.http_get_json") as http:
            with self.assertRaises(CommandError) as caught:
                call_command("refresh_external", "keyedsource", "keyeddataset",
                             "--iso3", "SDN")
        http.assert_not_called()
        self.assertIn("IPC_API_KEY", str(caught.exception))


class DryRunTests(TestCase):
    def test_dry_run_writes_no_rows(self):
        SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                  iso3="TCD", variant="")
        with patch("external_data.fetchers.base.http_get_json",
                   return_value=_seasons_payload()):
            call_command("refresh_external", "fewsnet", "seasonal_calendar",
                         "--iso3", "TCD", "--dry-run")
        self.assertEqual(SeasonalCalendar.objects.count(), 0)


def _montandon_payload(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class MontandonEndToEndTests(TestCase):
    """One press: three calls, three payloads saved, rows in two tables.

    The three Calls are consumed by the runner's plain serial for-loop, which is
    what makes the order safe - severity applies onto events that must already
    exist, and significance needs impacts to have landed after that.
    """

    @override_settings(IFRC_API_TOKEN="TESTTOKEN")
    def test_refresh_external_montandon_loads_events_severity_and_impacts(self):
        from external_data.models import HazardEvent, HazardImpact
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        pages = [_montandon_payload("montandon_events_sdn.json"),
                 _montandon_payload("montandon_hazards_sdn.json"),
                 _montandon_payload("montandon_impacts_sdn.json")]
        with patch("external_data.fetchers.base.http_post_json", side_effect=pages) as post:
            call_command("refresh_external", "montandon", "hazard_events",
                         "--iso3", "SDN")

        self.assertEqual(post.call_count, 3)
        self.assertEqual(HazardEvent.objects.count(), 3)
        self.assertEqual(HazardImpact.objects.count(), 2)
        self.assertEqual(
            HazardEvent.objects.get(event_id="gdacs-event-1027729").severity_label,
            "Green")
        self.assertEqual(
            HazardEvent.objects.get(event_id="gdacs-event-1027729").significance,
            "detection")

    @override_settings(IFRC_API_TOKEN="TESTTOKEN")
    def test_the_three_raw_payloads_are_saved_before_they_are_loaded(self):
        """Saved before parsed, on purpose: a payload that breaks a loader is
        then still on disk to look at."""
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        pages = [_montandon_payload("montandon_events_sdn.json"),
                 _montandon_payload("montandon_hazards_sdn.json"),
                 _montandon_payload("montandon_impacts_sdn.json")]
        with patch("external_data.fetchers.base.http_post_json", side_effect=pages):
            call_command("refresh_external", "montandon", "hazard_events",
                         "--iso3", "SDN")
        cache = Path(settings.MCP_CACHE_DIR) / "montandon"
        for kind in ("events", "hazards", "impacts"):
            path = cache / f"SDN-{kind}.json"
            self.addCleanup(path.unlink, True)
            self.assertTrue(path.is_file(), path)

    @override_settings(IFRC_API_TOKEN="")
    def test_without_the_token_the_command_refuses_before_calling_anything(self):
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        with patch("external_data.fetchers.base.http_post_json") as post:
            with self.assertRaises(CommandError):
                call_command("refresh_external", "montandon", "hazard_events",
                             "--iso3", "SDN")
        post.assert_not_called()
