"""Ask for what is new, not for everything - and know the difference between
"nothing changed" and "the API broke".

The watermark already records the newest DATA date held. Narrowing a request to
that date, less a lookback, is what turns a refresh from a full re-download into
an update. The lookback is not decoration: agencies restate recent months, and a
strict "everything after what I hold" would never see a correction.
"""
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import LOOKBACK_DAYS, Fetcher
from external_data.models import SeasonalCalendar, SourceSync
from api_calls.models import PullJob


class SinceTests(TestCase):
    def test_no_watermark_means_no_narrowing(self):
        """A source never pulled must ask for everything, or the first pull
        silently fetches a slice and calls the table complete."""
        sync = SourceSync.objects.create(source="x", dataset="y", high_water_date=None)
        self.assertIsNone(Fetcher().since(sync))

    def test_a_watermark_is_walked_back_by_the_lookback(self):
        sync = SourceSync.objects.create(source="x", dataset="y",
                                         high_water_date=date(2026, 6, 1))
        self.assertEqual(Fetcher().since(sync),
                         date(2026, 6, 1) - __import__("datetime").timedelta(days=LOOKBACK_DAYS))

    def test_the_lookback_is_ninety_days(self):
        """Long enough to catch a restated quarter, short enough that a refresh
        is not a re-download of the whole series."""
        self.assertEqual(LOOKBACK_DAYS, 90)


@override_settings(HDX_API_TOKEN="TESTTOKEN")
class NarrowedRequestTests(TestCase):
    def test_hdx_idps_asks_from_the_watermark(self):
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview",
                                         high_water_date=date(2025, 12, 31))
        call = next(iter(fetcher_for("hdx", "idps", "admin2-overview")().plan(sync)))
        self.assertEqual(call.params["start_date"], "2025-10-02")
        self.assertTrue(call.narrowed)

    def test_hdx_refugees_asks_from_the_watermark(self):
        sync = SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="TCD",
                                         high_water_date=date(2025, 7, 1))
        call = next(iter(fetcher_for("unhcr", "refugees", "")().plan(sync)))
        self.assertEqual(call.params["start_date"], "2025-04-02")
        self.assertTrue(call.narrowed)

    def test_a_first_pull_sends_no_start_date_and_is_not_narrowed(self):
        sync = SourceSync.objects.create(source="unhcr", dataset="refugees", iso3="EGY")
        call = next(iter(fetcher_for("unhcr", "refugees", "")().plan(sync)))
        self.assertNotIn("start_date", call.params)
        self.assertFalse(call.narrowed)


class FewsnetNarrowingTests(TestCase):
    def test_phases_never_ask_earlier_than_the_crisis_start(self):
        """The watermark could be older than the crisis if someone backfilled.
        The floor is still the floor."""
        sync = SourceSync.objects.create(source="fewsnet", dataset="food_security",
                                         iso3="ETH", variant="fewsnet-phases",
                                         high_water_date=date(2023, 4, 20))
        call = next(iter(fetcher_for("fewsnet", "food_security", "fewsnet-phases")().plan(sync)))
        self.assertEqual(call.params["start_date"], "2023-04-15")

    def test_phases_ask_from_the_watermark_when_it_is_later(self):
        sync = SourceSync.objects.create(source="fewsnet", dataset="food_security",
                                         iso3="ETH", variant="fewsnet-phases",
                                         high_water_date=date(2026, 6, 1))
        call = next(iter(fetcher_for("fewsnet", "food_security", "fewsnet-phases")().plan(sync)))
        self.assertEqual(call.params["start_date"], "2026-03-03")

    def test_seasons_are_never_narrowed(self):
        """A seasonal calendar has no date to filter on - it is six bands, and a
        full pull of it is cheaper than the code to avoid one."""
        sync = SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                         iso3="TCD", high_water_date=date(2026, 6, 1))
        call = next(iter(fetcher_for("fewsnet", "seasonal_calendar", "")().plan(sync)))
        self.assertNotIn("start_date", call.params)
        self.assertFalse(call.narrowed)


class UpToDateTests(TestCase):
    """The rule that had to split once requests became narrowed.

    "Loud on empty" exists so an API error serialised as [] can never be
    recorded as a successful, up-to-date pull. But an empty answer to "anything
    since June?" is the normal result of nothing having changed. So emptiness
    means different things depending on whether we narrowed the question, and
    only the unnarrowed case is still a failure.
    """

    def _run(self, job):
        call_command("refresh_external", "fewsnet", "seasonal_calendar",
                     "--iso3", "TCD", "--job", str(job.id))

    def test_an_empty_answer_to_an_unnarrowed_request_still_fails(self):
        SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                  iso3="TCD", variant="")
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD")
        with patch("external_data.fetchers.base.http_get_json", return_value=[]):
            with self.assertRaises(CommandError):
                self._run(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")

    def test_an_empty_answer_to_a_narrowed_request_is_success(self):
        """Nothing changed is not a fault, and must not be reported as one -
        otherwise every up-to-date source shows a red banner."""
        sync = SourceSync.objects.create(source="hdx", dataset="idps", iso3="SDN",
                                         variant="admin2-overview",
                                         high_water_date=date(2025, 12, 31))
        job = PullJob.objects.create(kind="pull", source="hdx", dataset="idps",
                                     iso3="SDN", variant="admin2-overview")
        with override_settings(HDX_API_TOKEN="T"), \
             patch("external_data.fetchers.hdx.http_get_json", return_value={"data": []}):
            call_command("refresh_external", "hdx", "idps", "--iso3", "SDN",
                         "--variant", "admin2-overview", "--job", str(job.id))
        job.refresh_from_db()
        sync.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.rows_written, 0)
        self.assertIn("up to date", job.message)
        # And nothing pretended to be fresher than it is.
        self.assertEqual(sync.high_water_date, date(2025, 12, 31))


class ProgressTests(TestCase):
    def test_a_pull_records_how_many_calls_it_has_made(self):
        import json
        from pathlib import Path
        payload = json.loads(
            (Path(__file__).parent / "fixtures" / "fewsnet_seasons_TCD.json")
            .read_text(encoding="utf-8"))
        SourceSync.objects.create(source="fewsnet", dataset="seasonal_calendar",
                                  iso3="TCD", variant="")
        job = PullJob.objects.create(kind="pull", source="fewsnet",
                                     dataset="seasonal_calendar", iso3="TCD")
        with patch("external_data.fetchers.base.http_get_json", return_value=payload):
            call_command("refresh_external", "fewsnet", "seasonal_calendar",
                         "--iso3", "TCD", "--job", str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.progress_total, 1)
        self.assertEqual(job.progress_done, 1)
        self.assertEqual(SeasonalCalendar.objects.count(), 6)
