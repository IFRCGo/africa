"""Step 4: key events timeline.

Two sources:
  1. Curated milestone events of the Sudan crisis (verified against the corpus narrative).
  2. Light extraction from narrative documents (flash updates / external updates) -
     sentences with strong event verbs, deduplicated per month, which also covers
     periods after the curated list ends.
"""
import re

from common import get_db, load_gazetteer

GAZ = load_gazetteer()
LOC = {l["name"].lower(): l for l in GAZ["locations"]}
for l in GAZ["locations"]:
    for a in (l.get("aliases") or "").split("|"):
        if a:
            LOC.setdefault(a.lower(), l)

# (date, title, description, category, location, severity 1-5)
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

EVENT_VERBS = re.compile(
    r"(?:fell to|seized|captured|recaptured|stormed|massacre|famine (?:was )?(?:declared|confirmed)|"
    r"cholera outbreak|outbreak of cholera|dam (?:collapse|burst)|ceasefire|truce|"
    r"border (?:crossing )?(?:re-?opened|closed)|drone (?:attack|strike)s? (?:on|hit)|"
    r"airstrikes? (?:on|hit)|shelling of|attack(?:ed|s)? on (?:a |the )?(?:camp|hospital|market|convoy))",
    re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z■])|\n\s*\n|■|•")


def geocode(text):
    tl = text.lower()
    best = None
    for name, l in LOC.items():
        if len(name) < 4 or l["kind"] == "country_anchor":
            continue
        if name in tl and (best is None or len(name) > len(best[0])):
            best = (name, l)
    return best[1] if best else None


def extract_events(cur):
    n = 0
    seen = set()
    docs = cur.execute(
        """SELECT d.id, d.report_date, GROUP_CONCAT(t.text, '\n')
           FROM documents d JOIN document_text t ON t.document_id = d.id
           WHERE d.family IN ('flash_update', 'regional_external_update')
           GROUP BY d.id ORDER BY d.report_date"""
    ).fetchall()
    for doc_id, rdate, text in docs:
        found = 0
        for sent in SENT_SPLIT.split(text or ""):
            sent = re.sub(r"\s+", " ", sent).strip()
            if not (60 < len(sent) < 420):
                continue
            m = EVENT_VERBS.search(sent)
            if not m:
                continue
            month_key = (rdate[:7] if rdate else "?", m.group(0).lower()[:18])
            if month_key in seen:
                continue
            seen.add(month_key)
            loc = geocode(sent)
            title = sent[:90] + ("..." if len(sent) > 90 else "")
            cur.execute(
                """INSERT INTO events (event_date, title, description, category, location,
                       lat, lon, severity, source, document_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rdate, title, sent, "reported", loc and loc["name"],
                 loc and loc["lat"], loc and loc["lon"], 2, "extracted", doc_id),
            )
            n += 1
            found += 1
            if found >= 3:
                break
    return n


def main():
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM events")
    for d, title, desc, cat, locname, sev in CURATED:
        l = LOC.get(locname.lower())
        cur.execute(
            """INSERT INTO events (event_date, title, description, category, location, lat, lon,
                   severity, source) VALUES (?,?,?,?,?,?,?,?,?)""",
            (d, title, desc, cat, locname, l and l["lat"], l and l["lon"], sev, "curated"),
        )
    n = extract_events(cur)
    con.commit()
    print(f"events: {len(CURATED)} curated + {n} extracted")


if __name__ == "__main__":
    main()
