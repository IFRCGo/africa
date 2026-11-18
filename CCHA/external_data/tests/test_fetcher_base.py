"""The fetcher contract: registry keys, key checks, redaction, saving.

No test here touches the network. `http_get_json` is exercised with requests.get
patched, because the thing being tested is our handling, not theirs.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import FETCHERS, base, register
from external_data.fetchers.base import (Call, FetchError, Fetcher, fetcher_for,
                                         http_get_json, missing_keys, redact,
                                         save_payload)


class _Fake(Fetcher):
    source = "testsource"
    dataset = "testdataset"
    variant = "testvariant"
    tool = "get_test"
    requires = ("IPC_API_KEY",)

    def plan(self, sync):
        yield Call(url="https://example.org/x", params={"a": 1},
                   cache_path=Path("test/x.json"), loader_dataset="testdataset",
                   context={})


class RegistryTests(TestCase):
    def test_register_keys_on_source_dataset_and_variant(self):
        """Variant is in the key: fewsnet/food_security/'fewsnet-phases' is a
        different pull from anything keyed on source and dataset alone."""
        register(_Fake)
        self.addCleanup(FETCHERS.pop, ("testsource", "testdataset", "testvariant"), None)
        self.assertIs(fetcher_for("testsource", "testdataset", "testvariant"), _Fake)

    def test_an_unregistered_row_resolves_to_none(self):
        self.assertIsNone(fetcher_for("excel", "idps", "sudan-idps-workbook"))


class KeyCheckTests(TestCase):
    @override_settings(IPC_API_KEY="")
    def test_a_missing_key_is_reported_by_name(self):
        self.assertEqual(missing_keys(_Fake), ["IPC_API_KEY"])

    @override_settings(IPC_API_KEY="abc123")
    def test_a_present_key_leaves_nothing_missing(self):
        self.assertEqual(missing_keys(_Fake), [])


@override_settings(IPC_API_KEY="SUPERSECRET", HDX_API_TOKEN="TOKENVALUE")
class RedactionTests(TestCase):
    def test_key_values_are_removed_from_text(self):
        """HAPI carries its token in the query string, so it lands in exception
        text. Anything written to a job log goes through here first."""
        text = "GET https://hapi.humdata.org/x?app_identifier=TOKENVALUE failed"
        self.assertNotIn("TOKENVALUE", redact(text))
        self.assertIn("<redacted>", redact(text))

    def test_both_keys_are_covered(self):
        self.assertNotIn("SUPERSECRET", redact("key=SUPERSECRET"))

    def test_an_empty_key_does_not_redact_everything(self):
        """A blank key must not turn every character into <redacted>."""
        with override_settings(IPC_API_KEY="", HDX_API_TOKEN=""):
            self.assertEqual(redact("hello"), "hello")


class HttpTests(TestCase):
    def test_json_is_returned_on_success(self):
        with patch("external_data.fetchers.base.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"ok": True}
            get.return_value.raise_for_status.return_value = None
            self.assertEqual(http_get_json("https://example.org", {"a": 1}), {"ok": True})

    def test_an_http_error_becomes_a_fetcherror_with_the_key_redacted(self):
        import requests
        with override_settings(HDX_API_TOKEN="TOKENVALUE"), \
             patch("external_data.fetchers.base.requests.get") as get:
            get.side_effect = requests.RequestException("boom app_identifier=TOKENVALUE")
            with self.assertRaises(FetchError) as caught:
                http_get_json("https://example.org", {})
        self.assertNotIn("TOKENVALUE", str(caught.exception))


class SaveTests(TestCase):
    def test_payload_is_written_under_the_cache_dir_and_parents_created(self):
        path = save_payload(Path("testsource/deep/x.json"), {"hello": "world"})
        self.addCleanup(path.unlink, True)
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"hello": "world"})

    def test_the_path_is_relative_to_api_cache_dir(self):
        from django.conf import settings
        path = save_payload(Path("testsource/y.json"), [])
        self.addCleanup(path.unlink, True)
        self.assertEqual(path.parent.parent, Path(settings.API_CACHE_DIR))


class PostAndTokenPaginationTests(TestCase):
    """STAC pages by a token inside links[rel=next].body, not by an offset.

    A fetcher that takes the first page of a Sudan pull writes 500 events over
    the top of however many there really are and reports a successful refresh -
    the same fault fetch_all_pages exists to prevent for HAPI.
    """

    def test_post_sends_the_body_as_json_and_returns_the_decoded_reply(self):
        with patch("external_data.fetchers.base.requests.post") as post:
            post.return_value.json.return_value = {"type": "FeatureCollection",
                                                   "features": []}
            post.return_value.raise_for_status.return_value = None
            out = base.http_post_json("https://example.test/search",
                                      {"limit": 5}, headers={"Authorization": "x"})
        self.assertEqual(out["type"], "FeatureCollection")
        self.assertEqual(post.call_args.kwargs["json"], {"limit": 5})
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "x")

    def test_a_post_failure_is_a_fetcherror_with_the_token_removed(self):
        import requests as _requests
        with override_settings(IFRC_API_TOKEN="SECRETVALUE"),              patch("external_data.fetchers.base.requests.post") as post:
            post.side_effect = _requests.RequestException("boom Bearer SECRETVALUE")
            with self.assertRaises(FetchError) as caught:
                base.http_post_json("https://example.test/search", {})
        self.assertNotIn("SECRETVALUE", str(caught.exception))

    def test_token_pagination_follows_next_to_the_end_and_combines(self):
        page1 = {"type": "FeatureCollection",
                 "features": [{"id": "a"}, {"id": "b"}],
                 "links": [{"rel": "next", "method": "POST",
                            "body": {"limit": 2, "token": "next:x"}}]}
        page2 = {"type": "FeatureCollection", "features": [{"id": "c"}], "links": []}
        with patch("external_data.fetchers.base.http_post_json",
                   side_effect=[page1, page2]) as post:
            out = base.fetch_all_pages_token("https://example.test/search",
                                             {"limit": 2})
        self.assertEqual([f["id"] for f in out["features"]], ["a", "b", "c"])
        self.assertEqual(post.call_count, 2)
        # The second call is the next link's body, verbatim - the token is the
        # server's cursor, not ours to construct.
        self.assertEqual(post.call_args_list[1].args[1], {"limit": 2, "token": "next:x"})

    def test_a_page_with_no_next_link_stops(self):
        only = {"type": "FeatureCollection", "features": [{"id": "a"}], "links": []}
        with patch("external_data.fetchers.base.http_post_json",
                   side_effect=[only]) as post:
            out = base.fetch_all_pages_token("https://example.test/search", {})
        self.assertEqual(len(out["features"]), 1)
        self.assertEqual(post.call_count, 1)

    def test_fetch_dispatches_get_and_post(self):
        get_call = Call(url="https://example.test/a", params={"x": 1},
                        cache_path=Path("a.json"), loader_dataset="d")
        post_call = Call(url="https://example.test/b", params={},
                         cache_path=Path("b.json"), loader_dataset="d",
                         method="POST", body={"limit": 1})
        with patch("external_data.fetchers.base.http_get_json",
                   return_value={"got": True}) as g,              patch("external_data.fetchers.base.http_post_json",
                   return_value={"posted": True}) as p:
            self.assertEqual(base.fetch(get_call), {"got": True})
            self.assertEqual(base.fetch(post_call), {"posted": True})
        g.assert_called_once()
        p.assert_called_once()

    def test_a_paginated_post_call_goes_through_the_token_paginator(self):
        call = Call(url="https://example.test/search", params={},
                    cache_path=Path("c.json"), loader_dataset="d",
                    method="POST", body={"limit": 1}, paginated=True)
        with patch("external_data.fetchers.base.fetch_all_pages_token",
                   return_value={"features": []}) as paged:
            base.fetch(call)
        paged.assert_called_once()


class CrisisFloorTests(TestCase):
    @override_settings(CRISIS_START="2023-04-15")
    def test_the_window_floor_is_the_day_fighting_broke_out(self):
        self.assertEqual(base.crisis_floor(), date(2023, 4, 15))
