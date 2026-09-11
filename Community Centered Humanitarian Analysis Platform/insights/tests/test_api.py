"""Only published rows leave the building."""
from django.test import TestCase

from insights.models import Insight, InsightCoding
from insights.verify import quote_sha1


def make(quote, **kwargs):
    defaults = dict(
        quote=quote, quote_sha1=quote_sha1(quote), voice_type="community",
        channel="manual", stated_on="2026-03-14", iso3="ETH", method="manual",
        status="published",
    )
    defaults.update(kwargs)
    return Insight.objects.create(**defaults)


class InsightApiTests(TestCase):
    def setUp(self):
        self.published = make("We have cholera and no clinic.", lat=11.75, lon=40.95,
                              admin_pcode="ET02", match_method="name",
                              place_name_as_written="Afar")
        InsightCoding.objects.create(insight=self.published, dimension="hazard",
                                     tag="disease_outbreak")
        make("A pending statement.", status="pending")
        make("An analyst passage.", voice_type="secondary_analysis", iso3="SDN")

    def get(self, query=""):
        return self.client.get(f"/api/insights/{query}").json()

    def test_only_published_rows_are_returned(self):
        body = self.get()
        quotes = [row["quote"] for row in body["results"]]
        self.assertIn("We have cholera and no clinic.", quotes)
        self.assertNotIn("A pending statement.", quotes)

    def test_codings_travel_with_the_row(self):
        row = next(r for r in self.get()["results"] if r["quote"].startswith("We have"))
        self.assertEqual(row["codings"], [{"dimension": "hazard", "tag": "disease_outbreak"}])

    def test_placement_is_reported_honestly(self):
        row = next(r for r in self.get()["results"] if r["quote"].startswith("We have"))
        self.assertEqual(row["match_method"], "name")
        self.assertEqual(row["lat"], 11.75)

    def test_filtering_by_voice_type(self):
        body = self.get("?voice_type=community")
        self.assertTrue(all(r["voice_type"] == "community" for r in body["results"]))

    def test_filtering_by_country(self):
        self.assertEqual(len(self.get("?iso3=SDN")["results"]), 1)

    def test_filtering_by_tag(self):
        self.assertEqual(len(self.get("?tag=disease_outbreak")["results"]), 1)

    def test_free_text_search(self):
        self.assertEqual(len(self.get("?q=cholera")["results"]), 1)

    def test_the_count_reflects_the_filter(self):
        self.assertEqual(self.get("?iso3=SDN")["count"], 1)
