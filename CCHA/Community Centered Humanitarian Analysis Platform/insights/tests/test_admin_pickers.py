"""Picking a place from the boundary library instead of typing it.

The "Where" fieldset used to be seven boxes a reviewer typed into, five of them
machine fields - `admin_pcode`, `admin_level`, `match_method`, `lat`, `lon` -
that only an extraction had any business filling. Typing a p-code by hand is how
you get an insight on the wrong polygon, and typing `lat`/`lon` by hand is how
you get one in the sea.

So the reviewer now picks Country, then State/Region, then District, and the
five machine fields are DERIVED from that pick. The rule those tests defend is
"the deepest selection wins": a district answers the question better than the
state containing it, so it is the district's p-code that lands on the row.

Everything here places itself against a tiny hand-built boundary library rather
than the real one - three Sudanese rows and one Chadian - because these tests
are about the form's arithmetic, not about the OCHA data.
"""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from boundaries.models import AdminArea, BoundarySource
from insights.models import Insight, InsightFolder
from insights.verify import quote_sha1

QUOTE = "The water point has been dry since the rains failed."


def _library():
    """Sudan down to a district, plus Chad, so 'wrong country' is testable."""
    source = BoundarySource.objects.create(path="/test/cod.zip", source_label="test")

    def area(**kwargs):
        return AdminArea.objects.create(source=source, kind=AdminArea.KIND_ADMIN, **kwargs)

    sudan = area(iso3="SDN", country_name="Sudan", level=0, pcode="SD", name="Sudan")
    gezira = area(iso3="SDN", country_name="Sudan", level=1, pcode="SD03",
                  name="Aj Jazirah", parent_pcode="SD", center_lat=14.4, center_lon=33.5)
    madani = area(iso3="SDN", country_name="Sudan", level=2, pcode="SD03001",
                  name="Wad Madani Al Kubra", parent_pcode="SD03",
                  center_lat=14.401, center_lon=33.52)
    chad = area(iso3="TCD", country_name="Chad", level=0, pcode="TD", name="Chad")
    return sudan, gezira, madani, chad


class PlacePickerFormTests(TestCase):
    """Saving an Insight through the three dropdowns."""

    def setUp(self):
        self.user = User.objects.create_superuser("picker", "p@example.org", "pw")
        self.client.force_login(self.user)
        _library()

    def _post(self, **where):
        payload = {
            "quote": QUOTE,
            "quote_language": "en",
            "voice_type": "community",
            "channel": "manual",
            "stated_on": "2026-05-01",
            "method": "manual",
            "status": "pending",
            # All three inlines are part of the same form, and Django rejects the
            # whole thing if any one's management form is missing.
            "codings-TOTAL_FORMS": "0",
            "codings-INITIAL_FORMS": "0",
            "codings-MIN_NUM_FORMS": "0",
            "codings-MAX_NUM_FORMS": "1000",
            "figures-TOTAL_FORMS": "0",
            "figures-INITIAL_FORMS": "0",
            "figures-MIN_NUM_FORMS": "0",
            "figures-MAX_NUM_FORMS": "1000",
            "movements-TOTAL_FORMS": "0",
            "movements-INITIAL_FORMS": "0",
            "movements-MIN_NUM_FORMS": "0",
            "movements-MAX_NUM_FORMS": "1000",
        }
        payload.update(where)
        return self.client.post(reverse("admin:insights_insight_add"), payload, follow=True)

    def test_the_district_wins_over_the_state_containing_it(self):
        """The whole point: pick the finest place and that is what is recorded."""
        self._post(country="SDN", state="SD03", district="SD03001")

        row = Insight.objects.get()
        self.assertEqual(row.iso3, "SDN")
        self.assertEqual(row.admin_pcode, "SD03001")
        self.assertEqual(row.admin_level, 2)
        self.assertEqual(row.match_method, "pcode")
        self.assertAlmostEqual(row.lat, 14.401)
        self.assertAlmostEqual(row.lon, 33.52)

    def test_a_state_with_no_district_chosen_records_the_state(self):
        self._post(country="SDN", state="SD03", district="")

        row = Insight.objects.get()
        self.assertEqual(row.admin_pcode, "SD03")
        self.assertEqual(row.admin_level, 1)
        self.assertEqual(row.match_method, "pcode")
        self.assertAlmostEqual(row.lat, 14.4)

    def test_a_country_alone_is_a_valid_answer_and_places_nothing(self):
        """"Somewhere in Sudan" and "we do not know where" are the same finding
        at this resolution, and `places.resolve` calls it unmatched. So do we."""
        self._post(country="SDN", state="", district="")

        row = Insight.objects.get()
        self.assertEqual(row.iso3, "SDN")
        self.assertIsNone(row.admin_pcode)
        self.assertIsNone(row.admin_level)
        self.assertEqual(row.match_method, "unmatched")
        self.assertIsNone(row.lat)
        self.assertIsNone(row.lon)

    def test_the_country_is_required(self):
        response = self._post(country="", state="", district="")
        self.assertEqual(Insight.objects.count(), 0)
        self.assertContains(response, "required")

    def test_a_state_from_another_country_is_refused(self):
        """A stale dropdown - country changed, state not re-picked - must not
        put a Sudanese polygon on a Chadian insight. This is the same rule
        AdminArea.iso3 exists to enforce; see boundaries/README.md."""
        response = self._post(country="TCD", state="SD03", district="")
        self.assertEqual(Insight.objects.count(), 0)
        self.assertContains(response, "Aj Jazirah")

    def test_a_district_outside_the_chosen_state_is_refused(self):
        response = self._post(country="SDN", state="SD03", district="SD99999")
        self.assertEqual(Insight.objects.count(), 0)

    def test_place_name_as_written_is_not_touched_by_the_pick(self):
        """It is the source's own spelling, not the library's. An insight whose
        document says "Wad Medani" keeps saying "Wad Medani" even though the
        polycode it resolved to is spelled "Wad Madani Al Kubra"."""
        self._post(country="SDN", state="SD03", district="SD03001",
                   place_name_as_written="Wad Medani")

        self.assertEqual(Insight.objects.get().place_name_as_written, "Wad Medani")

    def test_the_machine_fields_are_no_longer_typed_in(self):
        """They are shown, read-only, so a reviewer can audit where the pick
        landed - but there is nothing on the page to type a p-code into."""
        response = self.client.get(reverse("admin:insights_insight_add"))
        self.assertNotContains(response, 'name="admin_pcode"')
        self.assertNotContains(response, 'name="match_method"')
        self.assertNotContains(response, 'name="lat"')


class PlacePickerEditTests(TestCase):
    """Opening a row that already has a place must show that place selected.

    The failure this prevents is the ugly one: a `ChoiceField` whose options
    are filled in by JavaScript has no valid choices server-side, so editing
    an insight's status would fail validation on a location nobody touched.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("editor", "e@example.org", "pw")
        self.client.force_login(self.user)
        _library()

    def _insight(self, **kwargs):
        return Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="manual", stated_on="2026-05-01", method="manual", **kwargs)

    def test_a_district_row_reopens_with_all_three_dropdowns_set(self):
        row = self._insight(iso3="SDN", admin_pcode="SD03001", admin_level=2,
                            match_method="pcode")
        response = self.client.get(
            reverse("admin:insights_insight_change", args=[row.id]))
        form = response.context["adminform"].form

        self.assertEqual(form["country"].value(), "SDN")
        self.assertEqual(form["state"].value(), "SD03")
        self.assertEqual(form["district"].value(), "SD03001")
        # And the state/district dropdowns are populated, not empty - otherwise
        # re-saving would fail with "Select a valid choice".
        self.assertIn("SD03", [value for value, label in form.fields["state"].choices])
        self.assertIn("SD03001",
                      [value for value, label in form.fields["district"].choices])

    def test_an_iso3_the_library_does_not_hold_still_opens_and_saves(self):
        """The library holds nine countries. An insight extracted for a tenth
        must not become uneditable - a reviewer has to be able to reject it."""
        row = self._insight(iso3="KEN", match_method="unmatched")
        response = self.client.get(
            reverse("admin:insights_insight_change", args=[row.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["adminform"].form["country"].value(), "KEN")

    def test_resaving_an_untouched_row_keeps_its_place(self):
        row = self._insight(iso3="SDN", admin_pcode="SD03001", admin_level=2,
                            match_method="pcode", lat=14.401, lon=33.52)
        self.client.post(reverse("admin:insights_insight_change", args=[row.id]), {
            "quote": QUOTE, "quote_language": "en", "voice_type": "community",
            "channel": "manual", "stated_on": "2026-05-01", "method": "manual",
            "status": "published",
            "country": "SDN", "state": "SD03", "district": "SD03001",
            "codings-TOTAL_FORMS": "0", "codings-INITIAL_FORMS": "0",
            "figures-TOTAL_FORMS": "0", "figures-INITIAL_FORMS": "0",
            "figures-MIN_NUM_FORMS": "0", "figures-MAX_NUM_FORMS": "1000",
            "movements-TOTAL_FORMS": "0", "movements-INITIAL_FORMS": "0",
            "movements-MIN_NUM_FORMS": "0", "movements-MAX_NUM_FORMS": "1000",
            "codings-MIN_NUM_FORMS": "0", "codings-MAX_NUM_FORMS": "1000",
        }, follow=True)

        row.refresh_from_db()
        self.assertEqual(row.status, "published")
        self.assertEqual(row.admin_pcode, "SD03001")
        self.assertEqual(row.admin_level, 2)


class ReSaveGuardTests(TestCase):
    """Re-saving a row nobody relocated must not move it.

    `places.resolve()` matches a place name at ANY level, so extracted insights
    land at ADM3 and ADM4 too - Ethiopia alone has 1,082 ADM3 areas. This form
    offers three levels, which is what was asked for and is the right depth to
    type into. The two facts collide on save: if saving always re-derived the
    location from the dropdowns, then opening an ADM3 insight to repair an OCR
    artefact and clicking Save would silently blank its p-code, its level and
    its coordinates - because the dropdowns cannot express where it is, so they
    would overwrite it with where they can.

    So the rule is: derive only when the pick actually CHANGED. An untouched
    location is left exactly as the extractor wrote it.

    The same guard protects provenance. A row matched by NAME must not be
    quietly restamped "pcode" because a reviewer edited its rejection reason -
    match_method is the column that records how far the matcher actually got,
    and rewriting it would destroy the only evidence of that.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("resaver", "rs@example.org", "pw")
        self.client.force_login(self.user)
        source = BoundarySource.objects.create(path="/test/deep.zip")

        def area(**kwargs):
            return AdminArea.objects.create(
                source=source, kind=AdminArea.KIND_ADMIN, iso3="SDN",
                country_name="Sudan", **kwargs)

        area(level=0, pcode="SD", name="Sudan")
        area(level=1, pcode="SD03", name="Aj Jazirah", parent_pcode="SD",
             center_lat=14.4, center_lon=33.5)
        area(level=2, pcode="SD03001", name="Wad Madani Al Kubra",
             parent_pcode="SD03", center_lat=14.401, center_lon=33.52)
        # The level the form cannot express.
        area(level=3, pcode="SD03001005", name="Hantoub", parent_pcode="SD03001",
             center_lat=14.44, center_lon=33.55)

    def _insight(self, **kwargs):
        return Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="document_ai", stated_on="2026-05-01", method="llm",
            iso3="SDN", **kwargs)

    def _resave(self, row, **overrides):
        """POST the change form back with exactly the values it rendered."""
        form = self.client.get(
            reverse("admin:insights_insight_change", args=[row.id])
        ).context["adminform"].form
        payload = {
            "quote": row.quote, "quote_language": "en", "voice_type": row.voice_type,
            "channel": row.channel, "stated_on": "2026-05-01", "method": row.method,
            "status": row.status,
            "country": form["country"].value() or "",
            "state": form["state"].value() or "",
            "district": form["district"].value() or "",
            "codings-TOTAL_FORMS": "0", "codings-INITIAL_FORMS": "0",
            "figures-TOTAL_FORMS": "0", "figures-INITIAL_FORMS": "0",
            "figures-MIN_NUM_FORMS": "0", "figures-MAX_NUM_FORMS": "1000",
            "movements-TOTAL_FORMS": "0", "movements-INITIAL_FORMS": "0",
            "movements-MIN_NUM_FORMS": "0", "movements-MAX_NUM_FORMS": "1000",
            "codings-MIN_NUM_FORMS": "0", "codings-MAX_NUM_FORMS": "1000",
        }
        payload.update(overrides)
        response = self.client.post(
            reverse("admin:insights_insight_change", args=[row.id]), payload, follow=True)
        row.refresh_from_db()
        return response

    def test_an_adm3_row_survives_a_re_save_untouched(self):
        row = self._insight(admin_pcode="SD03001005", admin_level=3,
                            match_method="name", lat=14.44, lon=33.55)
        self._resave(row, status="published")

        self.assertEqual(row.status, "published")       # the edit did land
        self.assertEqual(row.admin_pcode, "SD03001005")  # and the place did not move
        self.assertEqual(row.admin_level, 3)
        self.assertEqual(row.match_method, "name")
        self.assertAlmostEqual(row.lat, 14.44)
        self.assertAlmostEqual(row.lon, 33.55)

    def test_an_adm3_row_shows_the_state_and_district_that_contain_it(self):
        """It cannot be shown exactly, so it is shown honestly: the dropdowns
        walk up to the district and state above it rather than going blank."""
        row = self._insight(admin_pcode="SD03001005", admin_level=3,
                            match_method="name")
        form = self.client.get(
            reverse("admin:insights_insight_change", args=[row.id])
        ).context["adminform"].form

        self.assertEqual(form["state"].value(), "SD03")
        self.assertEqual(form["district"].value(), "SD03001")

    def test_a_name_matched_row_is_not_restamped_as_a_pcode_match(self):
        row = self._insight(admin_pcode="SD03", admin_level=1,
                            match_method="name", lat=14.4, lon=33.5)
        self._resave(row, rejection_reason="Paraphrased, not verbatim.")

        self.assertEqual(row.match_method, "name")
        self.assertEqual(row.admin_pcode, "SD03")

    def test_an_unplaced_row_is_not_disturbed(self):
        row = self._insight(match_method="unmatched")
        self._resave(row, status="rejected")

        self.assertEqual(row.status, "rejected")
        self.assertIsNone(row.admin_pcode)
        self.assertEqual(row.match_method, "unmatched")

    def test_actually_changing_the_pick_still_re_derives(self):
        """The guard must not freeze a location a reviewer means to correct."""
        row = self._insight(admin_pcode="SD03001005", admin_level=3,
                            match_method="name", lat=14.44, lon=33.55)
        self._resave(row, district="")   # reviewer clears it back to the state

        self.assertEqual(row.admin_pcode, "SD03")
        self.assertEqual(row.admin_level, 1)
        self.assertEqual(row.match_method, "pcode")
        self.assertAlmostEqual(row.lat, 14.4)


class OrphanAreaTests(TestCase):
    """A district with no state above it must still be reachable.

    South Sudan's Abyei Region is an ADM2 whose recorded parent, "SS00", is not
    an ADM1 the library holds - the disputed area sits outside the state
    structure. A strict Country > State > District cascade would make it
    unpickable, which in a Sudan/South Sudan platform is not a gap worth
    shipping. It is offered in the state slot instead.

    The level it is SAVED with is the interesting part. It is a real ADM2, and
    that is what has to be recorded - `InsightPlaceForm.save` reads the level off the
    AdminArea row rather than inferring it from which dropdown the p-code came
    out of, so picking Abyei "as a state" still stores admin_level 2.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("abyei", "ab@example.org", "pw")
        self.client.force_login(self.user)
        source = BoundarySource.objects.create(path="/test/ss.zip")
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SSD",
            country_name="South Sudan", level=0, pcode="SS", name="South Sudan")
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SSD",
            country_name="South Sudan", level=1, pcode="SS01", name="Warrap",
            parent_pcode="SS")
        AdminArea.objects.create(
            source=source, kind=AdminArea.KIND_ADMIN, iso3="SSD",
            country_name="South Sudan", level=2, pcode="SS0001",
            name="Abyei Region", parent_pcode="SS00",   # an ADM1 that is not there
            center_lat=9.6, center_lon=28.4)

    def test_the_orphan_is_offered_beside_the_real_states(self):
        response = self.client.get(
            reverse("admin:insights_place_options"), {"parent": "SSD", "level": "1"})
        names = [area["name"] for area in response.json()["areas"]]
        self.assertEqual(names, ["Abyei Region", "Warrap"])

    def test_choosing_it_records_its_true_adm2_level(self):
        self.client.post(reverse("admin:insights_insight_add"), {
            "quote": QUOTE, "quote_language": "en", "voice_type": "community",
            "channel": "manual", "stated_on": "2026-05-01", "method": "manual",
            "status": "pending",
            "country": "SSD", "state": "SS0001", "district": "",
            "codings-TOTAL_FORMS": "0", "codings-INITIAL_FORMS": "0",
            "figures-TOTAL_FORMS": "0", "figures-INITIAL_FORMS": "0",
            "figures-MIN_NUM_FORMS": "0", "figures-MAX_NUM_FORMS": "1000",
            "movements-TOTAL_FORMS": "0", "movements-INITIAL_FORMS": "0",
            "movements-MIN_NUM_FORMS": "0", "movements-MAX_NUM_FORMS": "1000",
            "codings-MIN_NUM_FORMS": "0", "codings-MAX_NUM_FORMS": "1000",
        }, follow=True)

        row = Insight.objects.get()
        self.assertEqual(row.admin_pcode, "SS0001")
        self.assertEqual(row.admin_level, 2)
        self.assertEqual(row.match_method, "pcode")

    def test_it_reopens_in_the_state_slot_it_was_chosen_from(self):
        row = Insight.objects.create(
            quote=QUOTE, quote_sha1=quote_sha1(QUOTE), voice_type="community",
            channel="manual", stated_on="2026-05-01", method="manual",
            iso3="SSD", admin_pcode="SS0001", admin_level=2, match_method="pcode")
        form = self.client.get(
            reverse("admin:insights_insight_change", args=[row.id])
        ).context["adminform"].form

        self.assertEqual(form["state"].value(), "SS0001")
        self.assertEqual(form["district"].value(), "")


class PlaceOptionsEndpointTests(TestCase):
    """The JSON the dropdowns refill themselves from."""

    def setUp(self):
        self.user = User.objects.create_superuser("api", "a@example.org", "pw")
        self.client.force_login(self.user)
        _library()

    def test_states_of_a_country(self):
        response = self.client.get(
            reverse("admin:insights_place_options"), {"parent": "SDN", "level": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["areas"],
                         [{"pcode": "SD03", "name": "Aj Jazirah"}])

    def test_districts_of_a_state(self):
        response = self.client.get(
            reverse("admin:insights_place_options"), {"parent": "SD03", "level": "2"})
        self.assertEqual(response.json()["areas"],
                         [{"pcode": "SD03001", "name": "Wad Madani Al Kubra"}])

    def test_a_country_with_no_states_returns_an_empty_list_not_an_error(self):
        response = self.client.get(
            reverse("admin:insights_place_options"), {"parent": "TCD", "level": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["areas"], [])

    def test_it_is_staff_only(self):
        self.client.logout()
        response = self.client.get(
            reverse("admin:insights_place_options"), {"parent": "SDN", "level": "1"})
        self.assertIn(response.status_code, (302, 403))


class FolderBrowserEndpointTests(TestCase):
    """Choosing a folder by clicking down to it.

    A browser's own directory input hands back a path on the reviewer's Windows
    machine, which does not exist inside this container. So the browsing is done
    server-side, and it is confined to the configured roots - a reviewer who can
    reach this page must not be able to walk it to /etc.

    These override INSIGHT_DOCUMENT_ROOTS rather than SOURCE_ROOT: the roots are
    a setting of their own now, so a deployment can name several and none of
    them has to be the source-document mount. Overriding it here is also what
    proves that setting is what drives the browser.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("browser", "b@example.org", "pw")
        self.client.force_login(self.user)

    def _get(self, **params):
        return self.client.get(reverse("admin:insights_folder_browse"), params)

    def test_the_roots_are_listed_when_no_path_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(INSIGHT_DOCUMENT_ROOTS=[Path(tmp)]):
                body = self._get().json()
        self.assertEqual([entry["path"] for entry in body["roots"]][0], tmp)

    def test_subdirectories_are_listed_and_files_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "DTM Round 12").mkdir()
            (Path(tmp) / "notes.pdf").write_text("x", encoding="utf-8")
            with override_settings(INSIGHT_DOCUMENT_ROOTS=[Path(tmp)]):
                body = self._get(path=tmp).json()

        self.assertEqual([entry["name"] for entry in body["entries"]], ["DTM Round 12"])
        # The count of readable documents is what tells a reviewer whether this
        # is the folder they want before they commit to it.
        self.assertEqual(body["document_count"], 1)

    def test_a_path_outside_the_roots_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(INSIGHT_DOCUMENT_ROOTS=[Path(tmp)]):
                response = self._get(path="/etc")
        self.assertEqual(response.status_code, 400)

    def test_a_traversal_out_of_a_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = Path(tmp) / "inner"
            inner.mkdir()
            with override_settings(INSIGHT_DOCUMENT_ROOTS=[inner]):
                response = self._get(path=str(inner / ".." / ".."))
        self.assertEqual(response.status_code, 400)

    def test_it_is_staff_only(self):
        self.client.logout()
        response = self._get()
        self.assertIn(response.status_code, (302, 403))


class CountryDropdownTests(TestCase):
    """Folder and Upload get a Country dropdown, and nothing deeper.

    Their iso3 is only ever a cataloguing hint - it lands in
    Document.country_focus, and insights/prompts/extract_insights.md tells the
    extractor in as many words not to copy it to an insight's own iso3. The
    country an insight is about comes out of the document. So there is no state
    or district to pick here; there is a list of countries instead of a box to
    mistype a code into.
    """

    def setUp(self):
        self.user = User.objects.create_superuser("cataloguer", "c@example.org", "pw")
        self.client.force_login(self.user)
        _library()

    def test_the_folder_form_offers_countries_by_name(self):
        response = self.client.get(reverse("admin:insights_insightfolder_add"))
        choices = response.context["adminform"].form.fields["default_iso3"].choices
        self.assertIn(("SDN", "Sudan"), list(choices))

    def test_a_folder_saves_the_chosen_country(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.client.post(reverse("admin:insights_insightfolder_add"), {
                "label": "IOM DTM Chad round 12",
                "path": tmp,
                "default_iso3": "TCD",
                "recursive": "on",
            }, follow=True)

        self.assertEqual(InsightFolder.objects.get().default_iso3, "TCD")

    def test_a_country_the_library_does_not_hold_is_still_accepted(self):
        """The dropdown stops typos; it must not become a gate on cataloguing.

        This value is only ever a hint - it lands in Document.country_focus,
        which is free text. Refusing an unlisted code would mean an office that
        has not run `load_boundaries` yet could catalogue nothing at all, and a
        document about a tenth country could never be filed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.client.post(reverse("admin:insights_insightfolder_add"), {
                "label": "Kenya cross-border reporting",
                "path": tmp,
                "default_iso3": "KEN",
                "recursive": "on",
            }, follow=True)

        self.assertEqual(InsightFolder.objects.get().default_iso3, "KEN")

    def test_the_folder_country_stays_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.client.post(reverse("admin:insights_insightfolder_add"), {
                "label": "Mixed regional reporting",
                "path": tmp,
                "default_iso3": "",
                "recursive": "on",
            }, follow=True)

        folder = InsightFolder.objects.get()
        self.assertEqual(folder.label, "Mixed regional reporting")
        self.assertFalse(folder.default_iso3)
