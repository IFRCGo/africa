"""The ACAPS event -> season_type mapping, which decides the calendar's colour.

THE BUG THIS PINS DOWN. ACAPS files "Main wet/ Rainy/ Monsoon season" and
"Dry season" under the event_type "Seasonal hazard" - its taxonomy separates
"things the climate does" from "things people plant", and a rainy season lands
on the hazard side of that line. Keying the season type on event_type alone
therefore typed every rainy and dry season as a hazard, and the strip drew
Sudan's rainy season in the same red as Floods, Locusts and Malaria.

A rainy season is not a hazard. It is the single most predictable feature of the
agricultural year, and colouring it as a warning inverts what the calendar is
for. The mapping now reads the EVENT first and falls back to the event_type.
"""
from django.test import SimpleTestCase

from external_data.loaders.acaps_seasonal import _season_type, parse_records


class SeasonTypeMapping(SimpleTestCase):
    def test_climate_seasons_are_not_hazards(self):
        """The six rows that were wrong, and the reason this test exists."""
        for event, event_type in [
            ("Main wet/ Rainy/ Monsoon season", "Seasonal hazard"),
            ("2nd wet/ Rainy/ Monsoon season", "Seasonal hazard"),
        ]:
            self.assertEqual(_season_type(event, event_type), "Rainy", event)
        self.assertEqual(_season_type("Dry season", "Seasonal hazard"), "Dry")

    def test_real_hazards_stay_hazards(self):
        """Fixing the above must not empty the hazard band of its real members."""
        for event in ["Floods", "Locust/ Armyworm (caterpillar)", "Sandstorms season"]:
            self.assertEqual(_season_type(event, "Seasonal hazard"), "Hazard", event)
        self.assertEqual(_season_type("Malaria", "Outbreak"), "Hazard")

    def test_the_agricultural_cycle_splits_from_the_harvest(self):
        """Planting and harvest are different stages and are colour-coded apart."""
        for event in ["1st/main planting", "2nd planting", "Land preparation"]:
            self.assertEqual(_season_type(event, "Planting and growing"), "Planting", event)
        for event in ["1st/main harvest", "2nd harvest", "Green harvest"]:
            self.assertEqual(_season_type(event, "Harvest"), "Harvest", event)

    def test_lean_and_livestock(self):
        self.assertEqual(_season_type("Lean season", "Lean season"), "Lean")
        self.assertEqual(_season_type("Livestock migration", "Livestock"), "Livestock")

    def test_an_unknown_category_is_not_silently_called_dry(self):
        """The default was "Dry", which is how a rainy season became a hazard.

        A category ACAPS adds later must land somewhere visibly unclassified
        rather than being quietly filed under a real season, where nobody would
        ever notice it was wrong.
        """
        self.assertEqual(_season_type("Wildfire risk", "Something ACAPS added"), "Other")
        self.assertEqual(_season_type("", ""), "Other")


class ParseAssignsTheType(SimpleTestCase):
    """The mapping has to survive the parser, not just exist beside it."""

    def test_a_rainy_season_row_parses_as_rainy(self):
        rows = parse_records([{
            "id": "1", "iso": "['SDN']", "country": "['Sudan']",
            "event": "['Main wet/ Rainy/ Monsoon season']",
            "event_type": "['Seasonal hazard']", "label": "['Rainy season']",
            "months": "['June', 'July', 'August', 'September']",
            "country_wide": "True", "comment": "The main rains.",
        }])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["season_type"], "Rainy")
        self.assertEqual(rows[0]["months"], [6, 7, 8, 9])
