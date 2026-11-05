# Montandon Hazard Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull IFRC Montandon hazard events, severities and impacts for the eight countries of focus over a fixed 15 Apr 2023 → today window behind a per-country admin button, cluster every hazard into the IFRC hazard codebook's categories, and split the dashboard's Hazard dropdown into Hazard and Sub-Hazard driven by what the data actually holds.

**Architecture:** A JSON codebook file is the single vocabulary, read by one module (`external_data/hazards.py`) that three consumers use. A new fetcher makes three serial POST calls per country against Montandon's STAC API; three loaders write `HazardEvent`, apply severity onto it by `corr_id`, and write `HazardImpact`. A pipeline step exports two dashboard files, and `renderThemes()` unions the Montandon feed into the polygons it already lights.

**Tech Stack:** Django 5 + PostGIS (no GeoDjango — raw SQL for geometry), `requests`, vanilla JS + MapLibre, Docker Compose. All commands run inside the container.

**Spec:** `docs/superpowers/specs/2026-09-17-montandon-hazard-layer-design.md` — read it before Task 1. Every design decision below is argued there.

## Global Constraints

- **Everything runs in Docker.** There is no Django environment on the host. Every command in this plan is `docker compose exec web python manage.py …`, run from the repo root.
- **Window start is `settings.CRISIS_START`**, the string `"2023-04-15"`. Do **not** introduce a second constant. `external_data/fetchers/ipc.py` already parses it in `_crisis_floor()` and states why a fetcher must not import `data_pipeline`; Task 2 moves that helper into `fetchers/base.py` so both use one copy.
- **Countries of focus, in this exact order:** `SDN, TCD, SSD, EGY, ETH, LBY, CAF, UGA`.
- **Montandon collections, exactly these three families:** `gdacs`, `pdc`, `idmc-idu`. `idmc-idu-hazards` does not exist and must never be requested.
- **`source` is always the string `montandon`** on `HazardEvent` and `HazardImpact`. The publisher goes in `collection`. Writing `gdacs` into `source` makes `loaders/base.load()` compute `sync.row_count` as zero forever.
- **Settings that may be blank in `.env` use `os.environ.get(X) or default`,** never `get(X, default)`. An empty line in `.env` must fall back.
- **`parse()` is pure.** `loaders/base.py` documents it as *"Pure — no database access"*. Anything needing rows to exist goes in the new `after_insert()` hook.
- **`severity_value` is never sorted, compared or aggregated across collections.** GDACS 0.5/"Green" and PDC 0.1/"WATCH" are different scales. Display is always `severity_label (severity_unit)`.
- **After Tasks 3 and 8 (model changes) and Task 10 (JS/template):** `docker compose restart web`. Gunicorn never autoreloads.
- **Never pull two IPC countries in parallel** — unrelated to this work, but the serial-generator rule in `refresh_external.py` that enforces it must not be weakened by Task 2.

---

## File Structure

**Created**

| file | responsibility |
|---|---|
| `data_pipeline/hazard_codebook.json` | the vocabulary: 9 categories, their definitions, the HIP→category table, the tag→category table, the detection rule |
| `external_data/hazards.py` | the only reader of that file. Lookup helpers; no Django models, no I/O beyond the one read |
| `external_data/fetchers/montandon.py` | three Calls per country: events, hazards, impacts |
| `external_data/loaders/montandon.py` | the three loaders |
| `external_data/migrations/0014_hazard_events.py` | `HazardEvent` + `HazardImpact` |
| `external_data/migrations/0015_seed_montandon_sources.py` | the eight `source_sync` rows |
| `data_track/migrations/00NN_narrativetag_hazard_category.py` | two nullable columns |
| `external_data/tests/test_hazard_codebook.py` | the vocabulary is complete and consistent |
| `external_data/tests/test_fetcher_montandon.py` | Call shape, window, auth, pagination |
| `external_data/tests/test_loader_montandon.py` | rows, severity join, p-codes, significance |
| `external_data/tests/fixtures/montandon_events_sdn.json` | trimmed real payload |
| `external_data/tests/fixtures/montandon_hazards_sdn.json` | trimmed real payload |
| `external_data/tests/fixtures/montandon_impacts_sdn.json` | trimmed real payload |
| `data_pipeline/tests/test_hazard_export.py` | `hazards.json`, `hazard_events.json`, insight linking |

**Modified**

| file | change |
|---|---|
| `config/settings.py` | `IFRC_API_TOKEN`, `MONTANDON_STAC_URL`, `HAZARD_CODEBOOK` |
| `env.example` | the token, documented |
| `external_data/fetchers/base.py` | `SECRET_SETTINGS`, `Call.method/body/headers`, `http_post_json`, `fetch_all_pages_token`, `fetch`, `crisis_floor` |
| `external_data/fetchers/ipc.py` | use the shared `crisis_floor` |
| `external_data/fetchers/__init__.py` | import `montandon` |
| `external_data/loaders/base.py` | `after_insert()` hook, `counts_rows` attribute |
| `external_data/loaders/__init__.py` | import `montandon` |
| `external_data/management/commands/refresh_external.py` | `payload = base.fetch(call)` |
| `external_data/models.py` | `HazardEvent`, `HazardImpact` |
| `external_data/admin.py` | two read-only admins |
| `mcp/admin.py` | `SOURCE_LABELS["montandon"]` |
| `data_track/models.py` | `NarrativeTag.hazard_category`, `.hazard_sub` |
| `data_pipeline/steps/s03_parse.py` | stamp the two columns |
| `data_pipeline/steps/s06_mcp_layers.py` | `build_hazards()`, `build_hazard_events()`, widen `build_theme_areas()` |
| `dashboard/static/dashboard/js/app.js` | two dropdowns, `renderThemes()` union, popup |

---

### Task 1: The hazard codebook and its reader

**Files:**
- Create: `data_pipeline/hazard_codebook.json`
- Create: `external_data/hazards.py`
- Modify: `config/settings.py`
- Test: `external_data/tests/test_hazard_codebook.py`

**Interfaces:**
- Consumes: nothing.
- Produces — every later task depends on these exact names:
  - `hazards.codebook() -> dict`
  - `hazards.categories() -> list[dict]` (display order)
  - `hazards.for_hip(code: str) -> tuple[str, str]` → `(category_key, sub_key)`; `("uncategorised", "uncategorised")` when unknown
  - `hazards.for_tag(tag: str) -> tuple[str | None, str | None]`; `(None, None)` when unmapped
  - `hazards.hip_from_codes(codes: list[str]) -> str | None` — picks the HIP code out of Montandon's mixed list
  - `hazards.is_detection(collection: str, severity_label: str | None, max_impact: float | None) -> bool`
  - `hazards.sub_label(sub_key: str) -> str`

**Why `external_data/hazards.py` and not `data_pipeline/common.py`:** `external_data/fetchers/ipc.py` states that a fetcher "has no business importing the pipeline". `s06_mcp_layers.py` already does `from external_data.models import …`, so pipeline→external_data is the established direction. One reader module in `external_data`, the JSON file beside `taxonomy.json` where a person looks for vocabulary, found through a setting.

- [ ] **Step 1: Add the settings entry**

In `config/settings.py`, beside `MCP_CACHE_DIR`:

```python
# The hazard vocabulary: IFRC codebook categories, the HIP codes observed for
# the countries of focus, and the document tags, all mapped to one category set.
# Beside taxonomy.json because it is the same kind of thing - a vocabulary a
# person edits - but read through external_data/hazards.py, because a fetcher
# must not import the pipeline (see fetchers/ipc.py:_crisis_floor).
HAZARD_CODEBOOK = env_path("HAZARD_CODEBOOK",
                           BASE_DIR / "data_pipeline" / "hazard_codebook.json")
```

- [ ] **Step 2: Write the codebook file**

Create `data_pipeline/hazard_codebook.json`. `definition` carries the codebook's defining sentence, quoted exactly from pages 7–9 of the PDF; the full paragraph stays in the PDF.

```json
{
  "_comment": "IFRC hazard codebook (2021) used as a CLUSTERING METHOD, not a list to render. Categories and definitions are the codebook's; membership comes from the data. hip_codes is keyed on the UNDRR-ISC HIP code and NOT on the nat-*-*-* slug: the slug is absent on ~38% of Montandon items and, where present, disagrees with the codebook twice - wildfire (UNDRR climatological, codebook non-technological) and extreme heat (UNDRR meteorological, codebook climatological). Source: https://www.ifrc.org/sites/default/files/2021-06/04-HAZARD-DEFINITIONS-HR.pdf",

  "detection_rules": {
    "_comment": "A 'detection' is a machine observation with no evidence of consequence. Only GDACS is configured, because only GDACS produces the problem: 385 of the first 500 region-wide events are its satellite fire detections, Green with zero affected. PDC and IDMC-IDU have no rule, so everything they publish is an 'event'.",
    "gdacs": { "no_alert_severity_labels": ["Green"] }
  },

  "categories": [
    {
      "key": "climatological",
      "label": "Climatological hazards",
      "in_codebook": true,
      "definition": "Hazards arising from long-lived, meso- to macro-scale atmospheric processes, from intra-seasonal to multi-decadal climate variability.",
      "sub_hazards": [
        { "key": "drought", "label": "Drought", "source": "codebook",
          "definition": "A long-lasting event triggered by a lack of precipitation." },
        { "key": "extreme_heat", "label": "Extreme heat / heat wave", "source": "codebook",
          "definition": "A period during which the daily maximum temperature exceeds for more than five consecutive days the maximum normal temperature by 5 degrees Celsius." },
        { "key": "extreme_cold", "label": "Extreme cold / cold wave", "source": "codebook",
          "definition": "Marked cooling of the air, or the invasion of very cold air, over a large area." },
        { "key": "extreme_heat_drought", "label": "Extreme heat / drought (reported)", "source": "documents",
          "definition": "Document reporting of drought, extreme heat or water scarcity. One tag spanning two codebook hazards; splitting it would mean re-parsing the corpus." }
      ]
    },
    {
      "key": "biological",
      "label": "Biological hazards",
      "in_codebook": true,
      "definition": "Hazards of organic origin or conveyed by biological vectors, including exposure to pathogenic micro-organisms, toxins and bioactive substances.",
      "sub_hazards": [
        { "key": "biological_emergency", "label": "Biological emergency", "source": "codebook",
          "definition": "A biological emergency can occur when there is a major epidemic outbreak of diseases, plant or animal contagion, insect or other animal plagues and infestations." },
        { "key": "epidemic_pandemic", "label": "Major epidemic and potential pandemic diseases", "source": "codebook",
          "definition": "Either an unusual increase in the number of cases of an infectious disease that already exists in the region or population concerned, or the appearance of an infection disease previously absent from a region." },
        { "key": "disease_outbreak", "label": "Disease outbreak (reported)", "source": "documents",
          "definition": "Document reporting of cholera, measles, dengue, malaria, hepatitis or another epidemic." }
      ]
    },
    {
      "key": "geophysical",
      "label": "Geophysical hazards",
      "in_codebook": true,
      "definition": "Hazards originating from internal earth processes.",
      "sub_hazards": [
        { "key": "earthquake", "label": "Earthquake", "source": "codebook",
          "definition": "A term used to describe both sudden slip on a fault, and the resulting ground shaking and radiated seismic energy caused by the slip, or by volcanic or magmatic activity, or other sudden stress changes in the earth." },
        { "key": "landslide", "label": "Landslide / debris flow", "source": "codebook",
          "definition": "Movement of surface material down a slope." },
        { "key": "tsunami", "label": "Tsunami", "source": "codebook",
          "definition": "A sea wave of local or distant origin that results from large-scale seafloor displacements associated with strong earthquakes, major submarine slides, or exploding volcanic islands." },
        { "key": "volcanic_eruption", "label": "Volcanic eruption", "source": "codebook",
          "definition": "The discharge (aerially explosive) of fragmentary ejecta, lava and gases from a volcanic vent." }
      ]
    },
    {
      "key": "meteorological",
      "label": "Meteorological hazards",
      "in_codebook": true,
      "definition": "Hazards caused by short-lived, micro- to meso-scale extreme weather and atmospheric conditions that last from minutes to days.",
      "sub_hazards": [
        { "key": "tropical_cyclone", "label": "Tropical cyclone", "source": "codebook",
          "definition": "An atmospheric closed low pressure circulation system rotating counter-clockwise in the Northern Hemisphere and clockwise in the Southern Hemisphere." },
        { "key": "thunderstorm", "label": "Thunderstorm / lightning", "source": "observed",
          "definition": "Convective storm with thunder and lightning. Not named in the codebook; placed here by the Meteorological definition above." },
        { "key": "violent_wind", "label": "Storm (violent wind)", "source": "observed",
          "definition": "Wind- and pressure-related convective storm, including dust and sand storms. Not named in the codebook; placed here by the Meteorological definition above." }
      ]
    },
    {
      "key": "hydrological",
      "label": "Hydrological hazards",
      "in_codebook": true,
      "definition": "Hazards caused by the occurrence, movement and distribution of surface and subsurface freshwater and saltwater.",
      "sub_hazards": [
        { "key": "floods", "label": "Floods", "source": "codebook",
          "definition": "The overflowing of the normal confines of a stream or other body of water, or the accumulation of water over areas that are not normally submerged. This includes: river/fluvial floods." },
        { "key": "storm_surge", "label": "Storm surge", "source": "codebook",
          "definition": "The temporary increase, at a particular locality, in the height of the sea due to extreme meteorological conditions." },
        { "key": "hailstorm", "label": "Hailstorms", "source": "codebook",
          "definition": "Storms that produce hail that reaches the ground are known as hailstorms." },
        { "key": "flooding", "label": "Flooding (reported)", "source": "documents",
          "definition": "Document reporting of flood, heavy rain or inundation." }
      ]
    },
    {
      "key": "technological",
      "label": "Technological and man-made hazards",
      "in_codebook": true,
      "definition": "Hazards that are induced entirely or predominantly by human activities and choices. This term does not include the occurrence or risk of armed conflicts and other situations of social instability or tension that are subject to international humanitarian law and national legislation.",
      "sub_hazards": [
        { "key": "man_made", "label": "Man-made hazards", "source": "codebook",
          "definition": "Hazards that are induced entirely or predominantly by human activities and choices." },
        { "key": "nuclear_emergency", "label": "Nuclear emergency", "source": "codebook",
          "definition": "Nuclear emergencies involve or emerge from nuclear chain reactions." },
        { "key": "radiological_emergency", "label": "Radiological emergency", "source": "codebook",
          "definition": "Radiological emergencies can involve all other sources of radiation, such as radiography machines, radioactive material for use in industry, lost sources and more." },
        { "key": "chemical_emergency", "label": "Chemical emergency", "source": "codebook",
          "definition": "Any unplanned event involving hazardous substances that causes or is liable to cause harm to health, the environment or property." }
      ]
    },
    {
      "key": "non_technological",
      "label": "Non-technological and man-made hazards",
      "in_codebook": true,
      "definition": "Man-made hazards outside the technological group.",
      "sub_hazards": [
        { "key": "wildfires", "label": "Wildfires", "source": "codebook",
          "definition": "This includes all types of fire events, wildfires and forest fires. It is the process of combustion of inflammable materials producing heat, flames and (often) smoke." }
      ]
    },
    {
      "key": "conflict_violence",
      "label": "Conflict and violence",
      "in_codebook": false,
      "definition": "NOT an IFRC codebook category. The codebook explicitly excludes armed conflict from man-made hazards, but six of this project's ten hazard tags are conflict tags and they are most of the hazard reporting in a Sudan dashboard. Filing them as uncategorised would label the largest group in the data as leftovers.",
      "sub_hazards": [
        { "key": "armed_conflict", "label": "Armed conflict", "source": "documents", "definition": "" },
        { "key": "shelling_airstrikes", "label": "Shelling / airstrikes", "source": "documents", "definition": "" },
        { "key": "attacks_on_civilians", "label": "Attacks on civilians", "source": "documents", "definition": "" },
        { "key": "siege_blockade", "label": "Siege / blockade", "source": "documents", "definition": "" },
        { "key": "looting_robbery", "label": "Looting / robbery", "source": "documents", "definition": "" },
        { "key": "explosive_ordnance", "label": "Explosive ordnance", "source": "documents", "definition": "" }
      ]
    },
    {
      "key": "food_insecurity",
      "label": "Food insecurity and famine",
      "in_codebook": false,
      "definition": "NOT an IFRC codebook category. The codebook has no food-security hazard, and in Sudan famine is a consequence of conflict rather than a hazard in its own right - but food insecurity is central to this dashboard and needs to stay visible as its own thing.",
      "sub_hazards": [
        { "key": "famine_food_crisis", "label": "Famine / food crisis", "source": "documents", "definition": "" }
      ]
    },
    {
      "key": "uncategorised",
      "label": "Uncategorised",
      "in_codebook": false,
      "definition": "Where a HIP code Montandon sends that this file does not hold ends up. Never guessed at; always logged. A row here is a prompt to extend hip_codes.",
      "sub_hazards": [
        { "key": "uncategorised", "label": "Uncategorised", "source": "fallback", "definition": "" }
      ]
    }
  ],

  "hip_codes": {
    "EN0205": { "category": "non_technological", "sub": "wildfires",
                "note": "Wildfire. UNDRR slug nat-cli-wil-wil says climatological; the IFRC codebook names Wildfires under non-technological and man-made. The codebook wins." },
    "MH0600": { "category": "hydrological", "sub": "floods", "note": "Flood. nat-hyd-flo-flo." },
    "MH0103": { "category": "meteorological", "sub": "thunderstorm",
                "note": "Thunderstorm / lightning. Montandon keywords: Thunderstorm, Lightning (electrical storm), Convective-Related. Shares the nat-met-sto-sto slug with MH0301, which is why this table is keyed on the HIP code." },
    "MH0301": { "category": "meteorological", "sub": "violent_wind",
                "note": "Violent wind (GLIDE VW). Montandon keywords: Wind & Pressure-related, Dust Storm or Sandstorm. Seen as IDMC-IDU displacement events in CAR." },
    "MH0501": { "category": "climatological", "sub": "extreme_heat",
                "note": "Extreme heat. UNDRR slug nat-met-ext-hea says meteorological; the IFRC codebook files heat waves as climatological. The codebook wins." },
    "MH0401": { "category": "climatological", "sub": "drought", "note": "Drought. nat-cli-dro-dro." },
    "GH0300": { "category": "geophysical", "sub": "landslide", "note": "Landslide. nat-geo-mmd-lan." },
    "GH0101": { "category": "geophysical", "sub": "earthquake", "note": "Earthquake. nat-geo-ear-gro." }
  },

  "tags": {
    "flooding":            { "category": "hydrological",      "sub": "flooding" },
    "disease_outbreak":    { "category": "biological",        "sub": "disease_outbreak" },
    "extreme_heat_drought":{ "category": "climatological",    "sub": "extreme_heat_drought" },
    "armed_conflict":      { "category": "conflict_violence", "sub": "armed_conflict" },
    "shelling_airstrikes": { "category": "conflict_violence", "sub": "shelling_airstrikes" },
    "attacks_on_civilians":{ "category": "conflict_violence", "sub": "attacks_on_civilians" },
    "siege_blockade":      { "category": "conflict_violence", "sub": "siege_blockade" },
    "looting_robbery":     { "category": "conflict_violence", "sub": "looting_robbery" },
    "explosive_ordnance":  { "category": "conflict_violence", "sub": "explosive_ordnance" },
    "famine_food_crisis":  { "category": "food_insecurity",   "sub": "famine_food_crisis" }
  }
}
```

- [ ] **Step 3: Write the failing test**

Create `external_data/tests/test_hazard_codebook.py`:

```python
"""The hazard vocabulary is complete, consistent and keyed on the HIP code.

The test that matters most is test_every_taxonomy_hazard_tag_is_mapped: it fails
the day somebody adds a hazard tag to taxonomy.json and forgets this file, which
would otherwise show up as a tag silently missing from the dashboard dropdown.
"""
import json

from django.conf import settings
from django.test import TestCase

from external_data import hazards


class CodebookShapeTests(TestCase):
    def test_every_category_declares_whether_it_is_the_codebooks(self):
        for cat in hazards.categories():
            self.assertIn("in_codebook", cat, cat["key"])
            self.assertIsInstance(cat["in_codebook"], bool)

    def test_the_seven_codebook_categories_are_present_and_defined(self):
        expected = {"climatological", "biological", "geophysical", "meteorological",
                    "hydrological", "technological", "non_technological"}
        real = {c["key"] for c in hazards.categories() if c["in_codebook"]}
        self.assertEqual(real, expected)
        for cat in hazards.categories():
            if cat["in_codebook"]:
                self.assertTrue(cat["definition"].strip(), cat["key"])

    def test_the_two_project_categories_are_flagged_as_not_the_codebooks(self):
        for key in ("conflict_violence", "food_insecurity"):
            cat = next(c for c in hazards.categories() if c["key"] == key)
            self.assertFalse(cat["in_codebook"])
            self.assertIn("NOT an IFRC codebook category", cat["definition"])


class MappingTests(TestCase):
    def test_every_taxonomy_hazard_tag_is_mapped(self):
        """Add a hazard tag to taxonomy.json and forget this file, and the tag
        vanishes from the dashboard dropdown. This is where you find out."""
        taxonomy = json.loads(
            (settings.BASE_DIR / "data_pipeline" / "taxonomy.json").read_text("utf-8"))
        for tag in taxonomy["hazard"]:
            category, sub = hazards.for_tag(tag)
            self.assertIsNotNone(category, f"{tag} has no codebook category")
            self.assertIsNotNone(sub, f"{tag} has no sub-hazard")

    def test_every_observed_hip_code_is_mapped(self):
        observed = ["EN0205", "MH0600", "MH0103", "MH0301",
                    "MH0501", "MH0401", "GH0300", "GH0101"]
        for code in observed:
            category, sub = hazards.for_hip(code)
            self.assertNotEqual(category, "uncategorised", code)

    def test_wildfire_follows_the_codebook_not_the_undrr_slug(self):
        """nat-cli-wil-wil is climatological to UNDRR. The codebook names
        Wildfires under non-technological and man-made, and it wins."""
        self.assertEqual(hazards.for_hip("EN0205"), ("non_technological", "wildfires"))

    def test_extreme_heat_follows_the_codebook_not_the_undrr_slug(self):
        """nat-met-ext-hea is meteorological to UNDRR; the codebook files heat
        waves as climatological."""
        self.assertEqual(hazards.for_hip("MH0501"), ("climatological", "extreme_heat"))

    def test_the_two_storm_codes_sharing_a_slug_stay_distinct(self):
        """MH0103 and MH0301 both carry nat-met-sto-sto. Keying on the slug
        would merge thunderstorms with windstorms."""
        self.assertEqual(hazards.for_hip("MH0103"), ("meteorological", "thunderstorm"))
        self.assertEqual(hazards.for_hip("MH0301"), ("meteorological", "violent_wind"))

    def test_an_unknown_code_is_uncategorised_never_guessed(self):
        self.assertEqual(hazards.for_hip("ZZ9999"), ("uncategorised", "uncategorised"))

    def test_every_mapping_points_at_a_category_that_exists(self):
        keys = {c["key"] for c in hazards.categories()}
        subs = {s["key"] for c in hazards.categories() for s in c["sub_hazards"]}
        book = hazards.codebook()
        for table in ("hip_codes", "tags"):
            for name, entry in book[table].items():
                self.assertIn(entry["category"], keys, f"{table}/{name}")
                self.assertIn(entry["sub"], subs, f"{table}/{name}")


class HipExtractionTests(TestCase):
    def test_the_hip_code_is_picked_out_of_montandons_mixed_list(self):
        """Montandon sends three flavours in one list: HIP, GLIDE, UNDRR slug."""
        self.assertEqual(
            hazards.hip_from_codes(["EN0205", "WF", "nat-cli-wil-wil"]), "EN0205")
        self.assertEqual(
            hazards.hip_from_codes(["nat-hyd-flo-flo", "FL", "MH0600"]), "MH0600")

    def test_no_hip_code_present_returns_none(self):
        self.assertIsNone(hazards.hip_from_codes(["FL", "nat-hyd-flo-flo"]))
        self.assertIsNone(hazards.hip_from_codes([]))


class DetectionTests(TestCase):
    def test_a_green_gdacs_fire_with_no_impact_is_a_detection(self):
        self.assertTrue(hazards.is_detection("gdacs", "Green", 0))
        self.assertTrue(hazards.is_detection("gdacs", "Green", None))

    def test_a_green_gdacs_fire_that_affected_someone_is_an_event(self):
        self.assertFalse(hazards.is_detection("gdacs", "Green", 4200))

    def test_an_alerting_gdacs_event_is_an_event(self):
        self.assertFalse(hazards.is_detection("gdacs", "Orange", 0))

    def test_sources_with_no_rule_publish_events_only(self):
        """Only GDACS produces the problem, so only GDACS has a rule."""
        self.assertFalse(hazards.is_detection("pdc", "WATCH", 0))
        self.assertFalse(hazards.is_detection("idmc-idu", None, 0))
```

- [ ] **Step 4: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test external_data.tests.test_hazard_codebook -v 2
```

Expected: FAIL — `ModuleNotFoundError: No module named 'external_data.hazards'`.

- [ ] **Step 5: Write the reader module**

Create `external_data/hazards.py`:

```python
"""The hazard vocabulary, read once and answered from memory.

THE CODEBOOK IS A CLUSTERING METHOD, NOT A LIST TO RENDER. It supplies the
categories and the definitions that say what belongs in each; membership comes
from whatever Montandon and the document corpus actually hold. See
docs/superpowers/specs/2026-09-17-montandon-hazard-layer-design.md.

This module lives in external_data rather than data_pipeline because a fetcher
must not import the pipeline - fetchers/ipc.py says so where it parses
CRISIS_START out of settings for the same reason. The pipeline imports this way
round already (s06_mcp_layers imports external_data.models), so s03_parse and
s06 read the vocabulary from here.
"""
import functools
import json
import re

from django.conf import settings

# A HIP code is two letters and four digits: EN0205, MH0600, GH0101. Montandon
# sends it in a list beside a GLIDE two-letter code ("WF") and a UNDRR slug
# ("nat-cli-wil-wil"), in no fixed order, and the slug is missing about 38% of
# the time - so this pattern, not a position, is how the code is found.
_HIP = re.compile(r"^[A-Z]{2}\d{4}$")

UNCATEGORISED = ("uncategorised", "uncategorised")


@functools.lru_cache(maxsize=1)
def codebook():
    """The parsed file. Cached: it is read on every tag of every document."""
    return json.loads(settings.HAZARD_CODEBOOK.read_text(encoding="utf-8"))


def categories():
    """Every category, in display order. The dashboard's dropdown order."""
    return codebook()["categories"]


def for_hip(code):
    """(category, sub) for a HIP code. Unknown codes are never guessed at."""
    entry = codebook()["hip_codes"].get(code or "")
    return (entry["category"], entry["sub"]) if entry else UNCATEGORISED


def for_tag(tag):
    """(category, sub) for a document tag, or (None, None) if unmapped.

    None rather than 'uncategorised': an unmapped TAG is a bug in this file that
    test_every_taxonomy_hazard_tag_is_mapped exists to catch, whereas an
    unmapped HIP CODE is Montandon publishing something new, which is ordinary.
    """
    entry = codebook()["tags"].get(tag or "")
    return (entry["category"], entry["sub"]) if entry else (None, None)


def hip_from_codes(codes):
    """The HIP code out of Montandon's mixed list, or None."""
    return next((c for c in (codes or []) if _HIP.match(c)), None)


@functools.lru_cache(maxsize=None)
def sub_label(sub_key):
    """The human label for a sub-hazard key, or the key if it is unknown."""
    for cat in categories():
        for sub in cat["sub_hazards"]:
            if sub["key"] == sub_key:
                return sub["label"]
    return sub_key


def is_detection(collection, severity_label, max_impact):
    """Is this a machine observation with no evidence of consequence?

    385 of the first 500 events across the eight countries are GDACS satellite
    fire detections, Green with zero people potentially affected. Everything is
    stored - a real fire beside a displacement site must not be dropped with the
    noise - but a detection draws only under its own sub-hazard, never when a
    whole category is picked.

    Only GDACS is configured, because only GDACS produces the problem. A source
    with no rule publishes events only.
    """
    rule = codebook()["detection_rules"].get(collection)
    if not rule:
        return False
    if severity_label not in rule["no_alert_severity_labels"]:
        return False
    return not max_impact          # 0 and None both mean "nothing recorded"
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
docker compose exec web python manage.py test external_data.tests.test_hazard_codebook -v 2
```

Expected: PASS, 15 tests.

- [ ] **Step 7: Commit**

```bash
git add data_pipeline/hazard_codebook.json external_data/hazards.py \
        external_data/tests/test_hazard_codebook.py config/settings.py
git commit -m "feat: the IFRC hazard codebook as a clustering vocabulary

Nine categories - the codebook's seven plus Conflict and violence and Food
insecurity, both flagged as outside it - and the eight HIP codes Montandon
actually publishes for the countries of focus, each with a note saying why
it was placed there.

Keyed on the HIP code, not the UNDRR slug: the slug is absent on ~38% of
items, MH0103 and MH0301 share one, and where it is present it disagrees
with the codebook on wildfire and on extreme heat."
```

---

### Task 2: POST and token pagination in the fetch layer

**Files:**
- Modify: `external_data/fetchers/base.py`
- Modify: `external_data/fetchers/ipc.py` (use the shared `crisis_floor`)
- Modify: `external_data/management/commands/refresh_external.py`
- Test: `external_data/tests/test_fetcher_base.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `Call(url, params, cache_path, loader_dataset, context={}, narrowed=False, paginated=False, method="GET", body=None, headers={})`
  - `base.http_post_json(url, body, headers=None, timeout=60) -> dict`
  - `base.fetch_all_pages_token(url, body, headers=None) -> dict`
  - `base.fetch(call) -> dict`
  - `base.crisis_floor() -> datetime.date`

**Do not move `fetch_all_pages` out of `hdx.py`.** `test_fetcher_hdx.py` patches `external_data.fetchers.hdx.http_get_json` by name; moving the function breaks four passing tests for no gain. `base.fetch` imports it lazily, exactly as the runner does today.

- [ ] **Step 1: Write the failing test**

Append to `external_data/tests/test_fetcher_base.py`:

```python
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
        # server's, not ours to construct.
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
                   return_value={"got": True}) as g, \
             patch("external_data.fetchers.base.http_post_json",
                   return_value={"posted": True}) as p:
            self.assertEqual(base.fetch(get_call), {"got": True})
            self.assertEqual(base.fetch(post_call), {"posted": True})
        g.assert_called_once()
        p.assert_called_once()


class CrisisFloorTests(TestCase):
    @override_settings(CRISIS_START="2023-04-15")
    def test_the_window_floor_is_the_day_fighting_broke_out(self):
        self.assertEqual(base.crisis_floor(), date(2023, 4, 15))
```

Add to that file's imports: `from datetime import date`, `from pathlib import Path`, `from django.test import override_settings`, `from external_data.fetchers.base import Call`, and `from external_data.fetchers import base` if not already present.

- [ ] **Step 2: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test external_data.tests.test_fetcher_base -v 2
```

Expected: FAIL — `AttributeError: module 'external_data.fetchers.base' has no attribute 'http_post_json'`.

- [ ] **Step 3: Extend `fetchers/base.py`**

Add `IFRC_API_TOKEN` to the secrets tuple:

```python
SECRET_SETTINGS = ("IPC_API_KEY", "HDX_API_TOKEN", "IFRC_API_TOKEN")
```

Add three fields to `Call`, after `paginated`:

```python
    # GET with query params is what every fetcher before Montandon needed.
    # Montandon's country filter is a CQL2 expression, which only POST /search
    # accepts, so the verb is a property of the Call rather than of the runner.
    method: str = "GET"
    body: dict = None
    headers: dict = field(default_factory=dict)
```

Add the helpers below `http_get_json`:

```python
def http_post_json(url, body, headers=None, timeout=60):
    """POST a JSON body and decode, or raise FetchError with secrets removed."""
    try:
        response = requests.post(url, json=body, timeout=timeout,
                                 headers={"Accept": "application/json",
                                          "Content-Type": "application/json",
                                          **(headers or {})})
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise FetchError(redact(f"{url}: {exc}")) from None
    except ValueError as exc:
        raise FetchError(redact(f"{url}: response was not JSON ({exc})")) from None


def fetch_all_pages_token(url, body, headers=None):
    """Follow STAC's `token` to the end, and return one FeatureCollection.

    STAC does not page by offset the way HAPI does: the server hands back a
    complete next body, token included, in links[rel="next"]. It is sent back
    VERBATIM - constructing a token ourselves would be guessing at the server's
    cursor format, and it changes between implementations.

    The combined result has the shape the loader expects, as though it had been
    one call. Paging is a property of the API, not of the data.
    """
    features, next_body, pages = [], body, 0
    while True:
        page = http_post_json(url, next_body, headers)
        features.extend(page.get("features", []))
        pages += 1
        link = next((l for l in page.get("links", []) if l.get("rel") == "next"), None)
        if not link or not link.get("body") or pages >= MAX_PAGES:
            return {"type": "FeatureCollection", "features": features}
        next_body = link["body"]


def fetch(call):
    """Make one Call: GET or POST, paged or not. The runner's one door."""
    if call.method == "POST":
        return (fetch_all_pages_token(call.url, call.body, call.headers)
                if call.paginated else http_post_json(call.url, call.body, call.headers))
    if call.paginated:
        # Left in hdx.py on purpose: test_fetcher_hdx patches its http_get_json
        # by name, and moving the function would break four passing tests.
        from external_data.fetchers.hdx import fetch_all_pages
        return fetch_all_pages(call.url, call.params)
    return http_get_json(call.url, call.params)


def crisis_floor():
    """CRISIS_START as a date - the day fighting broke out in Khartoum.

    Defined in settings as a string and in data_pipeline.common as a date; a
    fetcher has no business importing the pipeline, so it parses the setting.
    Moved here from ipc.py, which now imports it, so there is one copy.
    """
    year, month, day = (int(part) for part in settings.CRISIS_START.split("-"))
    return date(year, month, day)
```

Add near `LOOKBACK_DAYS`:

```python
# A runaway `next` chain would page forever. Sudan's whole window is a few
# thousand events at 500 a page, so this is a guard rail and not a limit.
MAX_PAGES = 200
```

Add `from datetime import date, timedelta` to the imports (it currently imports `timedelta` only).

- [ ] **Step 4: Point `ipc.py` at the shared helper**

In `external_data/fetchers/ipc.py`, delete the local `_crisis_floor()` function and replace its import line:

```python
from external_data.fetchers.base import Call, Fetcher, crisis_floor, http_get_json
```

Then replace every `_crisis_floor()` call site with `crisis_floor()`.

- [ ] **Step 5: Point the runner at `base.fetch`**

In `external_data/management/commands/refresh_external.py`, replace:

```python
            if call.paginated:
                from external_data.fetchers.hdx import fetch_all_pages
                payload = fetch_all_pages(call.url, call.params)
            else:
                payload = base.http_get_json(call.url, call.params)
```

with:

```python
            # One door. GET or POST, paged or not, is the Call's business -
            # the runner's business is that they happen ONE AT A TIME.
            payload = base.fetch(call)
```

- [ ] **Step 6: Run the whole external_data suite**

```bash
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, including the four `test_fetcher_hdx` pagination tests and every `test_refresh_external` test, which patch `base.http_get_json` and must still work through `base.fetch`.

- [ ] **Step 7: Commit**

```bash
git add external_data/fetchers/base.py external_data/fetchers/ipc.py \
        external_data/management/commands/refresh_external.py \
        external_data/tests/test_fetcher_base.py
git commit -m "feat: let a Call be a POST, and page by token as well as offset

Montandon filters by country with a CQL2 expression, which only POST
/search accepts, and it pages by a token the server hands back inside
links[rel=next].body rather than by an offset. Both become properties of
the Call; the runner gets one door, base.fetch.

fetch_all_pages stays in hdx.py - test_fetcher_hdx patches its
http_get_json by name and moving it would break four passing tests.

_crisis_floor moves from ipc.py into base as crisis_floor, so the window
floor has one definition."
```

---

### Task 3: The two hazard tables

**Files:**
- Modify: `external_data/models.py`
- Create: `external_data/migrations/0014_hazard_events.py` (generated)
- Modify: `external_data/admin.py`
- Modify: `mcp/admin.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `external_data.models.HazardEvent`, `external_data.models.HazardImpact` with the fields below. Task 5, 6, 9 all read them.

- [ ] **Step 1: Add the models**

Append to `external_data/models.py`:

```python
class HazardEvent(models.Model):
    """One disaster event, as one Montandon source published it.

    SUBJECT-NAMED, LIKE ITS NEIGHBOURS. A hazard event is a hazard event whether
    GDACS, PDC or IDMC-IDU published it, so which one did is a column here.

    `source` IS ALWAYS 'montandon', AND THAT IS NOT COSMETIC. loaders/base.load()
    finishes by computing sync.row_count from the SYNC KEY's source. Writing
    'gdacs' here would make that count zero forever and the admin would report
    "0 rows" after every successful pull.

    THREE SOURCES PUBLISH THE SAME FLOOD. `corr_id` is what ties them together,
    and it also ties this row to its severity and its impacts, which arrive in
    separate calls. The dashboard draws one dot per corr_id; the table keeps all
    three, because which agencies saw an event is itself a finding.
    """

    source = models.TextField(default="montandon", help_text="Always 'montandon'. See above.")
    collection = models.TextField(
        db_index=True, help_text="gdacs / pdc / idmc-idu - which collection published it"
    )
    event_id = models.TextField(help_text="Montandon's STAC item id")
    corr_id = models.TextField(
        db_index=True, help_text="monty:corr_id - ties sources, severity and impacts together"
    )

    iso3 = models.CharField(max_length=3, db_index=True)
    event_date = models.DateField(db_index=True)
    end_date = models.DateField(null=True, blank=True)
    title = models.TextField(
        help_text="The item title, verbatim. Montandon writes the place into it, "
                  "in a shape that varies by source - admin_pcode is the checkable answer."
    )

    # The raw list as published - HIP code, GLIDE code and UNDRR slug together -
    # so the clustering below can be audited against what actually arrived.
    hazard_codes = models.JSONField(default=list, blank=True)
    hazard_category = models.TextField(
        db_index=True, default="uncategorised",
        help_text="An IFRC codebook category key, from hazard_codebook.json",
    )
    hazard_sub = models.TextField(default="uncategorised")

    # From the *-hazards item, applied by corr_id after the events load. Null for
    # every IDMC-IDU row: there is no idmc-idu-hazards collection.
    #
    # NEVER SORT OR COMPARE severity_value ACROSS COLLECTIONS. GDACS publishes
    # 0.5 on a "GDACS Severity Score" and PDC publishes 0.1 on a "PDC Severity
    # Score"; they are different scales meaning different things. The unit is
    # stored beside the number so nothing can show one without the other.
    severity_value = models.FloatField(null=True, blank=True)
    severity_unit = models.TextField(null=True, blank=True)
    severity_label = models.TextField(null=True, blank=True, help_text="Green / WATCH / …")
    severity_estimate_type = models.TextField(null=True, blank=True)

    significance = models.TextField(
        default="event", db_index=True,
        help_text="event / detection. A detection is a machine observation with no "
                  "evidence of consequence - it draws only under its own sub-hazard, "
                  "never when a whole category is picked. See hazards.is_detection.",
    )

    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    admin_pcode = models.TextField(null=True, blank=True)
    admin_level = models.IntegerField(null=True, blank=True)
    match_method = models.TextField(
        default="unmatched", help_text="point-in-polygon / unmatched"
    )
    source_url = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hazard_events"
        ordering = ["iso3", "-event_date", "collection"]
        constraints = [
            # iso3 IS IN THE KEY. One Montandon item can carry two countries - an
            # observed wildfire had ["ETH", "SDN"]. With iso3 outside, pulling
            # Chad after Sudan would silently rewrite Sudan's row.
            models.UniqueConstraint(
                fields=["collection", "event_id", "iso3"],
                name="uniq_hazard_event_identity",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["iso3", "hazard_category", "event_date"],
                         name="idx_hazard_country_cat"),
        ]

    def __str__(self):
        return f"{self.event_date} {self.iso3} {self.hazard_sub} - {self.title[:50]}"


class HazardImpact(models.Model):
    """One impact figure published against one hazard event.

    ONE ROW PER FIGURE, because Montandon publishes one item per (event, impact
    type): a flood has a displaced_internal item, an earthquake may have death
    and injured items.

    JOINED ON corr_id RATHER THAN BY FOREIGN KEY. Impacts and events are pulled
    in separate calls, and an impact whose event has not loaded is a fact worth
    keeping rather than an integrity error worth raising.
    """

    source = models.TextField(default="montandon")
    collection = models.TextField(db_index=True)
    impact_id = models.TextField()
    corr_id = models.TextField(db_index=True, help_text="Joins hazard_events.corr_id")
    iso3 = models.CharField(max_length=3, db_index=True)
    event_date = models.DateField(null=True, blank=True)

    impact_type = models.TextField(
        db_index=True, help_text="displaced_internal / death / potentially_affected / …"
    )
    category = models.TextField(null=True, blank=True, help_text="people / buildings / …")
    value = models.FloatField()
    unit = models.TextField(null=True, blank=True)
    estimate_type = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hazard_impacts"
        ordering = ["iso3", "-event_date", "impact_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "impact_id", "iso3"],
                name="uniq_hazard_impact_identity",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        return f"{self.corr_id} {self.impact_type} {self.value:,.0f}"
```

- [ ] **Step 2: Make and apply the migration**

```bash
docker compose exec web python manage.py makemigrations external_data -n hazard_events
docker compose exec web python manage.py migrate external_data
```

Expected: `0014_hazard_events.py` created, two tables added.

- [ ] **Step 3: Register them read-only in the admin**

In `external_data/admin.py`, add the two models to the import from `.models`, then append:

```python
@admin.register(HazardEvent)
class HazardEventAdmin(ReadOnly):
    # significance and match_method sit beside each other on purpose: a row that
    # is both 'detection' and 'unmatched' is a satellite fire pixel nobody can
    # place, and seeing the two together is how you spot what the map is missing.
    list_display = ("event_date", "iso3", "hazard_category", "hazard_sub",
                    "significance", "severity_label", "collection",
                    "match_method", "title")
    list_filter = ("iso3", "hazard_category", "hazard_sub", "collection",
                   "significance", "match_method")
    search_fields = ("title", "corr_id", "event_id", "admin_pcode")
    date_hierarchy = "event_date"


@admin.register(HazardImpact)
class HazardImpactAdmin(ReadOnly):
    list_display = ("event_date", "iso3", "impact_type", "value", "category",
                    "unit", "collection", "corr_id")
    list_filter = ("iso3", "impact_type", "category", "collection")
    search_fields = ("corr_id", "impact_id")
    date_hierarchy = "event_date"
```

- [ ] **Step 4: Label the source in the MCP admin**

In `mcp/admin.py`, add to `SOURCE_LABELS`:

```python
    "montandon": "IFRC Montandon",
```

- [ ] **Step 5: Restart web and check the admin renders**

```bash
docker compose restart web
```

Then open `/admin/external_data/hazardevent/` in a browser. Expected: an empty changelist with the filter sidebar, no error. **Gunicorn never autoreloads — without the restart the new admin registration is simply not served.**

- [ ] **Step 6: Commit**

```bash
git add external_data/models.py external_data/migrations/0014_hazard_events.py \
        external_data/admin.py mcp/admin.py
git commit -m "feat: hazard_events and hazard_impacts

source is always 'montandon' and the publisher goes in collection:
loaders/base.load() computes sync.row_count from the sync key's source, so
writing 'gdacs' into source would report 0 rows after every good pull.

iso3 is in both natural keys - one Montandon item can carry two countries,
and without it pulling Chad after Sudan rewrites Sudan's row.

Impacts join events on corr_id rather than by foreign key: they arrive in a
separate call, and an impact whose event has not loaded is a fact rather
than an integrity error."
```

---

### Task 4: The Montandon fetcher

**Files:**
- Modify: `config/settings.py`
- Modify: `env.example`
- Create: `external_data/fetchers/montandon.py`
- Modify: `external_data/fetchers/__init__.py`
- Test: `external_data/tests/test_fetcher_montandon.py`

**Interfaces:**
- Consumes: `base.Call(method=…, body=…, headers=…)`, `base.crisis_floor()` from Task 2.
- Produces: a registered fetcher at `fetcher_for("montandon", "hazard_events", "")`, whose `plan(sync)` yields exactly three Calls with `loader_dataset` values `"montandon_events"`, `"montandon_severity"`, `"montandon_impacts"` **in that order**. Tasks 5 and 6 register loaders under those dataset names.

- [ ] **Step 1: Add the settings**

In `config/settings.py`, beside `IPC_API_KEY`:

```python
# Montandon (IFRC's disaster-event registry). NOT an open API: a direct request
# to the staging host returns {"detail": "Not authenticated"}. The token is the
# same IFRC_API_TOKEN the `monty` MCP server uses, and it has to be copied into
# .env by hand. Production (montandon-eoapi.ifrc.org) answers 401 and wants GO
# OIDC credentials, so staging is the default until somebody holds them.
IFRC_API_TOKEN = os.environ.get("IFRC_API_TOKEN") or ""
MONTANDON_STAC_URL = (os.environ.get("MONTANDON_STAC_URL")
                      or "https://montandon-eoapi-stage.ifrc.org/stac")
```

In `env.example`, beside the other two keys:

```
# IFRC_API_TOKEN covers the montandon rows - IFRC's disaster-event registry.
# The same token the `monty` MCP server uses; copy it from your Docker MCP
# secret store. Without it the Pull now button reads "needs IFRC_API_TOKEN
# in .env" and nothing is called.
IFRC_API_TOKEN=
# Override only to point at a different Montandon deployment.
MONTANDON_STAC_URL=
```

- [ ] **Step 2: Write the failing test**

Create `external_data/tests/test_fetcher_montandon.py`:

```python
"""Montandon: the keyed source that POSTs, and whose window never narrows.

THE WINDOW IS FIXED, 15 Apr 2023 to today, on every pull. That is what the
office asked for, so since() is overridden to return None and `narrowed` is
always False - which means an empty answer is a fault rather than "nothing new",
exactly as loaders/base documents.
"""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from external_data.fetchers import fetcher_for
from external_data.fetchers.base import missing_keys
from external_data.models import SourceSync

STAC = "https://montandon-eoapi-stage.ifrc.org/stac"


class RegistrationTests(TestCase):
    def test_montandon_is_registered(self):
        self.assertIsNotNone(fetcher_for("montandon", "hazard_events", ""))

    @override_settings(IFRC_API_TOKEN="")
    def test_without_the_token_nothing_is_called(self):
        self.assertEqual(
            missing_keys(fetcher_for("montandon", "hazard_events", "")),
            ["IFRC_API_TOKEN"])


@override_settings(IFRC_API_TOKEN="TESTTOKEN", MONTANDON_STAC_URL=STAC,
                   CRISIS_START="2023-04-15")
class CallShapeTests(TestCase):
    def setUp(self):
        self.sync = SourceSync.objects.create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        self.calls = list(fetcher_for("montandon", "hazard_events", "")().plan(self.sync))

    def test_three_calls_events_then_severity_then_impacts(self):
        """Order is load-bearing: severity is applied onto rows that must
        already exist, and significance needs severity AND impacts."""
        self.assertEqual([c.loader_dataset for c in self.calls],
                         ["montandon_events", "montandon_severity", "montandon_impacts"])

    def test_every_call_is_a_paginated_post_to_search(self):
        for call in self.calls:
            self.assertEqual(call.url, f"{STAC}/search")
            self.assertEqual(call.method, "POST")
            self.assertTrue(call.paginated)

    def test_the_token_is_sent_as_a_header_not_a_query_parameter(self):
        for call in self.calls:
            self.assertIn("TESTTOKEN", call.headers["Authorization"])
            self.assertNotIn("TESTTOKEN", str(call.params))

    def test_the_window_starts_at_the_crisis_and_ends_today(self):
        for call in self.calls:
            start, end = call.body["datetime"].split("/")
            self.assertTrue(start.startswith("2023-04-15"))
            self.assertTrue(end.startswith(date.today().isoformat()))

    def test_the_filter_names_this_rows_country(self):
        for call in self.calls:
            self.assertEqual(call.body["filter"],
                             {"op": "a_contains",
                              "args": [{"property": "monty:country_codes"}, ["SDN"]]})

    def test_the_three_calls_name_the_three_collection_families(self):
        events, severity, impacts = self.calls
        self.assertEqual(events.body["collections"],
                         ["gdacs-events", "pdc-events", "idmc-idu-events"])
        self.assertEqual(severity.body["collections"], ["gdacs-hazards", "pdc-hazards"])
        self.assertEqual(impacts.body["collections"],
                         ["gdacs-impacts", "pdc-impacts", "idmc-idu-impacts"])

    def test_idmc_idu_hazards_is_never_requested_because_it_does_not_exist(self):
        self.assertNotIn("idmc-idu-hazards", self.calls[1].body["collections"])

    def test_the_html_description_is_excluded_from_every_call(self):
        """One item carries kilobytes of Word-exported HTML. Excluding it is
        what keeps a pull a sane size on disk and in mcp_cache/."""
        for call in self.calls:
            self.assertIn("properties.description", call.body["fields"]["exclude"])

    def test_each_call_caches_under_its_own_name(self):
        self.assertEqual(self.calls[0].cache_path,
                         Path("montandon/SDN-events.json"))
        self.assertEqual(self.calls[1].cache_path,
                         Path("montandon/SDN-hazards.json"))
        self.assertEqual(self.calls[2].cache_path,
                         Path("montandon/SDN-impacts.json"))


@override_settings(IFRC_API_TOKEN="TESTTOKEN", MONTANDON_STAC_URL=STAC,
                   CRISIS_START="2023-04-15")
class WindowNeverNarrowsTests(TestCase):
    def test_a_watermark_does_not_shorten_the_window(self):
        """The office asked for the whole window on every pull, so the
        inherited 90-day-lookback behaviour is deliberately switched off."""
        sync = SourceSync.objects.create(
            source="montandon", dataset="hazard_events", iso3="TCD", variant="",
            high_water_date=date(2026, 8, 1))
        calls = list(fetcher_for("montandon", "hazard_events", "")().plan(sync))
        for call in calls:
            self.assertFalse(call.narrowed)
            self.assertTrue(call.body["datetime"].startswith("2023-04-15"))
```

- [ ] **Step 3: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test external_data.tests.test_fetcher_montandon -v 2
```

Expected: FAIL — `AssertionError: unexpectedly None` on `test_montandon_is_registered`.

- [ ] **Step 4: Write the fetcher**

Create `external_data/fetchers/montandon.py`:

```python
"""IFRC Montandon -> hazard events, their severity and their impacts.

THREE CALLS PER COUNTRY, AND THE ORDER IS LOAD-BEARING:

    events    the what, where and when      -> hazard_events rows
    hazards   the severity                  -> applied onto those rows by corr_id
    impacts   the people                    -> hazard_impacts rows, then
                                               significance is classified

Severity has to land on rows that already exist, and `significance` needs both
severity and impacts to have arrived. plan() is a generator and the runner
consumes it with a plain for-loop, which is what makes the order safe.

NOT AN OPEN API. A direct request to the staging host returns
{"detail": "Not authenticated"}; it answers the `monty` MCP server only because
that server holds IFRC_API_TOKEN.

COUNTRY FILTERING NEEDS POST. GET /search offers bbox and nothing else, so the
country filter is a CQL2 expression and every call here is a POST.

`monty:country_codes` IS NOT TIGHT. A Sudan-filtered query returns
"Flood - Kemashi, Benshangul-Gumaz, Ethiopia", and the Egypt rows include
"Dense Fog - Negev, Israel". Those are kept: the filter is Montandon's own
judgement about which countries an event concerns, and overriding it here would
be this project second-guessing the registry. `title` carries the published
wording so a reader can see what happened.
"""
from datetime import date
from pathlib import Path

from django.conf import settings

from external_data.fetchers import register
from external_data.fetchers.base import Call, Fetcher, crisis_floor

# The three families. EM-DAT, GLIDE, IFRC-GO and DesInventar are deliberately
# absent: their geometry is the whole country, which would light Sudan entire
# and defeat the point of a layer whose job is to say WHERE.
EVENT_COLLECTIONS = ["gdacs-events", "pdc-events", "idmc-idu-events"]
# idmc-idu-hazards DOES NOT EXIST. Asking for it is a 404, and IDMC-IDU rows
# therefore carry no severity at all - which the popup handles by omitting it.
HAZARD_COLLECTIONS = ["gdacs-hazards", "pdc-hazards"]
IMPACT_COLLECTIONS = ["gdacs-impacts", "pdc-impacts", "idmc-idu-impacts"]

# Montandon's documented maximum for /search.
PAGE_SIZE = 500

# What every call needs regardless of kind. `geometry` is in because the point
# is the whole value of these three sources; `properties.description` is out
# because one item carries kilobytes of Word-exported HTML.
BASE_INCLUDE = ["id", "collection", "geometry", "bbox",
                "properties.title", "properties.datetime",
                "properties.start_datetime", "properties.end_datetime",
                "properties.monty:hazard_codes", "properties.monty:country_codes",
                "properties.monty:corr_id"]
BASE_EXCLUDE = ["properties.description", "assets", "properties.keywords",
                "stac_extensions"]


@register
class MontandonFetcher(Fetcher):
    """One press: events, then severity, then impacts, for one country."""

    source = "montandon"
    dataset = "hazard_events"
    variant = ""
    tool = "monty__search_items"
    requires = ("IFRC_API_TOKEN",)

    def since(self, sync):
        """None, always. The window is fixed and never narrows.

        The office asked for 15 Apr 2023 to today on every pull, so the
        inherited 90-day-lookback behaviour is switched off here. The
        consequence is deliberate: `narrowed` stays False, so under the loaders'
        "empty is a failure" guarantee a country that returns nothing fails
        loudly instead of being recorded as up to date.
        """
        return None

    def _window(self):
        return (f"{crisis_floor().isoformat()}T00:00:00Z"
                f"/{date.today().isoformat()}T23:59:59Z")

    def _headers(self):
        # A header, not a query parameter. HAPI's token travels in the URL and
        # base.redact() exists partly to scrub it out of exception messages;
        # a header keeps it out of the URL in the first place.
        return {"Authorization": f"Bearer {settings.IFRC_API_TOKEN}"}

    def _call(self, sync, collections, extra_include, kind, loader_dataset):
        return Call(
            url=f"{settings.MONTANDON_STAC_URL}/search",
            params={},
            body={
                "collections": collections,
                "datetime": self._window(),
                "limit": PAGE_SIZE,
                "filter": {"op": "a_contains",
                           "args": [{"property": "monty:country_codes"}, [sync.iso3]]},
                "filter-lang": "cql2-json",
                "fields": {"include": BASE_INCLUDE + extra_include,
                           "exclude": BASE_EXCLUDE},
            },
            headers=self._headers(),
            cache_path=Path("montandon") / f"{sync.iso3}-{kind}.json",
            loader_dataset=loader_dataset,
            context={"iso3": sync.iso3},
            method="POST",
            paginated=True,
            narrowed=False,
        )

    def plan(self, sync):
        yield self._call(sync, EVENT_COLLECTIONS, [], "events", "montandon_events")
        yield self._call(sync, HAZARD_COLLECTIONS, ["properties.monty:hazard_detail"],
                         "hazards", "montandon_severity")
        yield self._call(sync, IMPACT_COLLECTIONS, ["properties.monty:impact_detail"],
                         "impacts", "montandon_impacts")

    def params_record(self):
        return {"tool": self.tool, "window_start": crisis_floor().isoformat(),
                "window_end": "today", "collections": EVENT_COLLECTIONS,
                "paginated": True, "page_size": PAGE_SIZE}
```

- [ ] **Step 5: Register it**

In `external_data/fetchers/__init__.py`, change the bottom import to:

```python
from external_data.fetchers import fewsnet, hdx, ipc, montandon  # noqa: E402,F401
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
docker compose exec web python manage.py test external_data.tests.test_fetcher_montandon -v 2
```

Expected: PASS, 12 tests.

- [ ] **Step 7: Confirm the auth header shape against the real API**

This is the one thing the design could not settle from the desk. Put the token in `.env` first, then:

```bash
docker compose exec web python -c "
import os, requests
t = os.environ['IFRC_API_TOKEN']
u = 'https://montandon-eoapi-stage.ifrc.org/stac/collections'
for scheme in ('Bearer', 'Token'):
    r = requests.get(u, headers={'Authorization': f'{scheme} {t}'}, timeout=30)
    print(scheme, r.status_code)
"
```

Expected: one of the two prints `200`. If it is `Token` rather than `Bearer`, change the f-string in `_headers()` and the assertion in `test_the_token_is_sent_as_a_header_not_a_query_parameter` stays green either way. If **both** return 401, stop and report it — the token may be scoped to GO's own API rather than to Montandon, and that is a question for the office, not something to work around.

- [ ] **Step 8: Commit**

```bash
git add config/settings.py env.example external_data/fetchers/montandon.py \
        external_data/fetchers/__init__.py \
        external_data/tests/test_fetcher_montandon.py
git commit -m "feat: the Montandon fetcher - events, severity, impacts

Three POSTs per country in a load-bearing order: severity is applied onto
rows that must already exist, and significance needs severity and impacts
both. plan() is a generator and the runner is serial, which is what makes
the order safe.

since() returns None always. The office asked for 15 Apr 2023 to today on
every pull, so the inherited 90-day lookback is off and an empty answer
stays a fault rather than becoming 'nothing new'.

idmc-idu-hazards is never requested - it does not exist."
```

---

### Task 5: The loader hooks and the event loader

**Files:**
- Modify: `external_data/loaders/base.py`
- Create: `external_data/loaders/montandon.py`
- Modify: `external_data/loaders/__init__.py`
- Create: `external_data/tests/fixtures/montandon_events_sdn.json`
- Test: `external_data/tests/test_loader_montandon.py`

**Interfaces:**
- Consumes: `hazards.for_hip`, `hazards.hip_from_codes` (Task 1); `HazardEvent` (Task 3).
- Produces:
  - `Loader.after_insert(rows)` — optional hook, called inside `load()`'s transaction after `bulk_create` and the geometry pass.
  - `Loader.counts_rows = True` — class attribute; when `False`, `load()` leaves `sync.row_count` alone.
  - `MontandonEventLoader` registered under dataset `"montandon_events"`.

- [ ] **Step 1: Write the failing test**

Create `external_data/tests/fixtures/montandon_events_sdn.json` — a trimmed real payload, three features:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "id": "idmc-idu-event-80585",
      "collection": "idmc-idu-events",
      "geometry": {"type": "Point", "coordinates": [24.861231, 13.51387]},
      "properties": {
        "title": "Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026",
        "datetime": "2026-08-17T00:00:00Z",
        "start_datetime": "2026-08-17T00:00:00Z",
        "end_datetime": "2026-08-17T00:00:00Z",
        "monty:corr_id": "20260817-SDN-900001-MH0600-1-GCDB",
        "monty:hazard_codes": ["MH0600", "FL", "nat-hyd-flo-flo"],
        "monty:country_codes": ["SDN"]
      }
    },
    {
      "id": "gdacs-event-1027729",
      "collection": "gdacs-events",
      "geometry": {"type": "Point", "coordinates": [33.8278, 6.0834]},
      "properties": {
        "title": "Forest fires in Ethiopia, Sudan",
        "datetime": "2026-03-01T00:00:00Z",
        "start_datetime": "2026-03-01T00:00:00Z",
        "end_datetime": "2026-03-01T00:00:00Z",
        "monty:corr_id": "20260301-ETH-EN0205-1-GCDB",
        "monty:hazard_codes": ["EN0205", "WF", "nat-cli-wil-wil"],
        "monty:country_codes": ["ETH", "SDN"]
      }
    },
    {
      "id": "pdc-event-unknown-code",
      "collection": "pdc-events",
      "geometry": {"type": "Point", "coordinates": [32.5, 15.6]},
      "properties": {
        "title": "Something Montandon has not published before",
        "datetime": "2026-05-05T00:00:00Z",
        "start_datetime": "2026-05-05T00:00:00Z",
        "end_datetime": "2026-05-05T00:00:00Z",
        "monty:corr_id": "20260505-SDN-ZZ9999-1-GCDB",
        "monty:hazard_codes": ["ZZ9999", "XX"],
        "monty:country_codes": ["SDN"],
        "description": "<div>kilobytes of Word HTML</div>"
      }
    }
  ]
}
```

Create `external_data/tests/test_loader_montandon.py`:

```python
"""Montandon loaders: rows, clustering, the country trap, and where a point is.

The failure this file exists to prevent is the quiet one: an item carrying two
countries silently overwriting the first country's row on the second country's
pull.
"""
import json
from pathlib import Path

from django.test import TestCase

from external_data.loaders import LOADERS
from external_data.loaders.base import EmptyPayload, load
from external_data.models import HazardEvent, SourceSync

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
        self.assertEqual(result.high_water_date.isoformat(), "2026-08-17")

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
        # A square around the Tawila point, as an admin_areas row.
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("""
                INSERT INTO admin_areas (pcode, name, iso3, country_name, level,
                                         kind, name_alt, geom)
                VALUES ('SD-TEST-2', 'Tawila', 'SDN', 'Sudan', 2, 'admin', '[]',
                        ST_GeomFromText(
                          'POLYGON((24.5 13.2, 25.2 13.2, 25.2 13.8, 24.5 13.8,
                                    24.5 13.2))', 4326))
            """)

    def test_a_point_inside_a_polygon_resolves_to_its_pcode(self):
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
```

If `admin_areas` has columns beyond those listed, adjust the INSERT to supply them — run `docker compose exec web python manage.py dbshell -c "\d admin_areas"` to see the real shape before writing this test.

- [ ] **Step 2: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test external_data.tests.test_loader_montandon -v 2
```

Expected: FAIL — `KeyError: 'montandon_events'`.

- [ ] **Step 3: Add the two hooks to `loaders/base.py`**

Add to the `Loader` class, after `tool`:

```python
    # Whether load() should write sync.row_count from this loader's model.
    #
    # THREE LOADERS SHARE ONE SYNC ROW for Montandon - events, severity and
    # impacts - and load() overwrites row_count from its own model every time.
    # Without this flag the last loader to run would win and the freshness table
    # would report the impact count as the event count.
    counts_rows = True

    def after_insert(self, rows):
        """Optional: raw SQL that needs the rows to already exist.

        Called inside load()'s transaction, after bulk_create and after the
        geometry pass. This is where work belongs that parse() cannot do,
        because parse() is pure - resolving a point to a p-code, or applying a
        severity onto rows keyed by something other than the natural key.
        """
        return None
```

In `load()`, after the geometry block, add:

```python
    loader.after_insert(rows)
```

and guard the row-count write:

```python
    if loader.counts_rows:
        scope = {k: v for k, v in key.items() if k in ("source", "iso3")}
        sync.row_count = loader.model.objects.filter(**scope).count()
    sync.save()
```

Update the module docstring's list of guarantees to mention the hook.

- [ ] **Step 4: Write the event loader**

Create `external_data/loaders/montandon.py`:

```python
"""Montandon payloads -> hazard_events and hazard_impacts.

Three loaders, one sync row, and they run in the order the fetcher yields them:

    montandon_events    inserts the events, then places each point
    montandon_severity  does NOT insert - applies severity onto events by corr_id
    montandon_impacts   inserts the impacts, then classifies significance

Only the first counts rows. See Loader.counts_rows.
"""
import json
from datetime import datetime

from django.db import connection

from external_data import hazards
from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import HazardEvent

# gdacs-events -> gdacs. The collection family is what the row records; the
# suffix says which of the three calls it arrived in, which the row does not
# need because the three land in different tables and columns.
def _family(collection):
    for suffix in ("-events", "-hazards", "-impacts"):
        if collection.endswith(suffix):
            return collection[: -len(suffix)]
    return collection


def _date(value):
    """An ISO timestamp to a date, or None."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _point(geometry):
    """(lon, lat) from a STAC Point, or (None, None).

    All three chosen collections publish points; anything else is a source
    behaving unexpectedly and is left unplaced rather than guessed at.
    """
    if not geometry or geometry.get("type") != "Point":
        return None, None
    coords = geometry.get("coordinates") or []
    return (coords[0], coords[1]) if len(coords) >= 2 else (None, None)


@register
class MontandonEventLoader(Loader):
    """The events. One row per (item x focus country named on the item)."""

    dataset = "montandon_events"
    source = "montandon"
    model = HazardEvent
    unique_fields = ["collection", "event_id", "iso3"]
    update_fields = ["corr_id", "event_date", "end_date", "title", "hazard_codes",
                     "hazard_category", "hazard_sub", "lat", "lon", "source_url",
                     "source"]
    tool = "monty__search_items"

    def parse(self, payload, iso3, context=None):
        """Pure. No database access - see Loader.after_insert."""
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            # ONLY THIS COUNTRY. An item carrying ["ETH", "SDN"] becomes a row
            # under each, but only on that country's own pull - which is what
            # makes a per-country button honest.
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            lon, lat = _point(feature.get("geometry"))
            codes = props.get("monty:hazard_codes") or []
            category, sub = hazards.for_hip(hazards.hip_from_codes(codes))
            collection = _family(feature.get("collection", ""))
            rows.append({
                "source": "montandon",
                "collection": collection,
                "event_id": feature.get("id"),
                "corr_id": props.get("monty:corr_id") or "",
                "iso3": iso3,
                "event_date": _date(props.get("start_datetime")
                                    or props.get("datetime")),
                "end_date": _date(props.get("end_datetime")),
                "title": props.get("title") or "",
                "hazard_codes": codes,
                "hazard_category": category,
                "hazard_sub": sub,
                "lat": lat,
                "lon": lon,
                # Defaults the after_insert pass overwrites where it can.
                "admin_pcode": None,
                "admin_level": None,
                "match_method": "unmatched",
                "source_url": None,
            })
        return rows

    def high_water(self, rows):
        dates = [r["event_date"] for r in rows if r["event_date"]]
        return max(dates) if dates else None

    def after_insert(self, rows):
        """Place every point, deepest admin level first.

        ST_Contains against admin_areas, which already carries a GIST index on
        geom from boundaries/migrations/0002_geometry_columns.py. DISTINCT ON
        with ORDER BY level DESC is the same "finest first, most precise wins"
        rule build_theme_areas() applies - a locality beats the state holding it.
        """
        if not rows:
            return
        iso3 = rows[0]["iso3"]
        collections = sorted({r["collection"] for r in rows})
        with connection.cursor() as cur:
            cur.execute("""
                UPDATE hazard_events h
                   SET admin_pcode  = m.pcode,
                       admin_level  = m.level,
                       match_method = 'point-in-polygon'
                  FROM (SELECT DISTINCT ON (e.id) e.id AS event_id, a.pcode, a.level
                          FROM hazard_events e
                          JOIN admin_areas a
                            ON a.iso3 = e.iso3
                           AND ST_Contains(
                                 a.geom,
                                 ST_SetSRID(ST_MakePoint(e.lon, e.lat), 4326))
                         WHERE e.iso3 = %s
                           AND e.collection = ANY(%s)
                           AND e.lon IS NOT NULL
                         ORDER BY e.id, a.level DESC) m
                 WHERE h.id = m.event_id
            """, [iso3, collections])
```

- [ ] **Step 5: Register it**

In `external_data/loaders/__init__.py`, add `montandon` to the bottom import:

```python
from external_data.loaders import (acaps_seasonal, fewsnet_phases,  # noqa: E402,F401
                                   food_security, montandon, movement, seasonal)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
docker compose exec web python manage.py test external_data.tests.test_loader_montandon -v 2
docker compose exec web python manage.py test external_data -v 2
```

Expected: both PASS. The second confirms `counts_rows` did not disturb any existing loader.

- [ ] **Step 7: Commit**

```bash
git add external_data/loaders/base.py external_data/loaders/montandon.py \
        external_data/loaders/__init__.py \
        external_data/tests/test_loader_montandon.py \
        external_data/tests/fixtures/montandon_events_sdn.json
git commit -m "feat: the Montandon event loader, and two hooks it needs

parse() is documented pure, so placing a point is an after_insert pass -
the same shape as _write_geometry, keyed on the natural key, taking the
deepest matching admin level.

counts_rows exists because three loaders share one sync row: without it
the impact count would overwrite the event count in the freshness table.

An item carrying two countries becomes a row under each, on each
country's own pull - iso3 is in the natural key, so Chad's pull can no
longer rewrite Sudan's row."
```

---

### Task 6: Severity, impacts and significance

**Files:**
- Modify: `external_data/loaders/montandon.py`
- Create: `external_data/tests/fixtures/montandon_hazards_sdn.json`
- Create: `external_data/tests/fixtures/montandon_impacts_sdn.json`
- Modify: `external_data/tests/test_loader_montandon.py`

**Interfaces:**
- Consumes: `MontandonEventLoader` (Task 5), `hazards.is_detection` (Task 1), `HazardImpact` (Task 3).
- Produces: loaders registered under `"montandon_severity"` and `"montandon_impacts"`.

- [ ] **Step 1: Write the fixtures**

`external_data/tests/fixtures/montandon_hazards_sdn.json`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "id": "gdacs-hazard-1027729",
      "collection": "gdacs-hazards",
      "properties": {
        "title": "Forest fires in Ethiopia, Sudan",
        "monty:corr_id": "20260301-ETH-EN0205-1-GCDB",
        "monty:country_codes": ["ETH", "SDN"],
        "monty:hazard_detail": {
          "estimate_type": "primary",
          "severity_unit": "GDACS Severity Score",
          "severity_label": "Green",
          "severity_value": 0.5
        }
      }
    },
    {
      "id": "gdacs-hazard-orphan",
      "collection": "gdacs-hazards",
      "properties": {
        "title": "A severity whose event never loaded",
        "monty:corr_id": "20260101-SDN-NOSUCH-1-GCDB",
        "monty:country_codes": ["SDN"],
        "monty:hazard_detail": {
          "estimate_type": "primary",
          "severity_unit": "GDACS Severity Score",
          "severity_label": "Orange",
          "severity_value": 1.5
        }
      }
    }
  ]
}
```

`external_data/tests/fixtures/montandon_impacts_sdn.json`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "id": "idmc-idu-impact-80585-displaced",
      "collection": "idmc-idu-impacts",
      "properties": {
        "title": "Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026",
        "datetime": "2026-08-17T00:00:00Z",
        "monty:corr_id": "20260817-SDN-900001-MH0600-1-GCDB",
        "monty:country_codes": ["SDN"],
        "monty:impact_detail": {
          "type": "displaced_internal",
          "unit": "count",
          "value": 813,
          "category": "people",
          "estimate_type": "primary"
        }
      }
    },
    {
      "id": "gdacs-impact-1027729-wf",
      "collection": "gdacs-impacts",
      "properties": {
        "title": "Forest fires in Ethiopia, Sudan",
        "datetime": "2026-03-01T00:00:00Z",
        "monty:corr_id": "20260301-ETH-EN0205-1-GCDB",
        "monty:country_codes": ["ETH", "SDN"],
        "monty:impact_detail": {
          "type": "potentially_affected",
          "unit": "GDACS WF",
          "value": 0,
          "category": "people",
          "estimate_type": "primary"
        }
      }
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Append to `external_data/tests/test_loader_montandon.py`:

```python
from external_data.models import HazardImpact


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
```

- [ ] **Step 3: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test external_data.tests.test_loader_montandon -v 2
```

Expected: FAIL — `KeyError: 'montandon_severity'`.

- [ ] **Step 4: Write the two loaders**

Append to `external_data/loaders/montandon.py`:

```python
@register
class MontandonSeverityLoader(Loader):
    """The *-hazards items: severity, applied onto events that already exist.

    THIS LOADER INSERTS NOTHING. A hazard item has its own STAC id and is not an
    event; upserting them into hazard_events would double every row that has a
    severity. parse() returns the details as rows so the "empty is a failure"
    guarantee still catches a payload that came back broken, and after_insert
    does the real work with an UPDATE keyed on corr_id.
    """

    dataset = "montandon_severity"
    source = "montandon"
    model = HazardEvent
    unique_fields = ["collection", "event_id", "iso3"]
    update_fields = []
    tool = "monty__search_items"
    counts_rows = False

    def parse(self, payload, iso3, context=None):
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            detail = props.get("monty:hazard_detail") or {}
            corr_id = props.get("monty:corr_id")
            if not corr_id or not detail:
                continue
            rows.append({
                "corr_id": corr_id,
                "iso3": iso3,
                "severity_value": detail.get("severity_value"),
                "severity_unit": detail.get("severity_unit"),
                "severity_label": detail.get("severity_label"),
                "severity_estimate_type": detail.get("estimate_type"),
            })
        return rows

    def _insert_rows(self, rows):
        """Nothing is inserted. See the class docstring."""
        return []

    def after_insert(self, rows):
        if not rows:
            return
        with connection.cursor() as cur:
            for row in rows:
                cur.execute("""
                    UPDATE hazard_events
                       SET severity_value = %s, severity_unit = %s,
                           severity_label = %s, severity_estimate_type = %s
                     WHERE corr_id = %s AND iso3 = %s
                """, [row["severity_value"], row["severity_unit"],
                      row["severity_label"], row["severity_estimate_type"],
                      row["corr_id"], row["iso3"]])


@register
class MontandonImpactLoader(Loader):
    """The *-impacts items, then the significance classification.

    LAST OF THE THREE, AND THAT IS THE POINT. significance needs severity and
    impacts both, so it is classified here - after the fetcher's third call has
    landed. plan() yields events, hazards, impacts in that order and the runner
    consumes the generator serially, which is what makes this safe.
    """

    dataset = "montandon_impacts"
    source = "montandon"
    model = HazardImpact
    unique_fields = ["collection", "impact_id", "iso3"]
    update_fields = ["corr_id", "event_date", "impact_type", "category",
                     "value", "unit", "estimate_type", "source"]
    tool = "monty__search_items"
    counts_rows = False

    def parse(self, payload, iso3, context=None):
        rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            if iso3 not in (props.get("monty:country_codes") or []):
                continue
            detail = props.get("monty:impact_detail") or {}
            if not detail or detail.get("value") is None:
                continue
            rows.append({
                "source": "montandon",
                "collection": _family(feature.get("collection", "")),
                "impact_id": feature.get("id"),
                "corr_id": props.get("monty:corr_id") or "",
                "iso3": iso3,
                "event_date": _date(props.get("datetime")),
                "impact_type": detail.get("type") or "unspecified",
                "category": detail.get("category"),
                "value": detail.get("value"),
                "unit": detail.get("unit"),
                "estimate_type": detail.get("estimate_type"),
            })
        return rows

    def after_insert(self, rows):
        """Classify every event in this country as event or detection.

        Read back and written in Python rather than as one clever UPDATE: the
        rule lives in hazard_codebook.json - which severity labels mean "no
        alert", per collection - and keeping it there is the point. Baking it
        into SQL would put a fact about GDACS inside a statement about hazards.
        """
        if not rows:
            return
        iso3 = rows[0]["iso3"]
        biggest = {}
        for impact in HazardImpact.objects.filter(iso3=iso3).values(
                "corr_id", "value"):
            key = impact["corr_id"]
            biggest[key] = max(biggest.get(key, 0), impact["value"] or 0)

        detections, events = [], []
        for event in HazardEvent.objects.filter(iso3=iso3).values(
                "id", "collection", "severity_label", "corr_id"):
            bucket = (detections if hazards.is_detection(
                event["collection"], event["severity_label"],
                biggest.get(event["corr_id"])) else events)
            bucket.append(event["id"])

        if detections:
            HazardEvent.objects.filter(id__in=detections).update(significance="detection")
        if events:
            HazardEvent.objects.filter(id__in=events).update(significance="event")
```

Add `HazardImpact` to the model import at the top of the file.

- [ ] **Step 5: Teach `load()` to respect a loader that inserts nothing**

In `external_data/loaders/base.py`, replace the `bulk_create` block with:

```python
    # A loader that inserts nothing - MontandonSeverityLoader applies its
    # payload onto rows another loader already wrote - says so by overriding
    # _insert_rows. Everything else gets the ordinary upsert.
    objects = loader._insert_rows(rows)
    if objects:
        loader.model.objects.bulk_create(
            objects,
            update_conflicts=True,
            unique_fields=loader.unique_fields,
            update_fields=loader.update_fields,
        )
```

and add the default to `Loader`:

```python
    def _insert_rows(self, rows):
        """The model instances to upsert. Override to insert nothing."""
        return [self.model(**row) for row in rows]
```

Note the geometry pass must be skipped when nothing was inserted — guard it with `if objects and any(g is not None for g in geometries):`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
docker compose exec web python manage.py test external_data -v 2
```

Expected: PASS, whole app.

- [ ] **Step 7: Commit**

```bash
git add external_data/loaders/montandon.py external_data/loaders/base.py \
        external_data/tests/test_loader_montandon.py \
        external_data/tests/fixtures/montandon_hazards_sdn.json \
        external_data/tests/fixtures/montandon_impacts_sdn.json
git commit -m "feat: severity by corr_id, impacts, and the detection rule

The severity loader inserts nothing: a hazard item has its own STAC id and
is not an event, so upserting them would double every row that has one. It
applies four columns by corr_id instead.

significance is classified last, once severity and impacts have both
landed - which the fetcher's call order and the runner's serial loop are
what make safe. The rule itself stays in hazard_codebook.json: which
severity labels mean 'no alert' is a fact about GDACS, not about hazards."
```

---

### Task 7: Seed the eight countries and prove the button

**Files:**
- Create: `external_data/migrations/0015_seed_montandon_sources.py`
- Test: `external_data/tests/test_seed.py` (extend)

**Interfaces:**
- Consumes: the fetcher (Task 4) and loaders (Tasks 5–6).
- Produces: eight `source_sync` rows, and therefore eight **Pull now** buttons.

- [ ] **Step 1: Write the migration**

Create `external_data/migrations/0015_seed_montandon_sources.py`:

```python
"""One source_sync row per country of focus, so each gets its own button.

Eight rows rather than one regional row, because the office asked for the
countries of focus and because a per-country button is what the rest of this
page already offers. They also join the "pull everything out of date" batch for
free - views.stale_rows() picks up anything with a fetcher and a key.

The notes column is where a no-op refresh explains itself, and here it records
the thing a reader will otherwise wonder about: why the watermark never narrows
anything.
"""
from django.db import migrations

COUNTRIES = ["SDN", "TCD", "SSD", "EGY", "ETH", "LBY", "CAF", "UGA"]

NOTE = ("Window is fixed: 15 Apr 2023 to today, on every pull, as asked. "
        "high_water_date therefore never narrows the next request - see "
        "MontandonFetcher.since(). Three calls per press: events, severity, "
        "impacts.")


def seed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    for iso3 in COUNTRIES:
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3=iso3, variant="",
            defaults={"tool": "monty__search_items", "notes": NOTE},
        )


def unseed(apps, schema_editor):
    SourceSync = apps.get_model("external_data", "SourceSync")
    SourceSync.objects.filter(source="montandon", dataset="hazard_events").delete()


class Migration(migrations.Migration):
    dependencies = [("external_data", "0014_hazard_events")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 2: Write the failing test**

Append to `external_data/tests/test_seed.py`:

```python
class MontandonSourceRowTests(TestCase):
    """Eight rows, eight buttons - and every one of them pullable."""

    def test_one_row_per_country_of_focus(self):
        rows = SourceSync.objects.filter(source="montandon", dataset="hazard_events")
        self.assertEqual(
            sorted(rows.values_list("iso3", flat=True)),
            ["CAF", "EGY", "ETH", "LBY", "SDN", "SSD", "TCD", "UGA"])

    @override_settings(IFRC_API_TOKEN="TESTTOKEN")
    def test_every_row_has_a_fetcher_so_every_row_has_a_button(self):
        from mcp.views import pullable
        for row in SourceSync.objects.filter(source="montandon"):
            self.assertIsNone(pullable(row), row.iso3)

    @override_settings(IFRC_API_TOKEN="")
    def test_without_the_token_the_button_says_so_rather_than_calling(self):
        from mcp.views import pullable
        row = SourceSync.objects.filter(source="montandon").first()
        self.assertEqual(pullable(row), "IFRC_API_TOKEN is not set")

    def test_the_notes_explain_why_the_watermark_never_narrows(self):
        row = SourceSync.objects.filter(source="montandon").first()
        self.assertIn("never narrows", row.notes)
```

Add `from django.test import override_settings` if absent.

- [ ] **Step 3: Run it to make sure it fails, then migrate**

```bash
docker compose exec web python manage.py test external_data.tests.test_seed -v 2
docker compose exec web python manage.py migrate external_data
docker compose exec web python manage.py test external_data.tests.test_seed -v 2
```

Expected: FAIL, then PASS.

- [ ] **Step 4: Prove the command end to end with mocked HTTP**

Append to `external_data/tests/test_refresh_external.py`:

```python
class MontandonEndToEndTests(TestCase):
    """One press: three calls, three payloads saved, rows in three tables."""

    @override_settings(IFRC_API_TOKEN="TESTTOKEN")
    def test_refresh_external_montandon_loads_events_severity_and_impacts(self):
        from external_data.models import HazardEvent, HazardImpact
        SourceSync.objects.update_or_create(
            source="montandon", dataset="hazard_events", iso3="SDN", variant="")
        pages = [payload("montandon_events_sdn.json"),
                 payload("montandon_hazards_sdn.json"),
                 payload("montandon_impacts_sdn.json")]
        with patch("external_data.fetchers.base.http_post_json", side_effect=pages):
            call_command("refresh_external", "montandon", "hazard_events",
                         "--iso3", "SDN")
        self.assertEqual(HazardEvent.objects.count(), 3)
        self.assertEqual(HazardImpact.objects.count(), 2)
        self.assertEqual(
            HazardEvent.objects.get(event_id="gdacs-event-1027729").severity_label,
            "Green")
```

Add a `payload()` helper reading from `external_data/tests/fixtures/`, matching the one in `test_loader_montandon.py`.

- [ ] **Step 5: Run it, then do a real pull**

```bash
docker compose exec web python manage.py test external_data.tests.test_refresh_external -v 2
```

Expected: PASS.

Then, with the token in `.env` and after `docker compose restart web`, press **Pull now** on the Sudan row at `/admin/mcp/datasource/`. Expected: the job chip goes `running → succeeded`, three files appear under `data_pipeline/mcp_cache/montandon/`, and `/admin/external_data/hazardevent/?iso3=SDN` shows several hundred rows, most of them `wildfires` / `detection`.

- [ ] **Step 6: Commit**

```bash
git add external_data/migrations/0015_seed_montandon_sources.py \
        external_data/tests/test_seed.py external_data/tests/test_refresh_external.py
git commit -m "feat: eight Montandon source rows, one button per country

pull_button and pullable() both key off the fetcher registry with no
whitelist, so seeding the rows IS the button. They also join the 'pull
everything out of date' batch for free."
```

---

### Task 8: Stamp the codebook onto narrative tags

**Files:**
- Modify: `data_track/models.py`
- Create: `data_track/migrations/00NN_narrativetag_hazard_category.py` (generated)
- Modify: `data_pipeline/steps/s03_parse.py`
- Test: `data_pipeline/tests/test_hazard_export.py` (created here, extended in Task 9)

**Interfaces:**
- Consumes: `hazards.for_tag` (Task 1).
- Produces: `NarrativeTag.hazard_category`, `NarrativeTag.hazard_sub`.

- [ ] **Step 1: Add the columns**

In `data_track/models.py`, inside `NarrativeTag`, after `tag`:

```python
    # WHICH CODEBOOK CATEGORY THIS TAG BELONGS TO, stamped at parse time from
    # data_pipeline/hazard_codebook.json. Derived, never curated: s03_parse
    # deletes and rebuilds this whole table on every run, so anything typed in
    # by hand here would not survive the next pipeline pass.
    #
    # Null for the non-hazard dimensions - a need or a coping strategy has no
    # hazard category, and an empty string would read as one that is blank.
    hazard_category = models.TextField(
        null=True, blank=True, db_index=True,
        help_text="IFRC codebook category key. Null unless dimension='hazard'.",
    )
    hazard_sub = models.TextField(null=True, blank=True)
```

- [ ] **Step 2: Make and apply the migration**

```bash
docker compose exec web python manage.py makemigrations data_track -n narrativetag_hazard_category
docker compose exec web python manage.py migrate data_track
docker compose restart web
```

Both columns are nullable, so no backfill is needed and the `NotNullViolation` trap does not apply — but restart anyway, because Task 9 and 10 need the worker current.

- [ ] **Step 3: Write the failing test**

Create `data_pipeline/tests/test_hazard_export.py`:

```python
"""The codebook reaches the tag rows, and then the dashboard files."""
from datetime import date

from django.test import TestCase

from data_track.models import NarrativeTag


class TagStampingTests(TestCase):
    def test_a_hazard_tag_carries_its_codebook_category(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "flooding"),
                         {"hazard_category": "hydrological", "hazard_sub": "flooding"})

    def test_a_conflict_tag_lands_in_the_project_category(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("hazard", "armed_conflict"),
                         {"hazard_category": "conflict_violence",
                          "hazard_sub": "armed_conflict"})

    def test_a_need_has_no_hazard_category(self):
        """Null, not empty string - an empty string reads as a blank category."""
        from data_pipeline.steps.s03_parse import hazard_columns
        self.assertEqual(hazard_columns("need", "water_wash"),
                         {"hazard_category": None, "hazard_sub": None})

    def test_the_columns_survive_a_round_trip_through_the_table(self):
        from data_pipeline.steps.s03_parse import hazard_columns
        NarrativeTag.objects.create(
            dimension="hazard", tag="flooding", country="Sudan",
            report_date=date(2026, 8, 1), **hazard_columns("hazard", "flooding"))
        row = NarrativeTag.objects.get(tag="flooding")
        self.assertEqual(row.hazard_category, "hydrological")
```

- [ ] **Step 4: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test data_pipeline.tests.test_hazard_export -v 2
```

Expected: FAIL — `ImportError: cannot import name 'hazard_columns'`.

- [ ] **Step 5: Add the helper and call it**

In `data_pipeline/steps/s03_parse.py`, near the taxonomy-tagging section:

```python
from external_data import hazards


def hazard_columns(dimension, tag):
    """The two codebook columns for one tag row.

    Null for every dimension but hazard: a need has no hazard category, and an
    empty string would read as a blank one. Stamped here rather than curated in
    the table because this step deletes and rebuilds narrative_tags on every run.
    """
    if dimension != "hazard":
        return {"hazard_category": None, "hazard_sub": None}
    category, sub = hazards.for_tag(tag)
    return {"hazard_category": category, "hazard_sub": sub}
```

Then at every `add_tag(...)` call site, merge the columns in:

```python
        collector.add_tag(dimension=dimension, tag=tag, ...,
                          **hazard_columns(dimension, tag))
```

Find every call site with:

```bash
docker compose exec web grep -n "add_tag(" data_pipeline/steps/s03_parse.py
```

- [ ] **Step 6: Run the tests, then re-parse and check**

```bash
docker compose exec web python manage.py test data_pipeline.tests.test_hazard_export -v 2
docker compose exec web python manage.py run_pipeline --steps s03
docker compose exec web python manage.py shell -c "
from data_track.models import NarrativeTag as N
from collections import Counter
print(Counter(N.objects.filter(dimension='hazard').values_list('hazard_category', flat=True)))
print('unmapped:', N.objects.filter(dimension='hazard', hazard_category=None).count())
"
```

Expected: PASS; a category breakdown dominated by `conflict_violence`; **`unmapped: 0`**. Any non-zero count means a tag reached the corpus that `hazard_codebook.json` does not hold — add it to the file rather than to the pipeline.

(If the pipeline runner is not `run_pipeline --steps s03`, check `data_pipeline/management/commands/` for its real name and use that.)

- [ ] **Step 7: Commit**

```bash
git add data_track/models.py data_track/migrations/ \
        data_pipeline/steps/s03_parse.py data_pipeline/tests/test_hazard_export.py
git commit -m "feat: stamp the codebook category onto every hazard tag

Derived at parse time, never curated: s03_parse deletes and rebuilds
narrative_tags on every run, so a category typed into the table by hand
would not survive the next pass.

Null rather than empty string for the non-hazard dimensions - a need has
no hazard category, and an empty string reads as a blank one."
```

---

### Task 9: Export the vocabulary, the events, and the linked insights

**Files:**
- Modify: `data_pipeline/steps/s06_mcp_layers.py`
- Modify: `data_pipeline/tests/test_hazard_export.py`

**Interfaces:**
- Consumes: `HazardEvent`, `HazardImpact` (Task 3), `NarrativeTag.hazard_category` (Task 8), `hazards.categories/sub_label` (Task 1).
- Produces: `dashboard/data/hazards.json` and `dashboard/data/hazard_events.json` in the shapes below. Task 10 reads both.

**`hazards.json`**

```json
{"categories": [{"key": "hydrological", "label": "Hydrological hazards",
                 "in_codebook": true, "definition": "…",
                 "sub_hazards": [{"key": "floods", "label": "Floods",
                                  "definition": "…", "source": "codebook",
                                  "from": "montandon", "count": 12}]}]}
```

**`hazard_events.json`**

```json
{"by_sub": {"floods": {"monthly": [{"month": "2026-08", "country": "Sudan",
                                    "count": 3, "area": "SD16",
                                    "significance": "event"}]}},
 "events": {"SD16": {"2026-08": [
    {"date": "2026-08-17", "title": "Sudan: Flood - North Darfur (Tawila …)",
     "sub": "floods", "category": "hydrological", "significance": "event",
     "severity_label": null, "severity_unit": null,
     "impacts": [{"type": "displaced_internal", "value": 813, "unit": "count",
                  "category": "people", "source": "idmc-idu"}],
     "sources": ["idmc-idu"], "insight_ids": [4821]}]}}}
```

- [ ] **Step 1: Write the failing test**

Append to `data_pipeline/tests/test_hazard_export.py`:

```python
import json
from datetime import date

from django.conf import settings
from django.test import TestCase

from external_data.models import HazardEvent, HazardImpact
from insights.models import Insight, InsightCoding


def _read(name):
    return json.loads((settings.BASE_DIR / "dashboard" / "data" / name)
                      .read_text(encoding="utf-8"))


class HazardExportTests(TestCase):
    def setUp(self):
        self.flood = HazardEvent.objects.create(
            source="montandon", collection="idmc-idu",
            event_id="idmc-idu-event-80585",
            corr_id="20260817-SDN-900001-MH0600-1-GCDB", iso3="SDN",
            event_date=date(2026, 8, 17),
            title="Sudan: Flood - North Darfur (Tawila Locality) - 17/08/2026",
            hazard_codes=["MH0600"], hazard_category="hydrological",
            hazard_sub="floods", significance="event",
            lat=13.51, lon=24.86, admin_pcode="SD16", admin_level=2,
            match_method="point-in-polygon")
        HazardImpact.objects.create(
            source="montandon", collection="idmc-idu",
            impact_id="idmc-idu-impact-80585-displaced",
            corr_id=self.flood.corr_id, iso3="SDN", event_date=date(2026, 8, 17),
            impact_type="displaced_internal", category="people",
            value=813, unit="count")
        self.fire = HazardEvent.objects.create(
            source="montandon", collection="gdacs", event_id="gdacs-event-1",
            corr_id="20260301-SDN-EN0205-1-GCDB", iso3="SDN",
            event_date=date(2026, 3, 1), title="Forest fires in Sudan",
            hazard_codes=["EN0205"], hazard_category="non_technological",
            hazard_sub="wildfires", significance="detection",
            severity_label="Green", severity_unit="GDACS Severity Score",
            severity_value=0.5, lat=6.08, lon=33.82,
            admin_pcode="SD17", admin_level=2, match_method="point-in-polygon")

    def test_only_categories_present_in_the_data_are_offered(self):
        """The codebook is a clustering method, not a list to render. A Sahel
        operation must not be shown tsunamis."""
        from data_pipeline.steps.s06_mcp_layers import build_hazards
        build_hazards()
        keys = {c["key"] for c in _read("hazards.json")["categories"]}
        self.assertIn("hydrological", keys)
        self.assertIn("non_technological", keys)
        self.assertNotIn("technological", keys)

    def test_the_project_categories_are_marked_as_outside_the_codebook(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazards
        NarrativeTag.objects.create(dimension="hazard", tag="armed_conflict",
                                    country="Sudan", report_date=date(2026, 8, 1),
                                    hazard_category="conflict_violence",
                                    hazard_sub="armed_conflict")
        build_hazards()
        cat = next(c for c in _read("hazards.json")["categories"]
                   if c["key"] == "conflict_violence")
        self.assertFalse(cat["in_codebook"])

    def test_events_are_counted_by_sub_hazard_area_and_month(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        build_hazard_events()
        rows = _read("hazard_events.json")["by_sub"]["floods"]["monthly"]
        self.assertEqual(rows, [{"month": "2026-08", "country": "Sudan",
                                 "count": 1, "area": "SD16",
                                 "significance": "event"}])

    def test_the_detection_flag_travels_so_the_dashboard_can_hold_fires_back(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        build_hazard_events()
        rows = _read("hazard_events.json")["by_sub"]["wildfires"]["monthly"]
        self.assertEqual(rows[0]["significance"], "detection")

    def test_the_popup_entry_carries_severity_with_its_unit(self):
        """Never a bare number: GDACS 0.5 and PDC 0.1 are different scales."""
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD17"]["2026-03"][0]
        self.assertEqual(entry["severity_label"], "Green")
        self.assertEqual(entry["severity_unit"], "GDACS Severity Score")

    def test_the_popup_entry_carries_the_impact_figures(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["impacts"],
                         [{"type": "displaced_internal", "value": 813,
                           "unit": "count", "category": "people",
                           "source": "idmc-idu"}])

    def test_an_unmatched_event_is_not_exported_because_it_cannot_be_drawn(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        HazardEvent.objects.create(
            source="montandon", collection="pdc", event_id="pdc-nowhere",
            corr_id="x", iso3="SDN", event_date=date(2026, 7, 1),
            title="Somewhere in the desert", hazard_category="hydrological",
            hazard_sub="floods", match_method="unmatched", admin_pcode=None)
        build_hazard_events()
        total = sum(r["count"] for r in
                    _read("hazard_events.json")["by_sub"]["floods"]["monthly"])
        self.assertEqual(total, 1)

    def test_three_sources_reporting_one_flood_light_the_area_once(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        for collection in ("gdacs", "pdc"):
            HazardEvent.objects.create(
                source="montandon", collection=collection,
                event_id=f"{collection}-dup", corr_id=self.flood.corr_id,
                iso3="SDN", event_date=date(2026, 8, 17),
                title="Flood - Tawila", hazard_category="hydrological",
                hazard_sub="floods", significance="event",
                admin_pcode="SD16", admin_level=2, match_method="point-in-polygon")
        build_hazard_events()
        rows = _read("hazard_events.json")["by_sub"]["floods"]["monthly"]
        self.assertEqual(rows[0]["count"], 1)
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(sorted(entry["sources"]), ["gdacs", "idmc-idu", "pdc"])


class InsightLinkingTests(TestCase):
    """Some hazards have insights and many do not. Both are expected."""

    def setUp(self):
        self.flood = HazardEvent.objects.create(
            source="montandon", collection="idmc-idu", event_id="e1",
            corr_id="c1", iso3="SDN", event_date=date(2026, 8, 17),
            title="Sudan: Flood - North Darfur (Tawila Locality)",
            hazard_category="hydrological", hazard_sub="floods",
            significance="event", admin_pcode="SD16", admin_level=2,
            match_method="point-in-polygon")

    def _insight(self, pcode, on, tag="flooding", status="published"):
        ins = Insight.objects.create(
            quote="The water came through the night.", iso3="SDN",
            admin_pcode=pcode, admin_level=2, stated_on=on, status=status,
            quote_sha1=f"{pcode}{on}{tag}"[:40])
        InsightCoding.objects.create(insight=ins, dimension="hazard", tag=tag)
        return ins

    def test_a_same_place_same_month_same_hazard_insight_links(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        ins = self._insight("SD16", date(2026, 8, 20))
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [ins.id])

    def test_a_different_month_does_not_link(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        self._insight("SD16", date(2026, 5, 20))
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [])

    def test_a_different_hazard_category_does_not_link(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        self._insight("SD16", date(2026, 8, 20), tag="armed_conflict")
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [])

    def test_an_unpublished_insight_does_not_link(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        self._insight("SD16", date(2026, 8, 20), status="pending")
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [])

    def test_a_hazard_with_no_insight_at_all_is_still_exported(self):
        from data_pipeline.steps.s06_mcp_layers import build_hazard_events
        build_hazard_events()
        entry = _read("hazard_events.json")["events"]["SD16"]["2026-08"][0]
        self.assertEqual(entry["insight_ids"], [])
        self.assertEqual(entry["sub"], "floods")
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
docker compose exec web python manage.py test data_pipeline.tests.test_hazard_export -v 2
```

Expected: FAIL — `ImportError: cannot import name 'build_hazards'`.

- [ ] **Step 3: Write the two build steps**

Append to `data_pipeline/steps/s06_mcp_layers.py`:

```python
# ============================================================ hazards
def build_hazards():
    """The hazard vocabulary, filtered to what the data actually holds.

    THE CODEBOOK IS A CLUSTERING METHOD, NOT A LIST TO RENDER. Writing all
    sixteen of its named hazards out would offer a Sahel operation tsunamis and
    volcanic eruptions while hiding the convective storms that actually happen
    here. So the categories and definitions come from the file, and membership
    comes from the rows.
    """
    from data_track.models import NarrativeTag
    from external_data import hazards
    from external_data.models import HazardEvent

    montandon = Counter(HazardEvent.objects.exclude(admin_pcode=None)
                        .values_list("hazard_sub", flat=True))
    documents = Counter(NarrativeTag.objects.filter(dimension="hazard")
                        .exclude(hazard_sub=None)
                        .values_list("hazard_sub", flat=True))

    out = []
    for cat in hazards.categories():
        subs = []
        for sub in cat["sub_hazards"]:
            m, d = montandon.get(sub["key"], 0), documents.get(sub["key"], 0)
            if not (m or d):
                continue
            subs.append({**sub,
                         "from": "montandon" if m and not d
                                 else "documents" if d and not m else "both",
                         "count": m + d})
        if subs:
            out.append({"key": cat["key"], "label": cat["label"],
                        "in_codebook": cat["in_codebook"],
                        "definition": cat["definition"], "sub_hazards": subs})
    dump("hazards.json", {"categories": out})


def build_hazard_events():
    """Montandon events as counts per area and month, plus popup detail.

    NO GEOMETRY. The polygons come from boundaries/areas.geojson exactly as the
    document tags' do - this file only says which areas to light and what to say
    about them, in the same shape a tags.json entry has, so renderThemes() can
    union the two.

    DEDUPLICATED ON corr_id. Three sources publish the same flood; the area is
    lit once and the popup names all three. The representative row is the one
    from the most place-specific source, because "North Darfur (Tawila
    Locality)" beats "Forest fires in Sudan".
    """
    from external_data.models import HazardEvent, HazardImpact

    # The order of place-name specificity.
    PREFERENCE = {"idmc-idu": 0, "pdc": 1, "gdacs": 2}

    events = list(HazardEvent.objects.exclude(admin_pcode=None)
                  .exclude(admin_pcode="").order_by("event_date", "id"))
    if not events:
        print("    (no located hazard events - skipping)")
        dump("hazard_events.json", {"by_sub": {}, "events": {}})
        return

    impacts = defaultdict(list)
    for imp in HazardImpact.objects.all():
        impacts[imp.corr_id].append(
            {"type": imp.impact_type, "value": imp.value, "unit": imp.unit,
             "category": imp.category, "source": imp.collection})

    links = _insight_links(events)

    # One entry per (corr_id, area): the best row, and every source that saw it.
    best, sources = {}, defaultdict(set)
    for event in events:
        key = (event.corr_id or event.event_id, event.admin_pcode)
        sources[key].add(event.collection)
        current = best.get(key)
        if current is None or PREFERENCE.get(event.collection, 9) < \
                PREFERENCE.get(current.collection, 9):
            best[key] = event

    by_sub = defaultdict(lambda: defaultdict(int))
    detail = defaultdict(lambda: defaultdict(list))
    for key, event in best.items():
        month = event.event_date.strftime("%Y-%m")
        country = COUNTRY_NAMES.get(event.iso3, event.iso3)
        by_sub[event.hazard_sub][
            (month, country, event.admin_pcode, event.significance)] += 1
        detail[event.admin_pcode][month].append({
            "date": event.event_date.isoformat(),
            "title": event.title,
            "sub": event.hazard_sub,
            "category": event.hazard_category,
            "significance": event.significance,
            # ALWAYS WITH ITS UNIT. GDACS 0.5 and PDC 0.1 are different scales,
            # so a bare number here would invite a comparison that is meaningless.
            "severity_label": event.severity_label,
            "severity_unit": event.severity_unit,
            "impacts": impacts.get(event.corr_id, []),
            "sources": sorted(sources[key]),
            "insight_ids": links.get(event.id, []),
        })

    dump("hazard_events.json", {
        "by_sub": {sub: {"monthly": [
            {"month": m, "country": c, "count": n, "area": a, "significance": s}
            for (m, c, a, s), n in sorted(rows.items())]}
            for sub, rows in by_sub.items()},
        "events": {area: dict(months) for area, months in detail.items()},
    })


def _insight_links(events):
    """event id -> the published insights that speak to it.

    THREE CONDITIONS, ALL OF THEM. Same hazard category, same place, same month.
    A country-level insight does not link to every event in the country, and an
    insight about shelling does not link to a flood.

    MANY EVENTS LINK TO NOTHING, and that is the design rather than a gap: the
    hazards are the spine and the insights attach where they exist.

    This READS the insights app and never writes to it. No pipeline step writes
    to that app, deliberately, and this one does not change that.
    """
    from insights.models import Insight

    coded = defaultdict(list)     # (category, pcode, month) -> [insight id]
    rows = (Insight.objects.filter(status="published")
            .exclude(admin_pcode=None).exclude(stated_on=None)
            .values("id", "admin_pcode", "stated_on", "codings__dimension",
                    "codings__tag"))
    for row in rows:
        if row["codings__dimension"] != "hazard":
            continue
        category, _sub = hazards_for_tag(row["codings__tag"])
        if not category:
            continue
        key = (category, row["admin_pcode"], row["stated_on"].strftime("%Y-%m"))
        if row["id"] not in coded[key]:
            coded[key].append(row["id"])

    out = {}
    for event in events:
        key = (event.hazard_category, event.admin_pcode,
               event.event_date.strftime("%Y-%m"))
        out[event.id] = sorted(coded.get(key, []))
    return out
```

At the top of `s06_mcp_layers.py`, add to the imports:

```python
from collections import Counter, defaultdict

from external_data.hazards import for_tag as hazards_for_tag
```

and reuse the existing `COUNTRY_NAMES` map if `s06` has one; if it does not, import it:

```python
from data_pipeline.management.commands.build_map_context import COUNTRY_NAMES
```

(Check first with `grep -n "COUNTRY_NAMES" data_pipeline/steps/s06_mcp_layers.py`. If neither exists, define it locally from the eight focus ISO3 codes.)

- [ ] **Step 4: Widen the theme areas and wire the steps in**

In `build_theme_areas()`, replace the p-code query with the union:

```python
    from data_track.models import NarrativeTag
    from external_data.models import HazardEvent

    # THE UNION, not just the tags: a locality that only Montandon knows about
    # still needs a polygon built for it, or its events light nothing.
    pcodes = sorted(
        set(NarrativeTag.objects.exclude(area_id=None).exclude(area_id="")
            .values_list("area_id", flat=True))
        | set(HazardEvent.objects.exclude(admin_pcode=None).exclude(admin_pcode="")
              .values_list("admin_pcode", flat=True)))
```

In `run()`, add the two steps before `build_theme_areas()`:

```python
    build_hazards()
    build_hazard_events()
    build_theme_areas()
```

- [ ] **Step 5: Run the tests and then the real build**

```bash
docker compose exec web python manage.py test data_pipeline.tests.test_hazard_export -v 2
docker compose exec web python manage.py run_rebuild
```

Expected: PASS; the rebuild prints `hazards.json` and `hazard_events.json` with non-zero sizes.

- [ ] **Step 6: Commit**

```bash
git add data_pipeline/steps/s06_mcp_layers.py data_pipeline/tests/test_hazard_export.py
git commit -m "feat: export the hazard vocabulary, the events and their insights

hazards.json holds only the categories the data actually has - writing the
whole codebook out would offer a Sahel operation tsunamis while hiding the
convective storms that happen here.

hazard_events.json carries no geometry: the polygons are the ones
areas.geojson already holds, and by_sub has the same shape as a tags.json
entry so renderThemes can union the two. Deduplicated on corr_id, so three
reports of one flood light an area once and the popup names all three.

Insights link on shared category, place and month. Many events link to
none, which is the design."
```

---

### Task 10: The two dropdowns and the popup

**Files:**
- Modify: `dashboard/static/dashboard/js/app.js`
- Modify: `dashboard/templates/dashboard/index.html` (data file preload, if the others are listed there)

**Interfaces:**
- Consumes: `dashboard/data/hazards.json`, `dashboard/data/hazard_events.json` (Task 9).
- Produces: the visible feature.

**This file is large — use a scratchpad patch script rather than a heredoc.** Write the new functions to a file under the scratchpad directory and apply them with a small Python script; heredocs break on payloads this size.

- [ ] **Step 1: Load the two new data files**

Find where `tags.json` is fetched (`grep -n "tags.json" dashboard/static/dashboard/js/app.js`) and add `hazards.json` and `hazard_events.json` to the same batch, as `state.data.hazards` and `state.data.hazardEvents`. Both must tolerate being absent — a dashboard built before this change has neither, and the page must still render.

- [ ] **Step 2: Build the two dropdowns**

In `initThemeControls()`, special-case the hazard dimension:

```js
/* THE HAZARD DIMENSION GETS TWO DROPDOWNS, not one: a category picked from the
   IFRC codebook, then a sub-hazard within it. Both lists come from
   hazards.json, which the pipeline writes from what the data actually holds -
   so a category with nothing behind it never appears.

   Both resolve DOWN into state.activeTags as "hazard|<tag>" keys, which is what
   lets Trends, Top reported hazards and Community Insights keep working
   through the machinery they already use, untouched. */
function buildHazardDropdowns(wrap, meta) {
  const book = state.data.hazards;
  if (!book || !book.categories.length) return false;

  const subsOf = (catKey) =>
    (book.categories.find((c) => c.key === catKey) || {}).sub_hazards || [];
  const visibleSubs = () => {
    const cats = state.activeHazards.size
      ? book.categories.filter((c) => state.activeHazards.has(c.key))
      : book.categories;
    return cats.flatMap((c) => c.sub_hazards.map((s) => ({ ...s, cat: c.key })));
  };

  /* One flat set of tag keys is what every existing panel reads, so the two
     new sets are resolved into it on every change rather than being consulted
     separately. A sub-hazard with no document tag - wildfires, earthquake -
     resolves to nothing here and filters the event feed only. */
  function resolveTags() {
    for (const key of [...state.activeTags])
      if (key.startsWith("hazard|")) state.activeTags.delete(key);
    for (const sub of visibleSubs()) {
      const on = state.activeSubHazards.size
        ? state.activeSubHazards.has(sub.key)
        : state.activeHazards.has(sub.cat);
      if (on && sub.source === "documents") state.activeTags.add(`hazard|${sub.key}`);
    }
  }

  const redraw = () => {
    resolveTags();
    subDropdown.setOptions(visibleSubs().map((s) => ({
      value: s.key,
      label: s.in_codebook === false ? s.label : s.label,
      color: meta.color,
    })));
    applyFilters({ refit: false });
    if (state.activeTags.size || state.activeSubHazards.size)
      loadAreas().then(renderMapLayers);
  };

  const catDropdown = makeDropdown({
    label: "Hazard",
    color: meta.color,
    options: book.categories.map((c) => ({
      value: c.key,
      label: c.in_codebook ? c.label : `${c.label} *`,
      color: meta.color,
    })),
    selected: setView(state.activeHazards),
    placeholder: "Search hazard categories…",
    onChange: () => {
      // A category deselected must not leave its sub-hazards ticked.
      for (const key of [...state.activeSubHazards]) {
        const owner = book.categories.find(
          (c) => c.sub_hazards.some((s) => s.key === key));
        if (owner && state.activeHazards.size && !state.activeHazards.has(owner.key))
          state.activeSubHazards.delete(key);
      }
      redraw();
    },
  });

  const subDropdown = makeDropdown({
    label: "Sub-Hazard",
    color: meta.color,
    options: visibleSubs().map((s) => ({ value: s.key, label: s.label,
                                         color: meta.color })),
    selected: setView(state.activeSubHazards),
    placeholder: "Search sub-hazards…",
    onChange: redraw,
  });

  wrap.appendChild(catDropdown.el);
  wrap.appendChild(subDropdown.el);
  return true;
}

/* The small view makeDropdown expects, over a plain Set. */
function setView(set) {
  return {
    has: (v) => set.has(v),
    add: (v) => set.add(v),
    delete: (v) => set.delete(v),
    clear: () => set.clear(),
    get size() { return set.size; },
  };
}
```

`makeDropdown` has no `setOptions` today. Add one: store `options` in a closure variable, and have `setOptions(next)` reassign it and call the existing `paint()`.

Declare the two sets beside `state.activeTags`:

```js
  activeHazards: new Set(),
  activeSubHazards: new Set(),
```

And in `initThemeControls()`'s loop:

```js
    if (dim === "hazard" && buildHazardDropdowns(wrap, meta)) continue;
```

Add a one-line note under the panel heading explaining the asterisk: *"\* not an IFRC codebook category"*.

- [ ] **Step 3: Union the Montandon feed into `renderThemes()`**

Immediately after the existing `for (const key of state.activeTags)` loop in `renderThemes()`:

```js
  /* MONTANDON EVENTS LIGHT THE SAME POLYGONS. Added into byArea so the fill
     works exactly as it does for document tags, and into a SEPARATE
     detail[area].hazardEvents list so the popup can tell the two kinds of
     evidence apart.

     Deliberately NOT merged into state.data.tags.hazard: monthTagTotals reads
     that object, and Top reported hazards would then show 407 GDACS fire
     pixels beside document mentions. */
  const feed = (state.data.hazardEvents || {}).by_sub || {};
  for (const [sub, subData] of Object.entries(feed)) {
    const cat = hazardCategoryOf(sub);
    const bySub = state.activeSubHazards.size;
    // A detection - a Green GDACS fire affecting nobody - draws ONLY when its
    // sub-hazard is picked by name, never when a whole category is picked.
    const picked = bySub ? state.activeSubHazards.has(sub)
                         : state.activeHazards.has(cat);
    if (!picked) continue;
    for (const row of subData.monthly) {
      if (row.month !== mk || !countryOnStrict(row.country)) continue;
      if (row.significance === "detection" && !bySub) continue;
      if (!row.area) continue;
      (byArea[row.area] = byArea[row.area] || {}).hazard =
        (byArea[row.area].hazard || 0) + row.count;
      const d = (detail[row.area] = detail[row.area] || {});
      d.hazardEvents = (d.hazardEvents || []).concat(
        ((state.data.hazardEvents.events[row.area] || {})[mk] || [])
          .filter((e) => e.sub === sub));
    }
  }
```

with the helper:

```js
/* Which codebook category holds this sub-hazard. */
function hazardCategoryOf(sub) {
  for (const c of ((state.data.hazards || {}).categories || []))
    if (c.sub_hazards.some((s) => s.key === sub)) return c.key;
  return null;
}
```

- [ ] **Step 4: Extend the area popup**

Find the function that renders `state.areaDetail` into the popup HTML and append a Montandon section:

```js
/* What Montandon says about this area, this month. Nothing is invented to
   fill a gap: an IDMC-IDU flood has displacement and no severity, a GDACS
   fire has severity and no displacement, and an empty section is absent
   rather than shown as "unknown".

   SEVERITY IS ALWAYS SHOWN WITH ITS UNIT. GDACS 0.5 "Green" and PDC 0.1
   "WATCH" are different scales; a bare number invites a comparison that
   means nothing. */
function hazardEventsHtml(events) {
  if (!events || !events.length) return "";
  const rows = events.map((e) => {
    const bits = [`<b>${sentence(e.sub)}</b> — ${fmtDate(Date.parse(e.date))}`];
    if (e.severity_label)
      bits.push(`severity ${e.severity_label} (${e.severity_unit})`);
    for (const i of e.impacts || [])
      bits.push(`${i.value.toLocaleString()} ${i.category || ""} ` +
                `${sentence(i.type)} (${i.source})`);
    bits.push(`reported by ${e.sources.join(", ")}`);
    if (e.significance === "detection")
      bits.push(`<i>automated detection, no recorded impact</i>`);
    if (e.insight_ids && e.insight_ids.length)
      bits.push(`${e.insight_ids.length} linked community insight` +
                `${e.insight_ids.length === 1 ? "" : "s"}`);
    return `<div class="haz-ev">${bits.join("<br>")}</div>`;
  });
  return `<div class="haz-events"><h4>Recorded hazard events</h4>${rows.join("")}</div>`;
}
```

Call it from the popup builder with `detail[areaId].hazardEvents`, and add `sentence()` if the file has no such helper (`s => s.replace(/_/g, " ")`).

- [ ] **Step 5: Restart, rebuild and look at it**

```bash
docker compose restart web
docker compose exec web python manage.py run_rebuild
```

Then in a real browser (not headless — per the project's own verification notes):

1. The themes panel shows **Hazard** and **Sub-Hazard** where one dropdown used to be.
2. Hazard lists only categories with data; *Conflict and violence* and *Food insecurity and famine* carry the asterisk.
3. Picking **Hydrological hazards** lights flood areas from both the documents and Montandon; **Top reported hazards** on the right shows document tags only and no wildfire count.
4. Picking **Non-technological and man-made** lights few or no areas — the Green fire detections are held back.
5. Picking the **Wildfires** sub-hazard by name lights them.
6. Clicking a lit area shows *Recorded hazard events* with a date, a severity-with-unit or a displacement figure, and the reporting sources.
7. With nothing selected, the map is exactly as it was before this change.

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/dashboard/js/app.js dashboard/templates/dashboard/index.html
git commit -m "feat: Hazard and Sub-Hazard, over documents and Montandon alike

Both dropdowns resolve down into state.activeTags, so Trends, Top reported
hazards and Community Insights keep working unchanged - the only new code
paths are the second dropdown, one loop in renderThemes and a popup
section.

The Montandon feed is deliberately NOT merged into state.data.tags.hazard:
monthTagTotals reads that object, and Top hazards would then show 407 GDACS
fire pixels beside things people actually wrote down.

A detection draws only when its sub-hazard is picked by name, so choosing a
category shows hazards that mattered."
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the vocabulary and its two project categories → Task 1; POST, token pagination and the fixed window → Tasks 2 and 4; `HazardEvent`, `HazardImpact`, the `source`/`collection` split and the three-part natural key → Task 3; auth and the three calls → Task 4; the pure-`parse()` rule, `after_insert`, `counts_rows` and p-code resolution → Tasks 5 and 6; severity-by-`corr_id` and the detection rule → Task 6; the eight buttons → Task 7; `NarrativeTag` stamping → Task 8; both dashboard files, `corr_id` dedupe, insight linking and the widened theme areas → Task 9; the two dropdowns, the `renderThemes` union and the popup → Task 10. Every row of the spec's error-handling table has a test in Task 1, 5, 6 or 9.

**Known soft spots**, flagged rather than hidden:
- **Task 4 Step 7** cannot be settled from the desk: the `Bearer` vs `Token` header shape needs one real call. Both outcomes are handled; a double-401 is a stop-and-report.
- **Task 5's `PointResolutionTests`** inserts an `admin_areas` row by raw SQL. Check the real column list with `\d admin_areas` before writing it.
- **Task 9** assumes `COUNTRY_NAMES` and a pipeline command name (`run_rebuild`); both are named with a `grep` to run first.
- **Task 10** describes `makeDropdown` gaining a `setOptions`, which it does not have today. That addition is part of the task.

**Type consistency.** `loader_dataset` strings (`montandon_events` / `montandon_severity` / `montandon_impacts`) match between Task 4's fetcher and Tasks 5–6's `register`ed loaders. `hazards.for_hip` returns a 2-tuple everywhere it is used. `significance` is `"event"` / `"detection"` in the model default, the loader, the export and the JS. `match_method` is `"point-in-polygon"` / `"unmatched"` in all four places.
