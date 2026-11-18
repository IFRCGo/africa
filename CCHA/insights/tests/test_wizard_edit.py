"""Correcting a statement in the review page is the same form, not a copy of it.

The two rules that matter are InsightPlaceForm's, and they are tested here
because this is a second caller of it: a changed pick re-derives the five
machine columns, and an untouched one leaves them exactly as the extractor
wrote them - including a row below ADM2, which the three dropdowns cannot
express at all.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from boundaries.models import AdminArea, BoundarySource
from insights.models import ExtractionJob, Insight
from insights.verify import quote_sha1

QUOTE = "The pump broke before the rains and no one has come."


class InlineEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("reviewer", "r@example.org", "pw")
        self.client.force_login(self.user)
        # AdminArea.source is a required FK and BoundarySource's only required
        # field is its unique `path` - the same fixture shape test_places.py uses.
        source = BoundarySource.objects.create(path="tests/wizard-fixture")
        self.country = AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, level=0, pcode="TD",
            iso3="TCD", country_name="Chad", name="Chad")
        self.state = AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, level=1, pcode="TD01",
            iso3="TCD", country_name="Chad", name="Ouaddai", parent_pcode="TD",
            center_lat=13.8, center_lon=20.8)
        # The ADM3 the "untouched place" test sits on. It must EXIST: the form
        # reconstructs an insight's original chain by walking parent_pcode up
        # through this table, and a p-code with no row walks to nothing - which
        # would make that test's "untouched" pick read as a change, re-derive
        # the columns, and pass for entirely the wrong reason.
        self.village = AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, level=3, pcode="TD0103",
            iso3="TCD", country_name="Chad", name="Abeche Ville",
            parent_pcode="TD01", center_lat=13.82, center_lon=20.83)
        self.source = source
        self.job = ExtractionJob.objects.create(status="loaded")
        self.insight = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="document_ai", stated_on="2026-04-02", iso3="TCD",
            status="pending", job=self.job, match_method="unmatched")

    def url(self):
        return reverse("admin:insights_wizard_edit", args=[self.insight.id])

    def post_data(self, **overrides):
        prefix = f"insight-{self.insight.id}"
        data = {
            f"{prefix}-quote": QUOTE,
            f"{prefix}-quote_language": "en",
            f"{prefix}-voice_type": "community",
            f"{prefix}-channel": "document_ai",
            f"{prefix}-stated_on": "2026-04-02",
            f"{prefix}-country": "TCD",
            f"{prefix}-state": "",
            f"{prefix}-district": "",
            f"{prefix}-method": "llm",
            f"{prefix}-status": "pending",
            f"{prefix}-codings-TOTAL_FORMS": "0",
            f"{prefix}-codings-INITIAL_FORMS": "0",
            f"{prefix}-codings-MIN_NUM_FORMS": "0",
            f"{prefix}-codings-MAX_NUM_FORMS": "1000",
        }
        data.update({f"{prefix}-{key}": value for key, value in overrides.items()})
        return data

    def test_the_panel_renders_the_three_dropdowns(self):
        body = self.client.get(self.url()).content.decode()
        self.assertIn(f"insight-{self.insight.id}-country", body)
        self.assertIn(f"insight-{self.insight.id}-state", body)
        self.assertIn(f"insight-{self.insight.id}-district", body)

    def test_picking_a_state_derives_the_machine_columns(self):
        response = self.client.post(self.url(), self.post_data(state="TD01"))
        self.insight.refresh_from_db()
        self.assertTrue(response.json()["saved"])
        self.assertEqual(self.insight.admin_pcode, "TD01")
        self.assertEqual(self.insight.admin_level, 1)
        self.assertEqual(self.insight.match_method, "pcode")
        self.assertAlmostEqual(self.insight.lat, 13.8)

    def test_an_untouched_place_is_left_exactly_as_it_was(self):
        # A row the matcher reached by NAME, below the level the dropdowns can
        # express. Saving a change to something else must not move it.
        self.insight.admin_pcode = "TD0103"
        self.insight.admin_level = 3
        self.insight.match_method = "name"
        self.insight.save()
        self.client.post(self.url(), self.post_data(
            state="TD01", rejection_reason="checked against the source"))
        self.insight.refresh_from_db()
        self.assertEqual(self.insight.admin_pcode, "TD0103")
        self.assertEqual(self.insight.admin_level, 3)
        self.assertEqual(self.insight.match_method, "name")

    def test_a_state_from_the_wrong_country_is_refused(self):
        other = AdminArea.objects.create(
            source=self.source, kind=AdminArea.KIND_ADMIN, level=1, pcode="SD01",
            iso3="SDN", country_name="Sudan", name="Kassala", parent_pcode="SD")
        response = self.client.post(self.url(), self.post_data(state=other.pcode))
        self.insight.refresh_from_db()
        self.assertFalse(response.json()["saved"])
        self.assertIsNone(self.insight.admin_pcode)

    def test_a_successful_save_returns_the_row_in_read_mode(self):
        body = self.client.post(self.url(), self.post_data(state="TD01")).json()
        self.assertIn("wiz-review-row", body["row"])
        self.assertIn(QUOTE, body["row"])
