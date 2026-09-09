"""Deciding WHERE a sentence in a report is about.

About a third of the tagged sentences in the corpus name a place. This turns
that name into a p-code from the boundary library, so the map can highlight the
actual polygon. The other two thirds genuinely say nothing more specific than
the country ("shelter needs remain acute across Chad") and are left with no
area rather than guessed at.

WHY THIS IS NO LONGER A SINGLE REGULAR EXPRESSION
The old matcher built one alternation of every known place name and ran it over
every sentence. That was fine for 336 names. The library now holds 10,844
polygons, and Python's `re` does not optimise a 30,000-branch alternation - it
tries them in turn. Re-parsing the corpus that way would take hours.

So the text is tokenised instead, and each run of one to four words is looked up
in a dictionary. That is O(words in the sentence) whatever the library's size,
and it is what makes matching at ADM3 and ADM4 affordable at all.

THE GUARDS, AND WHY EACH ONE EXISTS
Matching at every level means 30,000 names competing for ordinary sentences, so
a match has to earn its place:

  same country      A sentence attributed to Sudan may only highlight somewhere
                    in Sudan. Every polygon now carries a country - including
                    the IFRC areas of interest, which did not, and that is
                    precisely how 20 rows of Sudanese reporting ended up drawn
                    on Amhara, in Ethiopia.
  long enough       Four characters at ADM0-2 as before; six at ADM3 and below,
                    where the names get short, numerous and word-like.
  not a common word A stoplist, because several real districts are spelled
                    exactly like ordinary English and French words.
  unambiguous       Where one name belongs to several places in the same
                    country, the match falls back to the smallest area that
                    contains all of them - naming a place should never silently
                    pick one of four identically-named villages.
  deepest wins      A sentence naming both a locality and its state highlights
                    the locality.
"""
import functools
import re
import unicodedata

# Names that are also ordinary words. Every one of these is a real administrative
# unit somewhere in the library, and every one would otherwise match prose.
STOPWORDS = {
    # English
    "north", "south", "east", "west", "central", "centre", "center", "north east",
    "north west", "south east", "south west", "middle", "upper", "lower", "new",
    "old", "river", "lake", "island", "port", "city", "town", "village", "region",
    "district", "state", "county", "area", "camp", "market", "hospital", "school",
    "health", "water", "green", "white", "blue", "red", "block", "unity", "peace",
    "victory", "union", "capital", "national", "general", "special", "rural",
    "urban", "east bank", "west bank", "north bank", "south bank",
    # French - CAR and Chad names are French
    "nord", "sud", "est", "ouest", "centre ville", "ville", "region", "prefecture",
    "commune", "quartier", "arrondissement", "haut", "bas", "grand", "petit",
    "nouvelle", "nouveau", "lac", "riviere", "mont",
}

# How short a name may be, by level. Deeper levels have shorter, more numerous
# and more word-like names, so they have to clear a higher bar.
#
# Three at ADM0/ADM1 exists for exactly one place: Chad's Lac province, the
# only country or region in the whole library with a name that short. A floor of
# four silently lost the Lake Chad basin, which is not a corner of this crisis
# anyone can afford to drop.
MIN_LENGTH = {0: 3, 1: 3, 2: 4, 3: 6, 4: 6}

# The longest place name, in words, that will be looked for. "Northern Bahr el
# Ghazal" is four; nothing in the library that matters is longer.
MAX_WORDS = 4


def normalise(s):
    """Fold a name to something two spellings of it can both reach.

    Strips accents so Ouaddai matches Ouaddaï, drops punctuation, and collapses
    whitespace. Deliberately does NOT transliterate: Arabic names stay in
    Arabic, which is exactly what keeps Egypt's 5,716 Arabic-named villages from
    colliding with English prose.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


# Words a report adds or drops freely: "Aswan" and "Aswan Governorate" are one
# place, and so are "Northern" and "Northern State".
_SUFFIX = re.compile(
    r"\s+(governorate|governate|province|region|state|pca|locality|district|"
    r"county|prefecture|sub prefecture|zone|woreda|markaz|city)$")


class Gazetteer:
    """Every place the library knows, indexed by every name it answers to."""

    def __init__(self, rows):
        # normalised name -> [(pcode, level, iso3, name, kind), ...]
        self.index = {}
        self.parent = {}        # pcode -> parent pcode
        self.meta = {}          # pcode -> (name, level, iso3)
        for pcode, level, iso3, name, parent_pcode, alts, kind in rows:
            self.parent[pcode] = parent_pcode
            self.meta[pcode] = (name, level, iso3)
            names = [name] + [a.get("name") for a in (alts or []) if a.get("name")]
            for raw in names:
                for key in {normalise(raw), _SUFFIX.sub("", normalise(raw))}:
                    if self._acceptable(key, level):
                        self._add(key, (pcode, level, iso3, name, kind))

    def _add(self, key, entry):
        self.index.setdefault(key, [])
        if entry[0] not in [e[0] for e in self.index[key]]:
            self.index[key].append(entry)

    def add_alias(self, name, pcode):
        """Point another name at a place already in the library.

        This is how towns, camps and border crossings work. El Fasher is not an
        administrative unit anywhere, but a report naming El Fasher is telling
        us about North Darfur, so the gazetteer's places are registered as extra
        names for the area that contains them. Without this the corpus loses
        every town it names, which is most of the specific reporting there is.
        """
        if pcode not in self.meta:
            return
        pname, level, iso3 = self.meta[pcode]
        for key in {normalise(name), _SUFFIX.sub("", normalise(name))}:
            if self._acceptable(key, level):
                self._add(key, (pcode, level, iso3, pname, "alias"))

    @staticmethod
    def _acceptable(key, level):
        if not key:
            return False
        # THE STOPLIST APPLIES BELOW ADM1 ONLY.
        # Several countries genuinely name a whole region with an ordinary word:
        # Unity is a South Sudanese state, Central a Ugandan region. Blocking
        # those outright loses real reporting, and the country rule already
        # stops "central Sudan" reaching Uganda's Central region - a sentence
        # can only match a place in the country it was attributed to.
        # Below ADM1 the same words are everywhere (Uganda has fifteen "Central
        # Division" parishes), where they mean nothing and match prose, so there
        # the stoplist stands.
        if key in STOPWORDS and (level is None or level >= 2):
            return False
        # An Arabic or Amharic name is never an English word, so the length rule
        # (which exists to stop short Latin names matching prose) does not apply.
        if any(ord(c) > 0x0590 for c in key):
            return len(key) >= 2
        return len(key) >= MIN_LENGTH.get(level, 6)

    def ancestors(self, pcode):
        """Every p-code above this one, nearest first. Loop-safe."""
        out, seen = [], set()
        cur = self.parent.get(pcode)
        while cur and cur not in seen:
            seen.add(cur)
            out.append(cur)
            cur = self.parent.get(cur)
        return out

    def _resolve_ambiguity(self, candidates):
        """Several places share this name. Return the one area that holds them all.

        Two villages called Kubum in the same state should highlight the state,
        not a coin-flip between them. If they share no ancestor at all, nothing
        is returned - no highlight beats a wrong one.
        """
        chains = [[c[0]] + self.ancestors(c[0]) for c in candidates]
        common = set(chains[0]).intersection(*[set(c) for c in chains[1:]])
        if not common:
            return None
        # The deepest shared ancestor is the one furthest from the root, i.e.
        # the one appearing earliest in a chain.
        best = min(common, key=lambda p: min(c.index(p) for c in chains if p in c))
        name, level, iso3 = self.meta[best]
        # If the only thing they share is the country, there is no area to
        # highlight. Say so. Returning the ADM0 would paint the whole country as
        # a named place, which is not what the report said and is exactly what
        # the country-level wash already shows for reporting that names nowhere.
        if not level:
            return None
        return (best, level, iso3, name, "admin")

    def lookup(self, phrase, country_iso3):
        """One name -> (pcode, level, iso3, name), or None."""
        entries = self.index.get(phrase)
        if not entries:
            return None
        if country_iso3:
            entries = [e for e in entries if e[2] == country_iso3]
        # NAMING THE COUNTRY IS NOT NAMING A PLACE.
        # "Needs remain acute across Sudan" is country-level reporting, and the
        # dashboard already shows that as a wash over the whole country. Letting
        # it match Sudan's ADM0 polygon instead would draw the entire country as
        # though a report had pinned something to it, which is both wrong and
        # far louder on the map than the finding deserves.
        entries = [e for e in entries if e[1] != 0]
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0]

        # A NAMED PLACE beats a town standing in for its state. "Renk" is both
        # a South Sudanese county and a town, and the county is the better
        # answer; the town alias exists for places like El Fasher, which no
        # administrative unit is named after.
        direct = [e for e in entries if e[4] != "alias"]
        if direct:
            entries = direct
        if len(entries) == 1:
            return entries[0]

        # A real administrative unit beats an IFRC area of interest with the
        # same name: the AOIs exist to cover places that are NOT an admin unit,
        # so where both answer to a name, the admin unit is the better answer.
        admin = [e for e in entries if e[4] != "aoi"]
        if admin:
            entries = admin
        if len(entries) == 1:
            return entries[0]

        # SAME NAME AT SEVERAL LEVELS, one inside the other: take the LARGER.
        # Sudan has a Kassala locality inside Kassala state, and a report saying
        # "Kassala" nearly always means the state. Highlighting the locality
        # would be more precise and less often right - and understating the area
        # is the safer error, because the state contains the locality either way.
        pcodes = {e[0] for e in entries}
        outermost = [e for e in entries
                     if not (pcodes - {e[0]}) & set(self.ancestors(e[0]))]
        if len(outermost) == 1:
            return outermost[0]

        # Otherwise the deepest match wins - a locality beats the state around
        # it when the two are named differently.
        deepest = max(e[1] if e[1] is not None else 0 for e in entries)
        finalists = [e for e in entries if (e[1] if e[1] is not None else 0) == deepest]
        if len(finalists) == 1:
            return finalists[0]
        return self._resolve_ambiguity(finalists)

    def find(self, text, country_iso3, focus=None):
        """The place this passage is about: (pcode, matched text, level) or Nones.

        `focus` is the character offset the tagged phrase sits at; the match
        nearest to it wins, because a sentence can mention more than one place
        and the relevant one is the one beside the thing being described.
        """
        words = [(m.group(0), m.start()) for m in re.finditer(r"\w+", text, re.UNICODE)]
        best = None
        for i in range(len(words)):
            for n in range(min(MAX_WORDS, len(words) - i), 0, -1):
                phrase = normalise(" ".join(w for w, _ in words[i:i + n]))
                # Try the phrase as written and with a trailing "Governorate",
                # "State", "Region" removed, so "Aswan Governorate" reaches the
                # governorate itself rather than only whatever is indexed under
                # the full two-word form.
                hit = self.lookup(phrase, country_iso3)
                stripped = _SUFFIX.sub("", phrase)
                if stripped != phrase:
                    hit = self.lookup(stripped, country_iso3) or hit
                if not hit:
                    continue
                pos = words[i][1]
                distance = abs(pos - focus) if focus is not None else pos
                # Prefer the nearest match; break ties by the deeper level.
                rank = (distance, -(hit[1] or 0))
                if best is None or rank < best[0]:
                    best = (rank, hit, " ".join(w for w, _ in words[i:i + n]))
                break            # longest phrase at this position wins
        if not best:
            return None, None, None
        _, hit, matched = best
        return hit[0], matched, hit[1]


@functools.lru_cache(maxsize=1)
def gazetteer():
    """The gazetteer, built once from the boundary library.

    Built lazily rather than when this module is imported: importing the parser
    must not require a migrated database, or the test runner and a fresh install
    both break before they start.
    """
    from boundaries.models import AdminArea

    rows = AdminArea.objects.values_list(
        "pcode", "level", "iso3", "name", "parent_pcode", "name_alt", "kind")
    g = Gazetteer(list(rows))
    _add_gazetteer_towns(g)
    return g


def _add_gazetteer_towns(g):
    """Register the project's towns, camps and crossings as names for their area."""
    from data_pipeline.common import load_gazetteer

    iso_of = {"Sudan": "SDN", "Chad": "TCD", "Ethiopia": "ETH", "Egypt": "EGY",
              "South Sudan": "SSD", "Libya": "LBY", "Uganda": "UGA",
              "Central African Republic": "CAF", "Eritrea": "ERI"}
    added = 0
    for loc in load_gazetteer()["locations"]:
        if loc.get("kind") == "country_anchor" or not loc.get("admin1"):
            continue
        iso3 = iso_of.get(loc.get("country"))
        if not iso3:
            continue
        parent = g.lookup(normalise(loc["admin1"]), iso3)
        if not parent:
            continue
        names = [loc["name"]] + [a.strip() for a in (loc.get("aliases") or "").split("|") if a.strip()]
        for nm in names:
            g.add_alias(nm, parent[0])
            added += 1
    return added
