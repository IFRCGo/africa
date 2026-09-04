"""Step 4 of 7 - build the key-events timeline.

Events come from two places:

  1. A curated list of milestones (below). Each one was checked against the
     reports before being written down, and carries a severity from 1 to 5.
  2. Light extraction from flash updates and external updates: sentences that
     contain a strong event verb ("captured", "famine declared", "dam
     collapse"...). At most three per document and one per verb per month, so
     the timeline stays readable and keeps covering dates after the curated
     list ends.

Like step 3 this rebuilds its table from scratch every time it runs.
"""
import re
from datetime import date

from data_pipeline.common import load_gazetteer
from data_track.models import Document, DocumentText, Event

GAZ = load_gazetteer()

# Place name (and every alias) -> gazetteer entry, used to put events on the map.
LOC = {l["name"].lower(): l for l in GAZ["locations"]}
for l in GAZ["locations"]:
    for a in (l.get("aliases") or "").split("|"):
        if a:
            LOC.setdefault(a.lower(), l)

# The curated milestones: (date, title, description, category, location, severity 1-5)
CURATED = [
    ("2023-04-15", "Conflict erupts in Khartoum",
     "Fighting breaks out between the Sudanese Armed Forces (SAF) and the Rapid Support Forces (RSF) in Khartoum and other cities, triggering the displacement crisis.",
     "conflict", "Khartoum", 5),
    ("2023-04-24", "First mass cross-border outflows",
     "Within days, tens of thousands cross into Chad, Egypt, South Sudan, Ethiopia and CAR. UNHCR begins emergency border monitoring at Adre, Qustul, Joda and Metema.",
     "displacement", "Adre", 4),
    ("2023-05-11", "Jeddah Declaration",
     "SAF and RSF sign the Jeddah Declaration of Commitment to Protect the Civilians of Sudan; fighting nonetheless continues.",
     "policy", "Khartoum", 2),
    ("2023-06-14", "El Geneina violence peaks",
     "Ethnically targeted violence in El Geneina, West Darfur, including the killing of the state governor, drives one of the largest single outflows of the crisis into Chad via Adre.",
     "conflict", "El Geneina", 5),
    ("2023-08-01", "Half a million refugees in Chad",
     "Chad becomes host to the largest Sudanese refugee outflow; eastern Chad provinces (Ouaddai, Sila, Wadi Fira) absorb hundreds of thousands of mostly women and children.",
     "displacement", "Adre", 3),
    ("2023-10-26", "Sudan becomes world's largest displacement crisis",
     "With over 4.5 million IDPs and 1.2 million refugees, Sudan is declared the largest internal displacement crisis in the world.",
     "displacement", "Khartoum", 4),
    ("2023-11-02", "RSF takes most of Darfur capitals",
     "RSF captures Nyala, Zalingei and El Geneina garrisons; El Fasher remains the last SAF-held Darfur capital, becoming a refuge for displaced people.",
     "conflict", "Nyala", 4),
    ("2023-12-15", "Wad Madani offensive",
     "RSF attacks and on 18 December captures Wad Madani, Aj Jazirah state - itself a refuge hosting half a million displaced. Over 300,000 flee again (secondary displacement) toward Gedaref, Kassala and White Nile.",
     "conflict", "Wad Madani", 5),
    ("2024-02-07", "Nationwide telecommunications blackout",
     "A near-total telecoms blackout cuts millions off from money transfers and family contact for weeks, hampering aid coordination.",
     "access", "Khartoum", 3),
    ("2024-03-05", "UN Security Council Ramadan ceasefire call",
     "UNSC resolution 2724 calls for a Ramadan cessation of hostilities; fighting continues regardless.",
     "policy", "Khartoum", 2),
    ("2024-04-15", "One year of war",
     "8.6 million people displaced - 6.6 million inside Sudan, 1.8 million across borders. Paris conference raises pledges for the humanitarian response.",
     "displacement", "Khartoum", 4),
    ("2024-05-10", "Siege of El Fasher begins",
     "Full-scale RSF assault on El Fasher, North Darfur, starts an 18-month siege of the city and its 1.5+ million residents and IDPs.",
     "conflict", "El Fasher", 5),
    ("2024-06-29", "RSF captures Singa, Sennar state",
     "The fall of Singa displaces over 700,000 people across Sennar, Blue Nile and Gedaref states.",
     "conflict", "Singa", 4),
    ("2024-08-01", "Famine confirmed in Zamzam camp",
     "The IPC Famine Review Committee confirms famine (IPC Phase 5) in Zamzam IDP camp near El Fasher - the first famine determination globally since 2017.",
     "famine", "Zamzam camp", 5),
    ("2024-08-15", "Adre border crossing reopened",
     "Sudanese authorities reopen the Adre crossing from Chad for humanitarian convoys into Darfur, initially for three months, later extended.",
     "access", "Adre", 3),
    ("2024-08-25", "Catastrophic flooding",
     "Heavy rains and the Arba'at Dam collapse near Port Sudan destroy shelters and cut roads; flooding affects 300,000+ people and worsens cholera outbreaks.",
     "flood", "Port Sudan", 3),
    ("2024-10-20", "RSF surge in Aj Jazirah",
     "After a senior RSF commander defects to SAF, RSF retaliatory attacks sweep eastern Aj Jazirah villages, driving over 340,000 people toward Gedaref and Kassala.",
     "conflict", "Aj Jazirah", 4),
    ("2024-12-15", "Surge in arrivals to South Sudan",
     "Renewed fighting pushes arrival rates at the Joda/Renk border above 1,000 people per day; Renk transit centres exceed capacity many times over.",
     "displacement", "Renk", 4),
    ("2025-01-11", "SAF recaptures Wad Madani",
     "Sudanese Armed Forces retake Wad Madani; the army begins recovering central Sudan, opening prospects of return to Aj Jazirah.",
     "conflict", "Wad Madani", 4),
    ("2025-03-26", "SAF recaptures Khartoum",
     "The army retakes the Presidential Palace (21 March), the airport and most of the capital. Spontaneous returns to Khartoum and Aj Jazirah begin in the following months.",
     "conflict", "Khartoum", 5),
    ("2025-04-11", "RSF assault on Zamzam camp",
     "A ground assault on the famine-stricken Zamzam IDP camp kills hundreds and forces 400,000+ people to flee, mostly to Tawila and El Fasher town.",
     "conflict", "Zamzam camp", 5),
    ("2025-04-15", "Two years of war",
     "The crisis marks two years: about 13 million forcibly displaced, including nearly 4 million across borders. London conference seeks renewed funding.",
     "displacement", "Khartoum", 4),
    ("2025-05-04", "Drone attacks on Port Sudan",
     "Drone strikes hit Port Sudan - the de facto administrative capital and main aid hub - damaging the airport, fuel depots and power stations.",
     "conflict", "Port Sudan", 3),
    ("2025-02-25", "Influx from South Sudan",
     "Clashes in Upper Nile state, South Sudan, reverse a flow: by late 2025 over 200,000 people (South Sudanese refugees and returning Sudanese) cross INTO Sudan, mainly to White Nile and Blue Nile states.",
     "displacement", "Renk", 3),
    ("2025-06-01", "Returns gather pace",
     "UNHCR begins systematic tracking of returns: hundreds of thousands of Sudanese return from Egypt, South Sudan and Libya toward Khartoum, Aj Jazirah and Sennar, even as Darfur and Kordofan displacement continues.",
     "return", "Khartoum", 4),
    ("2025-10-26", "Fall of El Fasher",
     "After an 18-month siege, RSF captures El Fasher. Reports of mass atrocities; tens of thousands flee on foot to Tawila amid reports of killings along escape routes.",
     "conflict", "El Fasher", 5),
    ("2025-11-15", "Kordofan offensives intensify",
     "Fighting shifts to North and West Kordofan (Bara, Babanusa, El Obeid axis), driving fresh displacement while returns continue to Khartoum and central Sudan.",
     "conflict", "Bara", 4),
]

# Verbs and phrases that mark a real, datable event rather than background text.
EVENT_VERBS = re.compile(
    r"(?:fell to|seized|captured|recaptured|stormed|massacre|famine (?:was )?(?:declared|confirmed)|"
    r"cholera outbreak|outbreak of cholera|dam (?:collapse|burst)|ceasefire|truce|"
    r"border (?:crossing )?(?:re-?opened|closed)|drone (?:attack|strike)s? (?:on|hit)|"
    r"airstrikes? (?:on|hit)|shelling of|attack(?:ed|s)? on (?:a |the )?(?:camp|hospital|market|convoy))",
    re.I)

# How we split a page of text into sentences. UNHCR reports use bullet symbols
# as well as full stops, so both count as a sentence break.
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z■])|\n\s*\n|■|•")


def geocode(text):
    """Find the most specific place mentioned in a sentence, if any.

    Longer names win ("El Geneina" beats "El"), and whole-country anchors are
    skipped because pinning an event to a whole country is not informative.
    """
    lowered = text.lower()
    best = None
    for name, place in LOC.items():
        if len(name) < 4 or place["kind"] == "country_anchor":
            continue
        if name in lowered and (best is None or len(name) > len(best[0])):
            best = (name, place)
    return best[1] if best else None


def extract_events():
    """Read flash / external updates and pull event sentences out of them."""
    rows = []
    seen = set()

    # Only these two families are written as running narrative.
    documents = (
        Document.objects.filter(family__in=["flash_update", "regional_external_update"])
        .exclude(report_date=None)
        .order_by("report_date", "id")
        .values_list("id", "report_date")
    )
    for doc_id, report_date in documents:
        pages = (DocumentText.objects.filter(document_id=doc_id)
                 .order_by("page").values_list("text", flat=True))
        text = "\n".join(p for p in pages if p)

        found = 0
        for sentence in SENT_SPLIT.split(text or ""):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            # Too short = a heading; too long = a paragraph, not an event.
            if not (60 < len(sentence) < 420):
                continue
            m = EVENT_VERBS.search(sentence)
            if not m:
                continue

            # The same event is repeated across weekly reports, so keep only
            # the first mention of each verb in each month.
            month_key = (report_date.strftime("%Y-%m"), m.group(0).lower()[:18])
            if month_key in seen:
                continue
            seen.add(month_key)

            place = geocode(sentence)
            title = sentence[:90] + ("..." if len(sentence) > 90 else "")
            rows.append(Event(
                event_date=report_date, title=title, description=sentence,
                category="reported", location=place and place["name"],
                lat=place and place["lat"], lon=place and place["lon"],
                severity=2, source="extracted", document_id=doc_id,
            ))
            found += 1
            if found >= 3:      # three events per document is plenty
                break

    Event.objects.bulk_create(rows, batch_size=500)
    return len(rows)


def run():
    """Rebuild the whole timeline: curated milestones first, then extracted ones."""
    Event.objects.all().delete()

    Event.objects.bulk_create([
        Event(
            event_date=date.fromisoformat(day), title=title, description=description,
            category=category, location=place_name,
            lat=(LOC.get(place_name.lower()) or {}).get("lat"),
            lon=(LOC.get(place_name.lower()) or {}).get("lon"),
            severity=severity, source="curated",
        )
        for day, title, description, category, place_name, severity in CURATED
    ])

    n_extracted = extract_events()
    print(f"events: {len(CURATED)} curated + {n_extracted} extracted")
