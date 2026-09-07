/* =========================================================================
 * Sudan & Neighbouring countries - Community Centered Humanitarian Analysis
 * =========================================================================
 *
 * WHAT THIS FILE DOES
 * Draws an interactive map of the Sudan displacement crisis and lets you drag
 * a timeline to replay it from 15 April 2023 to today.
 *
 * WHERE THE DATA COMES FROM
 * Nothing is calculated here. The Django pipeline writes ready-made files into
 * dashboard/data/ (see data_pipeline/steps/s05_export.py, s06 and s07),
 * and this file only fetches them and draws them.
 *
 * HOW IT IS ORGANISED - read the sections in this order:
 *   1. SETTINGS      colours, map anchors, and the `state` object
 *   2. HELPERS       small reusable functions (formatting, maths)
 *   3. LOAD          fetch every data file once, at start-up
 *   4. MAP           create the map and declare every layer it can draw
 *   5. RENDER        one render*() function per layer or panel
 *   6. TIMELINE      the slider and the play button
 *   7. CONTROLS      the checkboxes in the left sidebar
 *   8. BOOT          the few lines at the bottom that start everything
 *
 * THE ONE IDEA TO UNDERSTAND
 * `state.current` is the date the timeline is pointing at. Every render*()
 * function asks the same question: "what was true on state.current?" When you
 * drag the slider we change state.current and call renderAll(), which re-runs
 * all of them. That is the whole animation.
 */
"use strict";

/* ========================= 1. SETTINGS ================================== */

const DAY = 86400000;                       // milliseconds in one day
const START = Date.parse("2023-04-15");     // the day the war began

// One representative point per country, used to place the theme bubbles.
// These mirror the "country_anchor" entries in data_pipeline/gazetteer.json.
const ANCHORS = {
  "Chad": [21.3, 13.6], "Egypt": [31.8, 24.5], "South Sudan": [32.8, 11.2],
  "Ethiopia": [36.5, 12.5], "Central African Republic": [22.9, 10.35],
  "Libya": [23.32, 24.18], "Uganda": [32.4, 1.2], "Eritrea": [36.66, 15.11],
  "Sudan": [29.5, 14.5], "Regional": [29.5, 19.5],
};

// ---------------------------------------------------------------- countries
/* The countries the filter offers, in the order they appear in the dropdown:
   Sudan first because it is the origin of the whole crisis, then its
   neighbours alphabetically. Every name here must match the "name" property
   in data/boundaries/admin0.geojson, because that file is what supplies the
   map bounds we zoom to. */
const COUNTRIES = ["Sudan", "Central African Republic", "Chad", "Egypt",
                   "Ethiopia", "Libya", "South Sudan", "Uganda"];

/* Corridor ids in flows.json are built from country slugs - "sudan-chad",
   "chad-sudan-return", "south_sudan-sudan-influx". This turns a slug back into
   the country name the rest of the dashboard uses. */
const SLUG_TO_COUNTRY = {
  sudan: "Sudan", chad: "Chad", egypt: "Egypt", libya: "Libya",
  ethiopia: "Ethiopia", uganda: "Uganda", eritrea: "Eritrea",
  south_sudan: "South Sudan", car: "Central African Republic",
};

/* The IFRC Areas of Interest carry a two-letter country code instead of a
   name (aoi_ipc.geojson, "ipc_country"). */
const ISO2_TO_COUNTRY = {
  SD: "Sudan", TD: "Chad", EG: "Egypt", LY: "Libya", ET: "Ethiopia",
  UG: "Uganda", SS: "South Sudan", CF: "Central African Republic",
};

/* These datasets describe the inside of Sudan only, so they have nothing to
   show when Sudan is filtered out. Named here so the reason is written down
   once rather than repeated as a magic string in five render functions. */
const SUDAN_ONLY = "Sudan";
// ---------------------------------------------------------------- colours
// Colour is defined ONCE, in the :root block of app.css. This reads those
// same custom properties back out, so the stylesheet stays the only place a
// colour is written down and the map, the legend and the CSS can never drift
// apart. (The stylesheet is a <link> in <head> and this script runs at the
// end of <body>, so the values are always resolved by the time we ask.)
const CSS_VARS = getComputedStyle(document.documentElement);
function paletteColor(name, fallback) {
  const value = CSS_VARS.getPropertyValue(name).trim();
  if (value) return value;
  // Only reachable if someone deletes a token from app.css; a visible wrong
  // colour is easier to debug than an invisible layer MapLibre refused.
  console.warn(`[dashboard] missing CSS colour token ${name}; using ${fallback}`);
  return fallback;
}

// The single colour rule of the whole map:
//   orange = people moving OUT of Sudan   (IFRC "Migration and identity")
//   green  = people moving back INTO Sudan (IFRC "Climate and environment")
const COLOR_OUT = paletteColor("--out", "#ff8200");
const COLOR_IN = paletteColor("--return", "#009775");
// Key events and the brand accent, both from the IFRC reds.
const COLOR_EVENT = paletteColor("--event", "#011e41");
const COLOR_ACCENT = paletteColor("--accent", "#ee2435");
const COLOR_INK = paletteColor("--text", "#011e41");
const COLOR_MUTED = paletteColor("--muted", "#6c757d");
const WHITE = paletteColor("--ifrc-white", "#ffffff");
// Sudanese refugees counted in the host countries.
const COLOR_IDP_LOCALITY = paletteColor("--idp-locality", "#ffb25b");
const COLOR_IDP_STATE = paletteColor("--idp-state", "#958dbe");
const COLOR_IN_HOST = paletteColor("--refugees", "#8dcde2");

// The five theme groups, their display names and their colours. These match
// the "dimension" values the pipeline writes into tags.json, and each one is
// given the IFRC thematic palette that means the same thing.
const DIM_META = {
  hazard: { label: "Hazards", color: paletteColor("--dim-hazard", "#d22730") },
  vulnerability: { label: "Vulnerabilities", color: paletteColor("--dim-vulnerability", "#6b3a90") },
  coping: { label: "Coping mechanisms", color: paletteColor("--dim-coping", "#009775") },
  need: { label: "Needs", color: paletteColor("--dim-need", "#1874a0") },
  movement_pattern: { label: "Movement patterns", color: paletteColor("--dim-movement", "#ff8200") },
};

/* The order the pillar bands are nested in, outermost first. Hazards are
   outside because they are the thing that happens TO a place; the pillars that
   describe the people there sit within it. */
const DIM_ORDER = ["hazard", "vulnerability", "coping", "need", "movement_pattern"];
// Pixels between one pillar's band and the next.
const BAND_STEP = 3.5;
const COLOR_WATER = paletteColor("--water", "#1f9ad6");

/* Which tags make the water worth pointing at. Flooding and water/sanitation
   needs are ABOUT the water; a protection concern in a riverside state is not,
   and lighting the river for it would imply a link the report never made. */
const WATER_TAGS = { hazard: ["flooding"], need: ["water_wash"] };

// EVERYTHING the page currently shows is described by this one object.
// Change something here, call renderAll(), and the map catches up.
const state = {
  data: {},                // every file loaded from data/, keyed by name
  endDate: null,           // the most recent date we have data for
  current: START,          // the date the timeline is pointing at RIGHT NOW
  playing: false,          // is the play button running?
  activeTags: new Set(),   // ticked theme boxes, stored as "dimension|tag"
  /* THE COUNTRY FILTER. Empty means "no filter - show everything", which is
     not the same as "no countries selected". Every filter test in this file
     goes through countryOn() below, so that distinction is made in exactly
     one place. */
  countries: new Set(),
  voiceSearch: "",         // text typed into the Community Insights search box
  // Which layers are switched on. These match the checkboxes in index.html.
  showFlows: true, showReturns: true, showEvents: true,
  showIDP: false, showIDPStates: false, showRefugees: false, showFoodsec: false, showCrossings: true, showAOI: false,
};

/* ========================= 2. HELPERS =================================== */

/* IPC republishes its food-security map a few times a year. This finds the
   most recent published version that existed on the timeline date `t`. */
function ipcPeriodAt(t) {
  const dates = (state.data.ipc && state.data.ipc._meta.dates) || [];
  let d = null;
  for (const dt of dates) { if (Date.parse(dt) <= t) d = dt; }
  return d;
}

const $ = (s) => document.querySelector(s);   // shorthand for "find this element"
// 1234567 -> "1.2M";  4500 -> "5K";  120 -> "120"
const fmtNum = (v) => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : String(v);
const fmtDate = (t) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const monthKey = (t) => new Date(t).toISOString().slice(0, 7);   // -> "2024-08"

/* THE most-used function in this file.

   Our data is a list of dated readings, taken irregularly. To show a number
   for any day the user drags to, we take the most recent reading on or before
   that day - exactly how a real situation report reads: the last figure
   published still stands until a newer one arrives. Returns null when nothing
   had been reported yet. */
function seriesAt(series, t) {
  let v = null;
  for (const p of series) {
    if (Date.parse(p.date) > t) break;
    v = p.value;
  }
  return v;
}

/* Build a gently curved line between two points, so movement arrows stay
   readable instead of becoming straight-line spaghetti. `bend` controls how
   far the curve bulges sideways; a negative bend curves the other way, which
   is how the outbound (red) and return (green) arrows on the same route are
   kept apart. */
function arc(o, d, bend = 0.18, steps = 40) {
  const mx = (o[0] + d[0]) / 2, my = (o[1] + d[1]) / 2;
  const dx = d[0] - o[0], dy = d[1] - o[1];
  const cx = mx - dy * bend, cy = my + dx * bend;
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const s = i / steps, u = 1 - s;
    pts.push([u * u * o[0] + 2 * u * s * cx + s * s * d[0],
              u * u * o[1] + 2 * u * s * cy + s * s * d[1]]);
  }
  return pts;
}

/* ================= 2b. WHICH COUNTRY IS THIS? ==========================
 * Only three of the data files say which country a row belongs to. For
 * everything else the country has to be worked out, and this section is
 * where that happens. It runs ONCE, at start-up (deriveCountries below), and
 * writes the answer onto the data, so that dragging the timeline never pays
 * for any of it.
 * ======================================================================== */

/* Is the point (x, y) inside this ring? The standard ray-casting test: walk
   the ring's edges and count how many cross a horizontal line running east
   from the point. An odd count means inside. */
function ringContains(ring, x, y) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

/* The same test for a whole Polygon or MultiPolygon. Ring 0 of each polygon
   is its outline and any further rings are holes punched out of it, so a
   point inside a hole is NOT inside the country. */
function polyContains(geom, x, y) {
  const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
  for (const rings of polys) {
    if (!ringContains(rings[0], x, y)) continue;
    let inHole = false;
    for (let r = 1; r < rings.length; r++) if (ringContains(rings[r], x, y)) inHole = true;
    if (!inHole) return true;
  }
  return false;
}

/* The smallest west/south/east/north box containing a geometry. */
function geomBBox(geom) {
  let w = 180, s = 90, e = -180, n = -90;
  (function walk(c) {
    if (typeof c[0] === "number") {
      if (c[0] < w) w = c[0];
      if (c[0] > e) e = c[0];
      if (c[1] < s) s = c[1];
      if (c[1] > n) n = c[1];
    } else for (const part of c) walk(part);
  })(geom.coordinates);
  return [w, s, e, n];
}

// name -> { bbox, geom }, filled by deriveCountries() from admin0.geojson.
const COUNTRY_SHAPES = {};

/* Which country contains this point? Returns null out at sea or outside the
   eight countries we hold outlines for. The cheap box test first means the
   expensive ring walk usually runs for one country, not eight. */
function countryAt(lon, lat) {
  if (lon == null || lat == null) return null;
  for (const [name, shape] of Object.entries(COUNTRY_SHAPES)) {
    const [w, s, e, n] = shape.bbox;
    if (lon < w || lon > e || lat < s || lat > n) continue;
    if (polyContains(shape.geom, lon, lat)) return name;
  }
  return null;
}

/* SPLIT VIEW: EACH HALF IS ITS OWN, NARROWER, FILTER.

   The panels down the sides always describe the whole selection. The map
   halves do not: with Sudan and Egypt selected, the left half is Sudan and the
   right half is Egypt, and Aswan - which is in Egypt - must appear only in the
   right half.

   That is what these two variables do. While a half is being drawn,
   `renderScope` holds just that half's country and `renderTarget` holds just
   that half's map, so every filter test below and every setSource() above
   narrows to it without any render function needing to know. Outside that,
   both are null and everything works on the whole selection, exactly as it
   does when the map is not split. */
let renderScope = null;    // the country THIS half is showing, or null for all
let renderTarget = null;   // the map THIS half draws to, or null for every map

// The countries that matter right now: one half's, or the whole selection.
const scopeCountries = () => renderScope || state.countries;

/* THE QUESTION EVERY RENDER FUNCTION ASKS.

   An empty filter means "no filter is applied", so everything passes. That is
   deliberately different from "the user deselected everything": the country
   dropdown's Clear button empties the set and the dashboard returns to showing
   the whole region, which is what people expect from a filter. */
function countryOn(name) {
  const s = scopeCountries();
  return s.size === 0 || s.has(name);
}

// Is any country in this list selected? Used for flows and crossings, which
// join two countries and stay visible if EITHER end is selected.
function anyCountryOn(names) {
  const s = scopeCountries();
  return s.size === 0 || names.some((c) => s.has(c));
}

// Is a filter applied at all? Reads better than checking .size everywhere.
const filtered = () => scopeCountries().size > 0;

/* Rows tagged "Regional" describe the response as a whole rather than any one
   country. They belong in the unfiltered view but would otherwise survive
   every filter, so they are dropped as soon as a country is chosen. */
const countryOnStrict = (name) => (filtered() ? scopeCountries().has(name) : true);

/* Corridors and border crossings join TWO countries, so "which half does this
   belong in?" has a second part to it.

   In the ordinary single map, nothing changes: a corridor shows if either end
   is selected, so picking Sudan alone still shows every route out of Sudan.

   In split view it also has to have its far end inside the selection. Showing
   Sudan beside Egypt should be about Sudan and Egypt: the Sudan-Chad arrow
   would otherwise still be drawn across the Sudan half, which is not what
   "these two countries" means. */
function corridorInScope(names) {
  if (!renderScope) return anyCountryOn(names);
  return names.some((c) => renderScope.has(c)) && names.every((c) => state.countries.has(c));
}

/* The map bounds to fly to for a set of countries: the union of their boxes,
   with a little breathing room, clamped to the region we allow panning in. */
function boundsFor(names) {
  let w = 180, s = 90, e = -180, n = -90;
  for (const name of names) {
    const shape = COUNTRY_SHAPES[name];
    if (!shape) continue;
    w = Math.min(w, shape.bbox[0]); s = Math.min(s, shape.bbox[1]);
    e = Math.max(e, shape.bbox[2]); n = Math.max(n, shape.bbox[3]);
  }
  if (w > e) return REGION_BOUNDS;   // nothing recognised - show the region
  const pad = 0.6;
  return [
    [Math.max(REGION_BOUNDS[0][0], w - pad), Math.max(REGION_BOUNDS[0][1], s - pad)],
    [Math.min(REGION_BOUNDS[1][0], e + pad), Math.min(REGION_BOUNDS[1][1], n + pad)],
  ];
}

/* Split a corridor id into the countries at its two ends.
   "sudan-chad" -> [Sudan, Chad];  "south_sudan-sudan-influx" -> [South Sudan,
   Sudan]. The trailing "-return"/"-influx" is a direction, not a place. */
function corridorCountries(cid) {
  const parts = cid.replace(/-(return|influx)$/, "").split("-");
  const out = [];
  for (const slug of parts) {
    const name = SLUG_TO_COUNTRY[slug];
    if (name && !out.includes(name)) out.push(name);
  }
  return out;
}

/* Stamp a country onto every row that does not already carry one. Called once,
   from loadData(), before anything is drawn. */
function deriveCountries() {
  // country outlines, used by countryAt() and boundsFor()
  for (const f of (state.data.admin0 || { features: [] }).features)
    COUNTRY_SHAPES[f.properties.name] = { bbox: geomBBox(f.geometry), geom: f.geometry };

  // flows: from the corridor id
  for (const [cid, c] of Object.entries(state.data.flows)) c.countries = corridorCountries(cid);

  // crossings: the file names the country on the far side; the near side is
  // always Sudan, so a crossing belongs to both.
  for (const c of state.data.crossings.points)
    c.countries = c.country === "Sudan" ? ["Sudan"] : ["Sudan", c.country];

  /* events: located by their coordinates. 26 of the 77 events have none -
     they are narrative items about the crisis as a whole ("the UN welcomed
     the ceasefire") rather than something that happened in one place. They
     are marked Regional: they can never draw on the map anyway, and they stay
     in the timeline list whatever the filter, because dropping the diplomatic
     record from a country view would misrepresent the record. */
  for (const ev of state.data.events)
    ev.country = countryAt(ev.lon, ev.lat) || "Regional";

  // the IFRC Areas of Interest carry a two-letter code
  for (const f of (state.data.aoi || { features: [] }).features)
    f.properties.country = ISO2_TO_COUNTRY[f.properties.ipc_country] || null;
}

/* The polygons the pillars are drawn on, and the rivers beside them, come to
   about 3 MB. Most visits never switch a theme on, so they are fetched the
   first time one is - the same bargain the food-security layer makes. */
let areasLoading = null;
function loadAreas() {
  if (!areasLoading) {
    areasLoading = Promise.all([
      fetch("data/boundaries/areas.geojson").then((r) => r.json()),
      fetch("data/water.geojson").then((r) => r.json()),
    ]).then(([areas, water]) => {
      state.data.areas = areas;
      state.data.water = water;
      // name -> the water bodies beside it, worked out by build_map_context
      state.data.areaById = {};
      for (const f of areas.features) state.data.areaById[f.properties.id] = f.properties;
      // Hand the geometry to every map that already exists.
      for (const m of maps) {
        const src = m.getSource("areas");
        if (src) src.setData(areas);
      }
    });
  }
  return areasLoading;
}

/* The IPC food-security file is downloaded lazily, the first time someone
   switches that layer on, so its areas are located then rather than at
   start-up. Each area is placed by the centre of its bounding box, which is
   accurate enough for "which country is this in?" and far cheaper than a true
   centroid over several thousand polygons. */
function deriveIPCCountries() {
  for (const fc of Object.values(state.data.ipc.periods)) {
    for (const f of fc.features) {
      if (f.properties.country !== undefined) continue;
      const [w, s, e, n] = geomBBox(f.geometry);
      f.properties.country = countryAt((w + e) / 2, (s + n) / 2);
    }
  }
}

/* Keep only the areas in the selected countries. Returns the collection
   unchanged when no filter is on, so the common case copies nothing. */
function filterFC(fc) {
  if (!filtered() || !fc) return fc;
  const s = scopeCountries();
  return { type: "FeatureCollection",
           features: fc.features.filter((f) => s.has(f.properties.country)) };
}

/* ========================= 3. LOAD ===================================== */

/* Fetch every data file once, at start-up, and remember it in state.data.
   Promise.all downloads them all at the same time rather than one by one. */
async function loadData() {
  const names = ["meta", "flows", "headline", "events", "tags", "documents",
                 "crossings", "idp_localities", "idp_states", "refugee_camps", "seasonal"];
  const res = await Promise.all(names.map((n) => fetch(`data/${n}.json`).then((r) => r.json())));
  names.forEach((n, i) => (state.data[n] = res[i]));
  // boundary context layers (country outlines, state lines, IFRC Areas of Interest + IPC)
  const [admin0, admin1, aoi] = await Promise.all([
    fetch("data/boundaries/admin0.geojson").then((r) => r.json()),
    fetch("data/boundaries/admin1_lines.geojson").then((r) => r.json()),
    fetch("data/aoi_ipc.geojson").then((r) => r.json()),
  ]);
  state.data.admin0 = admin0; state.data.admin1 = admin1; state.data.aoi = aoi;
  // ipc_areas_fs.geojson (~2 MB) is lazy-loaded on first food-security toggle
  state.endDate = Date.parse(state.data.meta.date_max);
  // Work out which country every row belongs to, once, before anything draws.
  deriveCountries();
  $("#last-updated").textContent = fmtDate(state.endDate);
}

/* The document count in the page footer. Unfiltered it is the figure the
   pipeline reported; filtered it is counted from the catalogue, which does
   name a country for every document. */
function renderDocCount() {
  const n = filtered()
    ? state.data.documents.filter((d) => state.countries.has(d.country)).length
    : state.data.meta.documents;
  $("#doc-count").textContent = n.toLocaleString();
}

/* ========================= 4. MAP ====================================== */

/* THE PAGE CAN SHOW MORE THAN ONE MAP.

   Normally there is exactly one. When the user picks exactly two countries in
   the country filter, the map area splits and shows those two side by side.
   That is the only reason this is a list rather than a single object.

   `map` is the FIRST map: the one that scroll-to-a-country and click-an-event
   fly. `maps` is every map currently alive, and every layer update goes to all
   of them through setSource() below, so both halves always show the same
   filtered data - only the viewport differs. */
let map;                 // the primary map (always maps[0])
let mapB = null;         // the right-hand map; built lazily, only if ever needed
const maps = [];         // every live map, in the order they were created

// Zoom lock to the Sudan + neighbours region. The top edge is 34.5°N rather
// than the region's 32°N because Libya reaches 33.18°N: with a lower cap,
// fitBounds() would silently clamp and never frame Libya properly.
const REGION_BOUNDS = [[8.0, -3.0], [56.0, 34.5]];

/* Create one map: a light CARTO Positron basemap, locked to the Sudan and
   neighbours region so a user cannot accidentally pan away to Europe.
   Resolves once the style has loaded, because layers cannot be added before
   then. */
function initMap(containerId) {
  const m = new maplibregl.Map({
    container: containerId,
    style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    center: [29.5, 15.2],
    zoom: 4.35,
    minZoom: 3,
    maxBounds: REGION_BOUNDS,
    attributionControl: { compact: true },
  });
  m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  return new Promise((resolve) => m.on("load", () => resolve(m)));
}

/* Hand one layer's shapes to EVERY live map. This is the single choke point
   that makes the split view work: the render*() functions in section 5 do not
   know or care how many maps are on screen. */
function setSource(id, fc) {
  for (const m of (renderTarget ? [renderTarget] : maps)) {
    const src = m.getSource(id);
    if (src) src.setData(fc);
  }
}

/* Declare every layer the map can draw, once, in the order they stack from
   bottom to top. They all start EMPTY: the render*() functions in section 5
   fill them with the right shapes for whatever date the timeline shows. */
function addLayers(m) {
  // ---- IPC food-security choropleth, area level (bottom of the stack) ----
  m.addSource("ipc", { type: "geojson", data: empty() });
  m.addLayer({
    id: "ipc-fill", type: "fill", source: "ipc",
    paint: {
      "fill-color": ["case", [">=", ["get", "ph"], 1], ["get", "color"], "rgba(0,0,0,0)"],
      "fill-opacity": 0.6,
    },
  });
  m.addLayer({
    id: "ipc-line", type: "line", source: "ipc",
    paint: { "line-color": "#0e1116", "line-width": 0.4, "line-opacity": 0.5 },
  });
  m.addLayer({
    id: "ipc-famine", type: "line", source: "ipc",
    filter: ["==", ["get", "fam"], true],
    paint: { "line-color": COLOR_ACCENT, "line-width": 1.8 },
  });

  // ---- boundary context: state lines, country outlines, IFRC Areas of Interest ----
  m.addSource("admin1lines", { type: "geojson", data: state.data.admin1 || empty() });
  m.addLayer({
    id: "admin1-line", type: "line", source: "admin1lines",
    paint: { "line-color": "#bfc4cb", "line-width": 0.6, "line-dasharray": [2, 2] },
  });
  m.addSource("aoi", { type: "geojson", data: empty() });
  m.addLayer({
    id: "aoi-fill", type: "fill", source: "aoi",
    paint: { "fill-color": ["get", "ipc_color"], "fill-opacity": 0.5 },
  });
  m.addLayer({
    id: "aoi-line", type: "line", source: "aoi",
    paint: { "line-color": COLOR_EVENT, "line-width": 2.4 },
  });
  /* The national wash. About two-thirds of tagged reporting names no place
     ("shelter needs remain acute across Chad"), and that reporting is real. It
     shades the whole country in NEUTRAL GREY, darker where there is more of
     it. Grey deliberately: the five pillar colours belong to the bands, so a
     colour on this map always names one pillar and the grey always means
     "reported, but not to a place". */
  m.addSource("admin0fill", { type: "geojson", data: state.data.admin0 || empty(),
                              promoteId: "name" });
  m.addLayer({
    id: "country-tint", type: "fill", source: "admin0fill",
    paint: {
      "fill-color": COLOR_INK,
      "fill-opacity": ["coalesce", ["feature-state", "tint"], 0],
    },
  });
  m.addSource("admin0lines", { type: "geojson", data: state.data.admin0 || empty() });
  m.addLayer({
    id: "admin0-line", type: "line", source: "admin0lines",
    paint: { "line-color": "#5b6470", "line-width": 1.3 },
  });

  /* ---- the theme layers: WHERE each pillar is reported -------------------
     The pillars used to be bubbles on a country anchor. They are now drawn on
     the place the report actually named, because "flooding in Northern State"
     and "flooding somewhere in Sudan" are different findings and one bubble in
     the middle of the country said the same thing for both.

     THE OVERLAY RULE. The five pillars are meant to be read TOGETHER: put
     hazards up, add vulnerabilities, then see whether coping is reported in
     the same places. So they are five independent layers, and each draws a
     band inset one step further from the boundary than the last. Bands never
     blend, so every colour still means exactly one pillar, and an area
     wearing three bands is an area where three pillars converge.

     One source holds all 336 polygons and is set once. What each pillar shows
     on it is carried by FEATURE STATE rather than by five copies of the
     geometry - see renderThemes(). */
  m.addSource("areas", { type: "geojson", data: empty(), promoteId: "id" });
  // A faint wash under the bands, so a highlighted area reads as filled in
  // rather than merely outlined. It takes the leading pillar's colour.
  m.addLayer({
    id: "area-wash", type: "fill", source: "areas",
    paint: {
      "fill-color": ["coalesce", ["feature-state", "topColor"], "rgba(0,0,0,0)"],
      "fill-opacity": ["coalesce", ["feature-state", "wash"], 0],
    },
  });
  DIM_ORDER.forEach((dim, i) => {
    m.addLayer({
      id: `theme-band-${dim}`, type: "line", source: "areas",
      layout: { "line-join": "round" },
      paint: {
        "line-color": DIM_META[dim].color,
        // one step further inside the boundary for each pillar
        "line-offset": -(i * BAND_STEP),
        "line-width": ["coalesce", ["feature-state", `w_${dim}`], 0],
        "line-opacity": ["coalesce", ["feature-state", `o_${dim}`], 0],
      },
    });
  });

  /* ---- water ------------------------------------------------------------
     Rivers and lakes beside an area that has WATER-RELATED reporting on it -
     flooding, or water and sanitation needs. They pulse, and that is the only
     movement on this map, so it is kept for the case where the water is part
     of the story rather than merely nearby: floods by the Nile light the Nile,
     a protection concern in the same state does not. */
  m.addSource("water", { type: "geojson", data: empty() });
  m.addLayer({
    id: "water-glow", type: "line", source: "water",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": COLOR_WATER,
      "line-width": ["case", ["==", ["get", "kind"], "lake"], 5, 7],
      "line-opacity": 0.35,             // animated by pulseWater()
      "line-blur": 3,
    },
  });
  m.addLayer({
    id: "water-core", type: "line", source: "water",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": COLOR_WATER, "line-width": 1.4, "line-opacity": 0.95 },
  });

  m.addSource("flows", { type: "geojson", data: empty() });
  m.addSource("flow-labels", { type: "geojson", data: empty() });
  m.addSource("events", { type: "geojson", data: empty() });

  m.addLayer({
    id: "flow-lines", type: "line", source: "flows",
    layout: { "line-cap": "round" },
    paint: {
      "line-color": ["get", "color"],
      "line-width": ["get", "width"],
      "line-opacity": 0.8,
    },
  });
  // chevrons repeated along the line, auto-rotated to the direction of travel
  m.addLayer({
    id: "flow-arrows", type: "symbol", source: "flows",
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 60,
      "text-field": ">",
      "text-size": ["get", "arrowSize"],
      "text-font": ["Open Sans Bold"],
      "text-keep-upright": false,
      "text-allow-overlap": true,
      "text-rotation-alignment": "map",
    },
    paint: {
      "text-color": ["get", "color"],
      "text-halo-color": WHITE, "text-halo-width": 1.4,
    },
  });
  m.addLayer({
    id: "flow-labels", type: "symbol", source: "flow-labels",
    layout: {
      "text-field": ["get", "label"],
      "text-size": 12,
      "text-font": ["Open Sans Bold"],
      "text-anchor": "center",
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": ["get", "color"],
      "text-halo-color": WHITE, "text-halo-width": 1.8,
    },
  });
  m.addLayer({
    id: "event-glow", type: "circle", source: "events",
    paint: {
      "circle-radius": ["*", ["get", "size"], 2.1],
      "circle-color": COLOR_EVENT, "circle-opacity": 0.22, "circle-blur": 0.6,
    },
  });
  m.addLayer({
    id: "event-dots", type: "circle", source: "events",
    paint: {
      "circle-radius": ["get", "size"],
      "circle-color": ["case", ["==", ["get", "source"], "curated"], COLOR_EVENT, "#78909c"],
      "circle-stroke-color": WHITE, "circle-stroke-width": 1.4,
      "circle-opacity": ["get", "opacity"],
    },
  });

  // Events and corridors read on hover like every other layer.
  popup(m, "event-dots", (p) =>
    `<b style="color:${COLOR_EVENT}">${fmtDate(Date.parse(p.date))}</b><br><b>${p.title}</b><br>${p.description || ""}`);
  popup(m, "flow-lines", (p) =>
    `<b>${p.name}</b><br>${p.kind}<br><b style="color:${p.color}">${p.labelFull}</b> people (cumulative)`);

  // ---- IDP localities (IOM-DTM, admin2) ----
  m.addSource("idp", { type: "geojson", data: empty() });
  m.addLayer({
    id: "idp-circles", type: "circle", source: "idp",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IDP_LOCALITY, "circle-opacity": 0.5,
      "circle-stroke-color": COLOR_IDP_LOCALITY, "circle-stroke-width": 1,
    },
  });

  // ---- IDP by state (admin1, Sudan IDPs.xlsx) ----
  m.addSource("idp-states", { type: "geojson", data: empty() });
  m.addLayer({
    id: "idp-state-circles", type: "circle", source: "idp-states",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IDP_STATE, "circle-opacity": 0.4,
      "circle-stroke-color": COLOR_IDP_STATE, "circle-stroke-width": 1.4,
    },
  });

  // ---- refugees: host-country totals + curated camp markers ----
  m.addSource("refcountry", { type: "geojson", data: empty() });
  m.addLayer({
    id: "ref-country", type: "circle", source: "refcountry",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IN_HOST, "circle-opacity": 0.22,
      "circle-stroke-color": COLOR_IN_HOST, "circle-stroke-width": 1.4,
    },
  });
  m.addSource("refcamps", { type: "geojson", data: empty() });
  m.addLayer({
    id: "ref-camps", type: "circle", source: "refcamps",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IN_HOST, "circle-opacity": 0.85,
      "circle-stroke-color": "#0e1116", "circle-stroke-width": 1.2,
    },
  });

  // ---- border crossings ----
  m.addSource("crossings", { type: "geojson", data: empty() });
  m.addLayer({
    id: "crossing-dots", type: "circle", source: "crossings",
    paint: {
      "circle-radius": ["case", ["get", "active"], 7, 4.5],
      "circle-color": ["case", ["get", "active"], COLOR_EVENT, WHITE],
      "circle-stroke-color": COLOR_INK, "circle-stroke-width": 1.4,
    },
  });
  m.addLayer({
    id: "crossing-labels", type: "symbol", source: "crossings",
    layout: {
      "text-field": ["get", "name"], "text-size": 10, "text-font": ["Open Sans Bold"],
      "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true,
    },
    paint: { "text-color": COLOR_INK, "text-halo-color": WHITE, "text-halo-width": 1.6 },
  });

  popup(m, "idp-circles", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.state})</span><br>
    <b style="color:${COLOR_IDP_LOCALITY}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM via HDX</span>`);
  popup(m, "idp-state-circles", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(Sudan — state level)</span><br>
    <b style="color:${COLOR_IDP_STATE}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM / UNHCR (Sudan IDPs.xlsx)</span>`);
  popup(m, "ref-country", (p) => `<b style="color:${COLOR_IN_HOST}">${p.country}</b><br>
    <b>${p.valFull}</b> Sudanese refugees · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">UNHCR${p.note ? " · " + p.note : ""}</span>`);
  popup(m, "ref-camps", (p) => `<b style="color:${COLOR_IN_HOST}">${p.name}</b><br>${p.type} · ${p.country}<br>
    Opened ${p.opened}<br><span style="color:${COLOR_MUTED}">Location curated (UNHCR RRP); magnitude shown by country total</span>`);
  popup(m, "area-wash", (p) => {
    const dims = DIM_ORDER
      .map((d) => [d, m.getFeatureState({ source: "areas", id: p.id })[`w_${d}`]])
      .filter(([, w]) => w);
    return `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.country || "IFRC area of interest"})</span><br>
      ${dims.map(([d]) => `<span style="color:${DIM_META[d].color}">&#9632;</span> ${DIM_META[d].label}`).join("<br>") ||
        `<span style="color:${COLOR_MUTED}">no reporting this month</span>`}
      ${(p.water || []).length ? `<br><span style="color:${COLOR_MUTED}">near ${(p.water || []).slice(0, 3).join(", ")}</span>` : ""}`;
  });
  popup(m, "water-core", (p) =>
    `<b style="color:${COLOR_WATER}">${p.name}</b><br><span style="color:${COLOR_MUTED}">${p.kind}</span>`);

  popup(m, "crossing-dots", (p) => `<b>${p.name}</b><br>Crossing to ${p.country}<br>
    ${p.active ? `<b style="color:${COLOR_EVENT}">Active corridor</b> — ${p.flowLabel} people moved (cumulative)` : "No recorded movement at this date"}`);
  popup(m, "ipc-fill", (p) => `<b>${p.area}</b><br>IPC <b>Phase ${p.ph}</b>${p.fam ? ` · <b style="color:${COLOR_ACCENT}">Famine (P5)</b>` : ""}<br>
    <b>${Math.round(p.p3 * 100)}%</b> in Phase 3+ (Crisis or worse)<br><span style="color:${COLOR_MUTED}">IPC analysis via IPC MCP</span>`);
  popup(m, "aoi-fill", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.ipc_country || ""})</span><br>
    <b style="color:${COLOR_EVENT}">IFRC Area of Interest</b><br>
    ${p.ipc_phase ? `IPC <b>Phase ${p.ipc_phase}</b> — <b>${Math.round((p.ipc_p3 || 0) * 100)}%</b> in Phase 3+
      <span style="color:${COLOR_MUTED}">(${p.ipc_n_phase3plus}/${p.ipc_n_areas} sub-areas)</span>` : `<span style="color:${COLOR_MUTED}">No current IPC analysis</span>`}`);
}

/* ONE hovering bubble per map, reused by every layer.

   Making a new Popup on each mouse move would leave a trail of them behind, so
   each map keeps a single one and just moves it and rewrites its contents. */
const hoverBubbles = new WeakMap();
function hoverBubble(m) {
  if (!hoverBubbles.has(m))
    hoverBubbles.set(m, new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,               // clear of the cursor, so it cannot flicker
      className: "hover-popup",
      maxWidth: "280px",
    }));
  return hoverBubbles.get(m);
}

/* Show a layer's details on HOVER, and turn the mouse pointer into a hand over
   it. `html` builds the bubble text from the properties of whatever feature is
   under the cursor.

   It listens on mousemove rather than mouseenter so the bubble follows the
   cursor along a line or across a large area, instead of staying pinned where
   the shape was first entered. The bubble itself ignores the mouse (see
   .hover-popup in app.css); without that it would sit under the cursor, take
   the pointer off the shape, fire mouseleave, and flicker. */
function popup(m, layer, html) {
  m.on("mousemove", layer, (e) => {
    if (!e.features || !e.features.length) return;
    m.getCanvas().style.cursor = "pointer";
    hoverBubble(m).setLngLat(e.lngLat).setHTML(html(e.features[0].properties)).addTo(m);
  });
  m.on("mouseleave", layer, () => {
    m.getCanvas().style.cursor = "";
    hoverBubble(m).remove();
  });
}

// "Draw nothing" - used to clear a layer that is switched off.
const empty = () => ({ type: "FeatureCollection", features: [] });

/* ========================= 5. RENDER ===================================
 * Each function below answers "what should this layer look like on
 * state.current?" and hands the answer to the map. None of them fetch data.
 * ======================================================================== */

/* "sudan-chad" becomes "Sudan > Chad" for display. */
function corridorName(id) {
  return id.replace(/-/g, " → ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/* The movement arrows. Line thickness grows with the number of people (as the
   square root, so a corridor ten times bigger is not drawn ten times fatter),
   and the label in the middle shows the cumulative figure on this date. */
function renderFlows() {
  const t = state.current;
  const lines = [], labels = [];
  for (const [cid, c] of Object.entries(state.data.flows)) {
    const isInflux = cid.endsWith("influx");
    const intoSudan = c.flow_type === "return" || isInflux;   // green family
    if (intoSudan && !state.showReturns) continue;
    if (!intoSudan && !state.showFlows) continue;
    // A corridor stays on the map if EITHER end is a selected country: the
    // Sudan-Chad arrow is part of the Chad picture as much as the Sudan one.
    // In split view it must also stay within the pair - see corridorInScope().
    if (!corridorInScope(c.countries)) continue;
    const v = seriesAt(c.series, t);
    if (!v) continue;
    const color = intoSudan ? COLOR_IN : COLOR_OUT;
    const o = [c.origin.lon, c.origin.lat], d = [c.destination.lon, c.destination.lat];
    const width = Math.max(1, Math.min(5.5, Math.sqrt(v) / 200));
    const bend = !intoSudan ? 0.18 : isInflux ? -0.34 : -0.22;
    const pts = arc(o, d, bend);
    lines.push({
      type: "Feature", geometry: { type: "LineString", coordinates: pts },
      properties: {
        color, width,
        arrowSize: Math.round(8 + width * 2.4),
        name: corridorName(cid),
        kind: isInflux ? "Influx into Sudan" : intoSudan ? "Return movement" : "Cross-border displacement",
        labelFull: v.toLocaleString(),
      },
    });
    labels.push({
      type: "Feature", geometry: { type: "Point", coordinates: pts[Math.floor(pts.length / 2)] },
      properties: { label: fmtNum(v), color },
    });
  }
  setSource("flows", { type: "FeatureCollection", features: lines });
  setSource("flow-labels", { type: "FeatureCollection", features: labels });
}

/* Event dots, plus the banner across the top of the map.

   Recent events (under 45 days old on the timeline) are drawn big and bright.
   Older ones fade, and minor old ones disappear entirely, so the map keeps
   showing what matters now instead of every dot since 2023. */
function renderEvents() {
  const t = state.current;
  const feats = [];
  if (state.showEvents) {
    for (const ev of state.data.events) {
      const et = Date.parse(ev.date);
      if (et > t || !ev.lat) continue;
      if (!countryOn(ev.country)) continue;
      const age = (t - et) / DAY;
      const recent = age < 45;
      if (!recent && ev.severity < 4) continue;       // old minor events fade out
      feats.push({
        type: "Feature", geometry: { type: "Point", coordinates: [ev.lon, ev.lat] },
        properties: {
          title: ev.title, description: (ev.description || "").slice(0, 220),
          date: ev.date, source: ev.source,
          size: 3 + ev.severity * (recent ? 2.2 : 1.1),
          opacity: recent ? 0.95 : 0.45,
        },
      });
    }
  }
  setSource("events", { type: "FeatureCollection", features: feats });
}

/* The banner across the top of the map. It spans BOTH halves, so unlike the
   dots it is worked out once, from the whole selection, rather than per half. */
function renderEventBanner() {
  const t = state.current;
  let banner = null;
  if (state.showEvents) {
    for (const ev of state.data.events) {
      const et = Date.parse(ev.date);
      if (et > t || !countryOn(ev.country)) continue;
      if ((t - et) / DAY >= 45 || ev.source !== "curated") continue;
      if (!banner || Date.parse(banner.date) < et) banner = ev;
    }
  }
  const el = $("#event-banner");
  if (banner) {
    el.innerHTML = `<div class="eb-date">${fmtDate(Date.parse(banner.date))} — ${banner.location || ""}</div>
      <b>${banner.title}</b><br>${banner.description}`;
    el.classList.remove("hidden");
  } else el.classList.add("hidden");
}

// small per-dimension offsets so bubbles of different dimensions don't fully overlap
const DIM_OFFSET = { hazard: [0, 0], vulnerability: [0.55, 0.35], coping: [-0.55, 0.35],
                     need: [0.55, -0.35], movement_pattern: [-0.55, -0.35] };

/* Theme bubbles: for every tag the user ticked, how many times was it
   mentioned in this month of reporting, per country? A bigger bubble means
   more mentions. Each dimension is nudged slightly so bubbles do not hide
   each other. */
/* Write a set of feature states onto one source, on every map being drawn,
   having first cleared whatever was there before. Without the clear, an area
   that stopped being reported would keep last month's band. */
function setStates(sourceId, statesById) {
  for (const m of (renderTarget ? [renderTarget] : maps)) {
    if (!m.getSource(sourceId)) continue;
    m.removeFeatureState({ source: sourceId });
    for (const [id, st] of Object.entries(statesById))
      m.setFeatureState({ source: sourceId, id }, st);
  }
}

/* THE PILLAR LAYERS.

   For the month the timeline is on, and the tags the reader has ticked, this
   answers two questions per pillar:

     which AREAS did the reports name?      -> a band around each one
     how much named no area at all?         -> a grey wash over the country

   Both are drawn from the same rows. A tag row carries a country always and an
   area only when the report said where, so the two totals together are the
   whole of the reporting - nothing is dropped, and the difference between
   "here" and "somewhere in this country" stays visible.

   The bands are set through feature state rather than by rebuilding geometry,
   because the geometry is 2.3 MB and the timeline redraws about eight times a
   second while it plays. */
function renderThemes() {
  const mk = monthKey(state.current);
  const byArea = {};        // area id -> dim -> count
  const unlocated = {};     // country -> count of reporting that named no area
  const waterNames = new Set();

  for (const key of state.activeTags) {
    const [dim, tag] = key.split("|");
    const tagData = (state.data.tags[dim] || {})[tag];
    if (!tagData) continue;
    const isWaterTag = (WATER_TAGS[dim] || []).includes(tag);
    for (const row of tagData.monthly) {
      if (row.month !== mk || !countryOnStrict(row.country)) continue;
      if (row.area) {
        (byArea[row.area] = byArea[row.area] || {})[dim] =
          (byArea[row.area][dim] || 0) + row.count;
        // Only a water-related tag lights the water beside its area.
        if (isWaterTag && state.data.areaById) {
          for (const w of (state.data.areaById[row.area] || {}).water || []) waterNames.add(w);
        }
      } else {
        unlocated[row.country] = (unlocated[row.country] || 0) + row.count;
      }
    }
  }

  // ---- the bands, one feature state per area -----------------------------
  const areaStates = {};
  for (const [areaId, dims] of Object.entries(byArea)) {
    const st = {};
    let top = null;
    for (const [dim, count] of Object.entries(dims)) {
      // Band thickness grows with mentions, as the square root so that a
      // place reported ten times over is not drawn ten times as thick.
      st[`w_${dim}`] = Math.max(1.6, Math.min(7, 1.2 + Math.sqrt(count) * 0.9));
      st[`o_${dim}`] = 0.95;
      if (!top || count > top[1]) top = [dim, count];
    }
    if (top) {
      st.topColor = DIM_META[top[0]].color;
      st.wash = Math.max(0.07, Math.min(0.3, 0.05 + Math.sqrt(top[1]) * 0.03));
    }
    areaStates[areaId] = st;
  }
  setStates("areas", areaStates);

  // ---- the national wash for reporting that named no place ---------------
  const countryStates = {};
  for (const [country, count] of Object.entries(unlocated)) {
    // "Regional" is a bucket, not a country, so there is no outline to shade.
    if (country === "Regional" || !countryOn(country)) continue;
    countryStates[country] = { tint: Math.max(0.05, Math.min(0.26, Math.sqrt(count) * 0.022)) };
  }
  setStates("admin0fill", countryStates);

  // ---- the water beside the flooded places -------------------------------
  const water = state.data.water;
  setSource("water", water && waterNames.size
    ? { type: "FeatureCollection",
        features: water.features.filter((f) => waterNames.has(f.properties.name)) }
    : empty());
  pulseWater(waterNames.size > 0);
}

/* The pulse on the water.

   A slow sine wave on the glow's opacity, running only while there is water to
   show, so an idle dashboard is not animating an empty layer. The core line
   underneath stays steady, so the river is always readable and it is only the
   halo that breathes. */
let pulseFrame = null;
function pulseWater(on) {
  if (!on) {
    if (pulseFrame) cancelAnimationFrame(pulseFrame);
    pulseFrame = null;
    return;
  }
  if (pulseFrame) return;                      // already running
  const step = () => {
    const o = 0.22 + 0.3 * (0.5 + 0.5 * Math.sin(Date.now() / 620));
    for (const m of maps) {
      if (m.getLayer && m.getLayer("water-glow")) m.setPaintProperty("water-glow", "line-opacity", o);
    }
    pulseFrame = requestAnimationFrame(step);
  };
  pulseFrame = requestAnimationFrame(step);
}

/* The list under the theme toggles: each ticked tag, its mention count for
   this month, and a real sentence from a report (click a row to expand it). */
function renderThemePanel(mk) {
  const el = $("#theme-detail");
  el.innerHTML = "";
  const byDim = {};
  for (const key of state.activeTags) {
    const [dim, tag] = key.split("|");
    (byDim[dim] = byDim[dim] || []).push(tag);
  }
  for (const [dim, tags] of Object.entries(byDim)) {
    const rows = [];
    for (const tag of tags) {
      const tagData = (state.data.tags[dim] || {})[tag];
      if (!tagData) continue;
      const n = tagCount(tagData, mk);
      rows.push([tag, n, snippetFor(tagData, mk)]);
    }
    rows.sort((a, b) => b[1] - a[1]);
    if (!rows.length) continue;
    const g = document.createElement("div");
    g.className = "theme-group";
    g.innerHTML = `<h3 style="color:${DIM_META[dim].color}">${DIM_META[dim].label} — ${new Date(state.current).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h3>`;
    for (const [tag, n, snippet] of rows) {
      const row = document.createElement("div");
      row.className = "tag-row";
      row.innerHTML = `<span>${tag.replace(/_/g, " ")}</span><span class="cnt">${n ? n + " mention" + (n > 1 ? "s" : "") : "no reports"}</span>`;
      g.appendChild(row);
      if (snippet) {
        const sn = document.createElement("div");
        sn.className = "tag-snippet";
        sn.textContent = `“…${snippet}…”`;
        row.addEventListener("click", () => sn.classList.toggle("open"));
        g.appendChild(sn);
      }
    }
    el.appendChild(g);
  }
  if (state.activeTags.size && !el.children.length)
    el.innerHTML = `<div style="font-size:12px;color:var(--muted)">No tagged reporting for this month.</div>`;
}

/* The whole history of one headline figure under the current filter, for the
   trend chart under the timeline.

   Unfiltered, this is the published series untouched. Filtered, there is no
   stored series to read, so one is built: take every date any corridor
   reported on, and ask statAt() for the figure on each. A dozen corridors over
   a few hundred dates is a few thousand lookups, which is why this is called
   only when a filter changes and never while the timeline plays. */
function statSeries(metric) {
  const h = state.data.headline;
  if (!filtered()) return h[metric] ? h[metric].series : [];
  const dates = new Set();
  for (const c of Object.values(state.data.flows)) for (const p of c.series) dates.add(p.date);
  if (metric === "idps" || metric === "total_displaced")
    for (const p of (h.idps ? h.idps.series : [])) dates.add(p.date);
  const out = [];
  for (const d of [...dates].sort()) {
    const v = statAt(metric, Date.parse(d));
    if (v) out.push({ date: d, value: v });
  }
  return out;
}

/* Add up the corridors in the selected countries. `dir` is "out" for people
   leaving Sudan and "in" for people returning to it. Returns null when no
   corridor in the selection had reported anything yet, so the card shows a
   dash rather than a misleading zero. */
function flowSum(t, dir) {
  let total = 0, any = false;
  for (const [cid, c] of Object.entries(state.data.flows)) {
    const isInflux = cid.endsWith("influx");
    const intoSudan = c.flow_type === "return" || isInflux;
    if (dir === "out" ? intoSudan : c.flow_type !== "return") continue;
    if (!anyCountryOn(c.countries)) continue;
    const v = seriesAt(c.series, t);
    if (v) { total += v; any = true; }
  }
  return any ? total : null;
}

/* One headline figure, for the current filter.

   With NO filter this reads headline.json exactly as before, so the four
   numbers at the top of the page are the published ones and never drift.

   With a filter, headline.json cannot help: it has no country dimension. The
   figures are added up from the corridors instead. That substitution was
   checked against the unfiltered baseline before it was relied on - summed
   cross-border corridors come to 3.24M against a published 3.20M at the end
   of 2024, and 4.57M against 4.50M in August 2026, with returns matching to
   within 0.2% - so a filtered total and the headline it came from tell the
   same story.

   IDPs are inside Sudan by definition, so that card has nothing to say unless
   Sudan is among the selected countries. */
function statAt(metric, t) {
  const h = state.data.headline;
  if (!filtered()) return h[metric] ? seriesAt(h[metric].series, t) : null;
  const sudanIn = state.countries.has("Sudan");
  switch (metric) {
    case "cumulative_arrivals": return flowSum(t, "out");
    case "returns_to_sudan_total": return flowSum(t, "in");
    case "idps": return sudanIn ? seriesAt(h.idps.series, t) : null;
    case "total_displaced": {
      const idp = sudanIn ? seriesAt(h.idps.series, t) || 0 : 0;
      const out = flowSum(t, "out") || 0;
      return idp + out || null;
    }
    default: return null;
  }
}

/* The four big numbers at the top. Each also shows a small arrow comparing
   the current value with 30 days earlier - green when the direction is good
   news (returns rising), red when it is bad news (displacement rising).
   When a country filter is on, the cards are marked so a filtered number is
   never mistaken for the published headline. */
function renderStats() {
  const t = state.current;
  const set = (sel, metric, risingIsGood) => {
    const v = statAt(metric, t);
    const prev = statAt(metric, t - 30 * DAY);
    let trend = "";
    if (v && prev && Math.abs(v - prev) > v * 0.005) {
      const up = v > prev;
      const good = up === risingIsGood;
      trend = `<span class="trend" style="color:${good ? COLOR_IN : COLOR_EVENT}">${up ? "▲" : "▼"}</span>`;
    }
    const card = $(sel);
    card.classList.toggle("stat-filtered", filtered());
    // "n/a" and "–" mean different things: no data yet, versus a figure this
    // country selection cannot have.
    const naIDP = metric === "idps" && filtered() && !state.countries.has("Sudan");
    $(sel + " .stat-value").innerHTML = (naIDP ? "n/a" : v ? fmtNum(v) : "–") + trend;
  };
  set("#stat-displaced", "total_displaced", false);
  set("#stat-idps", "idps", false);
  set("#stat-crossborder", "cumulative_arrivals", false);
  set("#stat-returns", "returns_to_sudan_total", true);
}

/* --------- right-hand panel: insights, voices and triggers -------------- */

/* How many times was this tag mentioned in this month, in the countries the
   filter allows? The one place tag counting happens, so the theme panel, the
   bubbles, Trends and Top hazards can never disagree with each other. */
function tagCount(tagData, mk) {
  return tagData.monthly
    .filter((r) => r.month === mk && countryOnStrict(r.country))
    .reduce((a, r) => a + r.count, 0);
}

/* The example sentence for a tag in a month.

   tags.json has held one sentence per tag per month, with no record of which
   country it came from. The pipeline now also emits a country-keyed form
   ({"2024-08": {"Chad": "..."}}), so this reads BOTH shapes: the exact
   sentence for a selected country when the data has it, and the single
   month sentence otherwise. Until the pipeline is next run, a filtered view
   therefore shows the month's sentence whenever the tag was reported in the
   selected countries - close, but not attributed. */
function snippetFor(tagData, mk) {
  const entry = tagData.snippets[mk];
  if (!entry) return null;
  if (typeof entry === "string") return entry;          // the older, month-only shape
  const wanted = filtered() ? [...state.countries] : Object.keys(entry);
  for (const c of wanted) if (entry[c]) return entry[c];
  return filtered() ? null : Object.values(entry)[0] || null;
}

/* Which tags of this dimension has the user picked?

   Returns null when none are picked, meaning "this dimension is unrestricted"
   - which is NOT the same as an empty set. Restricting per dimension is the
   point: choosing two hazards should narrow the hazard reporting without
   silently emptying Needs, which the user never touched. */
function activeTagsIn(dim) {
  const picked = new Set();
  const prefix = dim + "|";
  for (const key of state.activeTags)
    if (key.startsWith(prefix)) picked.add(key.slice(prefix.length));
  return picked.size ? picked : null;
}

/* All tags of one dimension for one month, as [tag, count, sample sentence],
   biggest first.

   This is the single source for Trends, Top hazards, Community Insights and
   the theme panel, so both filters have to be applied HERE or those panels
   drift apart from the map: the country filter through tagCount(), and the
   theme filter through activeTagsIn(). */
function monthTagTotals(dim, mk) {
  const only = activeTagsIn(dim);
  const out = [];
  for (const [tag, tagData] of Object.entries(state.data.tags[dim] || {})) {
    if (only && !only.has(tag)) continue;
    const n = tagCount(tagData, mk);
    if (n) out.push([tag, n, snippetFor(tagData, mk)]);
  }
  return out.sort((a, b) => b[1] - a[1]);
}

/* Plain-English findings for the current date, worked out on the spot: the
   fastest-growing outflow, the direction of returns and of internal
   displacement, and the most-reported hazard and need this month. */
function renderInsights() {
  const t = state.current, el = $("#insight-list");
  const items = [];
  // fastest-growing outflow corridor over the last 90 days
  let best = null;
  for (const [cid, c] of Object.entries(state.data.flows)) {
    if (c.flow_type !== "cross_border" || cid.endsWith("influx")) continue;
    if (!anyCountryOn(c.countries)) continue;
    const now = seriesAt(c.series, t), prev = seriesAt(c.series, t - 90 * DAY);
    if (now && prev && now > prev && (!best || now - prev > best.delta))
      best = { cid, delta: now - prev, now };
  }
  if (best)
    items.push({ ico: "🔺", html: `Largest recent outflow: <b>${corridorName(best.cid)}</b> grew by <b>${fmtNum(best.delta)}</b> people in the last 3 months (now ${fmtNum(best.now)}).` });
  // returns trend - read through statAt() so it follows the country filter
  const rNow = statAt("returns_to_sudan_total", t), rPrev = statAt("returns_to_sudan_total", t - 90 * DAY);
  if (rNow && rPrev && rNow > rPrev)
    items.push({ ico: "🟢", good: true, html: `Returns to Sudan rising: <b>+${fmtNum(rNow - rPrev)}</b> in 3 months, <b>${fmtNum(rNow)}</b> in total.` });
  // IDP direction (inside Sudan only, so it drops out of a Chad-only view)
  const iNow = statAt("idps", t), iPrev = statAt("idps", t - 90 * DAY);
  if (iNow && iPrev && Math.abs(iNow - iPrev) > iNow * 0.02)
    items.push({ ico: iNow > iPrev ? "⚠" : "↩", good: iNow < iPrev,
      html: `Internal displacement ${iNow > iPrev ? "rising" : "falling"}: <b>${fmtNum(iNow)}</b> IDPs (${iNow > iPrev ? "+" : "−"}${fmtNum(Math.abs(iNow - iPrev))} since ${fmtDate(t - 90 * DAY)}).` });
  // dominant hazard + need this month
  const mk = monthKey(t);
  const hz = monthTagTotals("hazard", mk)[0];
  if (hz) items.push({ ico: "🔥", html: `Most-reported hazard this month: <b>${hz[0].replace(/_/g, " ")}</b> (${hz[1]} mentions).` });
  const nd = monthTagTotals("need", mk)[0];
  if (nd) items.push({ ico: "📦", html: `Top need in the reporting: <b>${nd[0].replace(/_/g, " ")}</b> (${nd[1]} mentions).` });

  el.innerHTML = items.length
    ? items.map((i) => `<div class="insight ${i.good ? "good" : ""}"><span class="ico">${i.ico}</span><span>${i.html}</span></div>`).join("")
    : `<div class="panel-note">${filtered()
        ? "Nothing to report for the selected countries on this date."
        : "Drag the timeline forward to see insights build up."}</div>`;
}

// "2024-08" -> "August 2024", for labelling a quote with the month it is from.
const monthLabel = (mk) =>
  new Date(mk + "-01").toLocaleDateString("en-GB", { month: "long", year: "numeric" });

/* Every quote in the whole archive, as flat rows, honouring the country
   filter. Built on demand by the search below rather than kept around,
   because it is only needed while someone is typing. */
function allVoices() {
  const rows = [];
  for (const [dim, tags] of Object.entries(state.data.tags)) {
    if (!DIM_META[dim]) continue;
    const only = activeTagsIn(dim);
    for (const [tag, tagData] of Object.entries(tags)) {
      if (only && !only.has(tag)) continue;
      for (const mk of Object.keys(tagData.snippets)) {
        // Under a filter, keep a quote only where its tag was actually
        // reported in one of the selected countries that month.
        if (filtered() && !tagCount(tagData, mk)) continue;
        const text = snippetFor(tagData, mk);
        if (text) rows.push({ dim, tag, mk, text });
      }
    }
  }
  return rows.sort((a, b) => (a.mk < b.mk ? 1 : a.mk > b.mk ? -1 : 0));
}

/* Verbatim sentences from the reports - the human voice behind the numbers.

   With the search box empty this shows up to three quotes for the month the
   timeline is on, one per dimension, as it always has. Type anything and it
   searches the WHOLE archive instead: any single month holds only a handful
   of quotes, so a search confined to one month would almost always come back
   empty. Each result is labelled with its month and clicking it moves the
   timeline there. */
function renderVoices() {
  const el = $("#voices");
  const q = state.voiceSearch.trim().toLowerCase();
  let picks, searching = q.length > 0;

  if (searching) {
    picks = allVoices().filter((v) =>
      v.text.toLowerCase().includes(q) ||
      v.tag.replace(/_/g, " ").toLowerCase().includes(q) ||
      DIM_META[v.dim].label.toLowerCase().includes(q)).slice(0, 40);
  } else {
    const mk = monthKey(state.current);
    picks = [];
    for (const dim of Object.keys(DIM_META)) {
      for (const [tag, n, snippet] of monthTagTotals(dim, mk)) {
        if (snippet) { picks.push({ dim, tag, mk, text: snippet }); break; }
      }
      if (picks.length >= 3) break;
    }
  }

  if (!picks.length) {
    el.innerHTML = `<div class="voices-empty">${searching
      ? `No quote matches “${escapeHTML(state.voiceSearch)}”${filtered() ? " in the selected countries" : ""}.`
      : "No narrative reporting captured for this month."}</div>`;
    $("#voice-count").textContent = "";
    return;
  }

  $("#voice-count").textContent = searching
    ? `${picks.length}${picks.length === 40 ? "+" : ""} across all months` : "";

  el.innerHTML = picks.map((p, i) => `<div class="voice${searching ? " voice-hit" : ""}"
      style="border-color:${DIM_META[p.dim].color}" data-month="${p.mk}" data-i="${i}">
      “…${searching ? highlight(p.text, q) : escapeHTML(p.text)}…”
      <div class="v-meta">${DIM_META[p.dim].label} · ${escapeHTML(p.tag.replace(/_/g, " "))} · ${monthLabel(p.mk)}</div>
    </div>`).join("");

  // Clicking a search result takes the whole dashboard to that month.
  if (searching)
    for (const node of el.querySelectorAll(".voice-hit"))
      node.addEventListener("click", () => goToMonth(node.dataset.month));
}

/* Quote text comes from PDFs, so it can contain anything. Everything drawn
   from it goes through here before it reaches innerHTML. */
function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* Wrap the matched words in a <mark>. The text is escaped first, and the
   query is escaped for the regular expression, so neither can inject markup. */
function highlight(text, q) {
  const safe = escapeHTML(text);
  if (!q) return safe;
  const re = new RegExp(escapeHTML(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return safe.replace(re, (m) => `<mark>${m}</mark>`);
}

/* Move the timeline to the first day of a month and redraw everything. */
function goToMonth(mk) {
  const t = Math.min(Math.max(Date.parse(mk + "-01"), START), state.endDate);
  state.current = t;
  $("#time-slider").value = Math.round((t - START) / DAY);
  renderAll();
}

/* A small bar chart of the six most-mentioned hazards this month. */
function renderTriggers() {
  const mk = monthKey(state.current), el = $("#triggers");
  const rows = monthTagTotals("hazard", mk).slice(0, 6);
  const max = rows.length ? rows[0][1] : 1;
  el.innerHTML = rows.length
    ? rows.map(([tag, n]) => `<div class="trigger-row">
        <div class="t-label"><span>${tag.replace(/_/g, " ")}</span><span class="t-n">${n}</span></div>
        <div class="trigger-bar"><div style="width:${Math.round((n / max) * 100)}%"></div></div></div>`).join("")
    : `<div style="font-size:12px;color:var(--muted)">No hazards reported this month.</div>`;
}

/* The scrolling timeline list on the right. Shows the 40 most recent events
   up to the current date, newest first; click one to fly the map to it. */
function renderEventList() {
  const t = state.current;
  const el = $("#event-list");
  el.innerHTML = "";
  /* Regional events stay in this list under any filter - they are the
     diplomatic and ceasefire record, which belongs to every country view. */
  const shown = state.data.events
    .filter((e) => Date.parse(e.date) <= t && (e.source === "curated" || e.severity >= 2))
    .filter((e) => e.country === "Regional" || countryOn(e.country))
    .slice(-40).reverse();
  for (const ev of shown) {
    const div = document.createElement("div");
    div.className = `event-item ${ev.source} ${ev.severity >= 4 ? "major" : ""}`;
    div.innerHTML = `<div class="ev-date">${fmtDate(Date.parse(ev.date))}${ev.location ? " · " + ev.location : ""}</div>
      <div class="ev-title">${ev.title}</div>`;
    // In split view, fly the half that is showing this event's country -
    // flying the other one would look like the click did nothing.
    if (ev.lat) div.addEventListener("click", () => mapShowing(ev.country).flyTo({ center: [ev.lon, ev.lat], zoom: 6 }));
    el.appendChild(div);
  }
}

/* ------------- layers built from the humanitarian open-data servers ------
 * (IOM-DTM and UNHCR via HDX, IPC, FEWS NET - see s06_external.py)
 * ----------------------------------------------------------------------- */

/* The date of the most recent reading on or before t, so a popup can say
   "as of 31 May 2026" rather than implying the number is from today. */
function lastDateOnOrBefore(series, t) {
  let d = "";
  for (const p of series) { if (Date.parse(p.date) <= t) d = p.date; }
  return d;
}

/* IPC food-insecurity map: show the analysis that was current on this date. */
function renderFoodsec() {
  if (!state.showFoodsec || !state.data.ipc) { setSource("ipc", empty()); return; }
  const d = ipcPeriodAt(state.current);
  setSource("ipc", d ? filterFC(state.data.ipc.periods[d]) : empty());
}

/* One bubble per locality (admin2) inside Sudan, sized by its IDP count. This
   is genuine per-location data from the IOM Displacement Tracking Matrix. */
function renderIDP() {
  // Every locality here is inside Sudan, so this layer has nothing to draw
  // when the filter excludes Sudan.
  if (!state.showIDP || !countryOn(SUDAN_ONLY)) { setSource("idp", empty()); return; }
  const t = state.current, feats = [];
  for (const L of state.data.idp_localities.localities) {
    const v = seriesAt(L.series, t);
    if (!v) continue;
    const dl = lastDateOnOrBefore(L.series, t);
    feats.push({
      type: "Feature", geometry: { type: "Point", coordinates: [L.lon, L.lat] },
      properties: {
        radius: Math.max(3, Math.min(38, Math.sqrt(v) / 45)),
        name: L.name, state: L.state, valFull: v.toLocaleString(),
        dateLabel: dl ? fmtDate(Date.parse(dl)) : "",
      },
    });
  }
  setSource("idp", { type: "FeatureCollection", features: feats });
}

/* The same idea one level up: one bubble per Sudanese state (admin1). */
function renderIDPStates() {
  if (!state.showIDPStates || !state.data.idp_states || !countryOn(SUDAN_ONLY)) {
    setSource("idp-states", empty());
    return;
  }
  const t = state.current, feats = [];
  for (const S of state.data.idp_states.states) {
    const v = seriesAt(S.series, t);
    if (!v) continue;
    const dl = lastDateOnOrBefore(S.series, t);
    feats.push({
      type: "Feature", geometry: { type: "Point", coordinates: [S.lon, S.lat] },
      properties: {
        radius: Math.max(4, Math.min(52, Math.sqrt(v) / 60)),
        name: S.name, valFull: v.toLocaleString(),
        dateLabel: dl ? fmtDate(Date.parse(dl)) : "",
      },
    });
  }
  setSource("idp-states", { type: "FeatureCollection", features: feats });
}

/* Two things at once: a big bubble per host country sized by its refugee
   total (the only level at which a time series exists), and small dots for
   individual camps, which appear on the map from the month they opened. */
function renderRefugees() {
  if (!state.showRefugees) {
    setSource("refcountry", empty());
    setSource("refcamps", empty());
    return;
  }
  const t = state.current, cfeats = [];
  for (const c of state.data.refugee_camps.countries) {
    if (!countryOn(c.country)) continue;
    const v = seriesAt(c.series, t);
    if (!v) continue;
    const dl = lastDateOnOrBefore(c.series, t);
    cfeats.push({
      type: "Feature", geometry: { type: "Point", coordinates: c.anchor },
      properties: {
        radius: Math.max(8, Math.min(58, Math.sqrt(v) / 22)),
        country: c.country, valFull: v.toLocaleString(),
        dateLabel: dl ? fmtDate(Date.parse(dl)) : "",
        note: c.note || "",
      },
    });
  }
  setSource("refcountry", { type: "FeatureCollection", features: cfeats });
  const cam = [];
  for (const m of state.data.refugee_camps.camps) {
    if (Date.parse(m.opened + "-01") > t || !countryOn(m.country)) continue;
    cam.push({
      type: "Feature", geometry: { type: "Point", coordinates: [m.lon, m.lat] },
      properties: { radius: 3 + m.size * 1.6, name: m.name, type: m.type,
                    country: m.country, opened: m.opened },
    });
  }
  setSource("refcamps", { type: "FeatureCollection", features: cam });
}

/* Border crossings. A crossing lights up when either of its corridors had
   people moving through it on this date. */
function renderCrossings() {
  if (!state.showCrossings) { setSource("crossings", empty()); return; }
  const t = state.current, feats = [];
  for (const c of state.data.crossings.points) {
    if (!corridorInScope(c.countries)) continue;
    let active = false, flow = 0;
    for (const cid of [c.corridor, c.return_corridor]) {
      const f = cid && state.data.flows[cid];
      if (!f) continue;
      const v = seriesAt(f.series, t);
      if (v) { active = true; flow = Math.max(flow, v); }
    }
    feats.push({
      type: "Feature", geometry: { type: "Point", coordinates: [c.lon, c.lat] },
      properties: { name: c.name, country: c.country, active,
                    flowLabel: flow ? flow.toLocaleString() : "" },
    });
  }
  setSource("crossings", { type: "FeatureCollection", features: feats });
}

/* The 14 IFRC Areas of Interest, coloured by their current IPC phase. */
function renderAOI() {
  setSource("aoi", state.showAOI ? filterFC(state.data.aoi) : empty());
}

const CAL_MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

/* The seasonal calendar strip: lean, rainy and harvest bands, with the month
   the timeline is currently in highlighted. */
function renderSeasonal() {
  const el = $("#seasonal-cal");
  if (!el || !state.data.seasonal) return;
  // FEWS NET publishes this calendar for Sudan, so it says nothing about a
  // selection that leaves Sudan out. Better to say so than to show Sudan's
  // rainy season under a heading that reads "Chad".
  if (!countryOn(SUDAN_ONLY)) {
    el.innerHTML = `<div class="panel-note">The seasonal calendar is published for Sudan only.
      Add Sudan to the country filter to see it.</div>`;
    return;
  }
  const cur = new Date(state.current).getMonth();   // 0-11
  let html = `<div class="cal-row cal-head"><span class="cal-label"></span>`;
  for (let m = 0; m < 12; m++)
    html += `<span class="cal-cell ${m === cur ? "cal-now" : ""}">${CAL_MONTHS[m]}</span>`;
  html += `</div>`;
  for (const it of state.data.seasonal.items) {
    html += `<div class="cal-row"><span class="cal-label" title="${it.note || ""}">${it.label}</span>`;
    for (let m = 1; m <= 12; m++) {
      const on = it.months.includes(m);
      html += `<span class="cal-cell ${m - 1 === cur ? "cal-now" : ""}"${on ? ` style="background:${it.color}"` : ""}></span>`;
    }
    html += `</div>`;
  }
  el.innerHTML = html;
}

/* Every layer of ONE map, for whatever scope is currently in force. */
function drawMapLayers() {
  renderFoodsec();
  renderFlows();
  renderCrossings();
  renderIDP();
  renderIDPStates();
  renderRefugees();
  renderEvents();
  renderThemes();
  /* The Areas of Interest used to be drawn only when their checkbox moved,
     because they do not change with the date. They do change with the country
     filter and with the split, so they are redrawn with everything else. */
  renderAOI();
}

/* Draw `fn` as one half: only this map, only this country. The scope is always
   put back, even if a render throws, so one bad layer cannot leave the whole
   dashboard stuck showing a single country. */
function withPane(m, country, fn) {
  renderTarget = m;
  renderScope = new Set([country]);
  try { fn(); } finally { renderTarget = null; renderScope = null; }
}

/* Fill the map, or both halves of it.

   Split view is the only interesting case: each half is drawn on its own, with
   its own country, so a feature that belongs to one country appears in that
   half alone. Everything else - one country, three, none - is a single scope
   written to every live map at once. */
function renderMapLayers() {
  const sel = [...state.countries];
  if (sel.length === 2 && mapB) {
    withPane(maps[0], sel[0], drawMapLayers);
    withPane(mapB, sel[1], drawMapLayers);
  } else {
    drawMapLayers();
  }
}

/* Redraw everything for state.current. This runs on every slider move, so
   each render*() function above must stay fast and must not fetch anything. */
function renderAll() {
  renderMapLayers();
  renderEventBanner();
  // The panels always describe the WHOLE selection, never one half of it.
  renderThemePanel(monthKey(state.current));
  renderStats();
  renderEventList();
  renderInsights();
  renderVoices();
  renderTriggers();
  renderSeasonal();
  renderDocCount();
  $("#current-date").textContent = fmtDate(state.current);
}

/* Everything renderAll() does, plus the things that only change when a FILTER
   changes rather than when the date does: the trend chart under the timeline
   and, if asked, the map viewport.

   Fitting the map is deliberately not part of renderAll(): renderAll runs
   about eight times a second while the timeline is playing, and re-fitting the
   camera at that rate would make the map unusable. */
function applyFilters({ refit = true } = {}) {
  renderAll();
  drawSparkline();
  if (refit) fitToSelection();
}

/* The mini line chart under the timeline. All three series share one vertical
   scale, so their relative sizes stay honest. Drawn with the plain HTML canvas
   API - no charting library involved. */
function drawSparkline() {
  const canvas = $("#sparkline");
  const w = (canvas.width = canvas.offsetWidth * devicePixelRatio);
  const hpx = (canvas.height = 48 * devicePixelRatio);
  const ctx = canvas.getContext("2d");
  const span = state.endDate - START;
  // all series share one scale so relative magnitudes stay honest
  const SERIES = [
    ["total_displaced", COLOR_OUT],
    ["cumulative_arrivals", COLOR_ACCENT],
    ["returns_to_sudan_total", COLOR_IN],
  ];
  const drawn = SERIES.map(([metric, color]) => [statSeries(metric), color]);
  const vmax = Math.max(...drawn.flatMap(([s]) => s.map((p) => p.value)), 1);
  for (const [s, color] of drawn) {
    if (s.length < 2) continue;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6 * devicePixelRatio;
    ctx.beginPath();
    s.forEach((p, i) => {
      const x = ((Date.parse(p.date) - START) / span) * w;
      const y = hpx - (p.value / vmax) * (hpx - 8) - 4;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }
  // defining events as ticks along the bottom
  ctx.fillStyle = "rgba(200,110,0,.85)";
  for (const ev of state.data.events.filter((e) =>
    e.source === "curated" && e.severity >= 4 && (e.country === "Regional" || countryOn(e.country)))) {
    const x = ((Date.parse(ev.date) - START) / span) * w;
    ctx.fillRect(x, hpx - 6 * devicePixelRatio, 1.5 * devicePixelRatio, 6 * devicePixelRatio);
  }
}

/* ========================= 6. TIMELINE ================================= */

/* Wire up the slider and the play button. The slider value is a number of days
   since 15 April 2023, which we turn back into a date. Play simply advances
   that number by 4 days every 120 milliseconds. */
function initTimeline() {
  const slider = $("#time-slider");
  const days = Math.round((state.endDate - START) / DAY);
  slider.max = days;
  slider.addEventListener("input", () => {
    state.current = START + Number(slider.value) * DAY;
    renderAll();
  });

  // year ticks
  const ticks = $("#slider-ticks");
  const y0 = 2023, y1 = new Date(state.endDate).getFullYear();
  for (let y = y0; y <= y1; y++) {
    const span = document.createElement("span");
    span.textContent = y;
    ticks.appendChild(span);
  }

  const play = $("#play-btn");
  let timer = null;
  play.addEventListener("click", () => {
    state.playing = !state.playing;
    play.textContent = state.playing ? "❚❚" : "▶";
    if (state.playing) {
      if (Number(slider.value) >= days) slider.value = 0;
      timer = setInterval(() => {
        const v = Number(slider.value) + 4;
        if (v >= days) {
          slider.value = days;
          state.playing = false; play.textContent = "▶";
          clearInterval(timer);
        } else slider.value = v;
        state.current = START + Number(slider.value) * DAY;
        renderAll();
      }, 120);
    } else clearInterval(timer);
  });
}

/* ========================= 7. CONTROLS ================================= */

/* Connect each sidebar checkbox to its layer. Note the food-security one: its
   file is about 2 MB, so we only download it the first time someone asks for
   it, and disable the checkbox while that happens. */
function initControls() {
  /* Each switch redraws the WHOLE map rather than only its own layer. That
     looks wasteful for a single checkbox, and would be, but for the split
     view: drawing one layer on its own has no half to draw it into, so it
     would write both countries' data into both halves and quietly undo the
     scoping. renderMapLayers() knows about the halves; a lone renderX() does
     not. It costs a few milliseconds and it is always right. */
  const layer = (id, key) =>
    $(id).addEventListener("change", (e) => { state[key] = e.target.checked; renderMapLayers(); });
  layer("#toggle-flows", "showFlows");
  layer("#toggle-returns", "showReturns");
  layer("#toggle-events", "showEvents");
  layer("#toggle-idp", "showIDP");
  layer("#toggle-idp-states", "showIDPStates");
  layer("#toggle-refugees", "showRefugees");
  layer("#toggle-crossings", "showCrossings");
  layer("#toggle-aoi", "showAOI");
  // Food security is the exception: its file is about 2 MB, so it is only
  // downloaded the first time someone asks for it.
  $("#toggle-foodsec").addEventListener("change", async (e) => {
    state.showFoodsec = e.target.checked;
    if (state.showFoodsec && !state.data.ipc) {
      e.target.disabled = true;
      state.data.ipc = await fetch("data/ipc_areas_fs.geojson").then((r) => r.json());
      // work out which country each area sits in, once, now that we have them
      deriveIPCCountries();
      e.target.disabled = false;
    }
    renderMapLayers();
  });
  // The key-events switch also empties the banner above the map.
  $("#toggle-events").addEventListener("change", renderEventBanner);
}

/* ---------------------------------------------------------------- dropdown
 * ONE searchable multi-select, built six times: once for the country filter
 * and once for each of the five narrative dimensions. Everything about how a
 * filter control behaves is decided here, so all six behave identically.
 *
 * The two ways to choose, as asked for:
 *   tick the box  -> add or remove this option, leaving the rest alone
 *   click the name -> select ONLY this option, clearing the others
 * ------------------------------------------------------------------------ */
function makeDropdown({ label, color, options, selected, onChange, placeholder }) {
  const root = document.createElement("div");
  root.className = "dd";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "dd-trigger";
  root.appendChild(trigger);

  const panel = document.createElement("div");
  panel.className = "dd-panel";
  panel.innerHTML = `
    <div class="dd-search"><input type="search" placeholder="${placeholder || "Search…"}" aria-label="${placeholder || "Search"}"></div>
    <div class="dd-actions"><button type="button" data-act="all">Select all</button>
      <button type="button" data-act="none">Clear</button>
      <span class="dd-shown"></span></div>
    <div class="dd-list" role="group" aria-label="${label}"></div>`;
  root.appendChild(panel);

  const search = panel.querySelector("input");
  const list = panel.querySelector(".dd-list");
  const shown = panel.querySelector(".dd-shown");

  // Draw the rows that match what has been typed in the search box.
  function paint() {
    // Every tick redraws the whole list, which would otherwise throw the
    // scroll position back to the top halfway down a long dimension.
    const scroll = list.scrollTop;
    const q = search.value.trim().toLowerCase();
    const hits = options.filter((o) => o.label.toLowerCase().includes(q));
    list.innerHTML = hits.length
      ? hits.map((o) => `<div class="dd-opt${selected.has(o.value) ? " on" : ""}" data-v="${escapeHTML(o.value)}">
          <input type="checkbox" class="dd-cb"${selected.has(o.value) ? " checked" : ""}
                 aria-label="${escapeHTML(o.label)}">
          ${o.color ? `<span class="dd-dot" style="background:${o.color}"></span>` : ""}
          <span class="dd-text" title="Show only this">${escapeHTML(o.label)}</span></div>`).join("")
      : `<div class="dd-empty">Nothing matches “${escapeHTML(search.value)}”.</div>`;
    shown.textContent = q ? `${hits.length} of ${options.length}` : "";
    list.scrollTop = scroll;
  }

  // The trigger always says what is currently chosen.
  function paintTrigger() {
    const n = selected.size;
    const chosen = options.filter((o) => selected.has(o.value));
    const text = n === 0 ? "All" : n === 1 ? chosen[0].label : `${n} selected`;
    trigger.innerHTML = `${color ? `<span class="dd-dot" style="background:${color}"></span>` : ""}
      <span class="dd-label">${escapeHTML(label)}</span>
      <span class="dd-value${n ? " on" : ""}">${escapeHTML(text)}</span>
      <span class="dd-caret">▾</span>`;
    root.classList.toggle("has-selection", n > 0);
  }

  function changed() { paint(); paintTrigger(); onChange(); }

  list.addEventListener("click", (e) => {
    const row = e.target.closest(".dd-opt");
    if (!row) return;
    const v = row.dataset.v;
    if (e.target.classList.contains("dd-cb")) {
      // the checkbox: add or remove, leave everything else as it is
      selected.has(v) ? selected.delete(v) : selected.add(v);
    } else {
      // the name: this one only - unless it already is the only one, in which
      // case clicking again clears it, so the control is never a dead end
      const only = selected.size === 1 && selected.has(v);
      selected.clear();
      if (!only) selected.add(v);
    }
    changed();
  });

  panel.querySelector('[data-act="all"]').addEventListener("click", () => {
    for (const o of options) selected.add(o.value);
    changed();
  });
  panel.querySelector('[data-act="none"]').addEventListener("click", () => {
    selected.clear();
    changed();
  });
  search.addEventListener("input", paint);
  search.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  const open = () => {
    // only one dropdown open at a time, or they overlap each other
    for (const other of document.querySelectorAll(".dd.open")) other.classList.remove("open");
    root.classList.add("open");
    search.value = ""; paint(); search.focus();
  };
  const close = () => root.classList.remove("open");
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    root.classList.contains("open") ? close() : open();
  });
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  paint(); paintTrigger();
  return { el: root, refresh: () => { paint(); paintTrigger(); } };
}

/* ------------------------------------------------------------- the filters */

let countryDropdown = null;

/* The country filter in the top bar, plus the chips under it that show what is
   selected and let you take one off again. */
function initCountryFilter() {
  const wrap = $("#country-filter");
  countryDropdown = makeDropdown({
    label: "Countries",
    options: COUNTRIES.map((c) => ({ value: c, label: c })),
    selected: state.countries,
    placeholder: "Search countries…",
    onChange: () => { renderCountryChips(); applyFilters(); },
  });
  wrap.appendChild(countryDropdown.el);
  renderCountryChips();
}

function renderCountryChips() {
  const el = $("#country-chips");
  const sel = [...state.countries];
  el.innerHTML = sel.length
    ? sel.map((c) => `<button type="button" class="chip" data-c="${escapeHTML(c)}"
         title="Remove ${escapeHTML(c)} from the filter">${escapeHTML(c)}<span>×</span></button>`).join("") +
      `<button type="button" class="chip chip-clear" data-c="*">Clear all</button>`
    : "";
  for (const btn of el.querySelectorAll(".chip"))
    btn.addEventListener("click", () => {
      btn.dataset.c === "*" ? state.countries.clear() : state.countries.delete(btn.dataset.c);
      countryDropdown.refresh();
      renderCountryChips();
      applyFilters();
    });
  // tell the reader what the split view is doing, in words
  const mode = $("#filter-mode");
  mode.textContent = sel.length === 0 ? "Whole region"
    : sel.length === 1 ? `Zoomed to ${sel[0]}`
    : sel.length === 2 ? `Split view: ${sel[0]} | ${sel[1]} · zoom only, panning locked`
    : `${sel.length} countries, fitted to all`;
}

/* Build the theme filters from the data itself: one searchable dropdown per
   dimension, holding every tag the pipeline actually found. Add a new tag to
   taxonomy.json and it appears here on the next run, with no code change. */
function initThemeControls() {
  const wrap = $("#dim-groups");
  for (const [dim, meta] of Object.entries(DIM_META)) {
    const tags = Object.keys(state.data.tags[dim] || {}).sort();
    if (!tags.length) continue;
    /* activeTags is one flat set of "dimension|tag" keys shared by all five
       dropdowns, so each one is given a small view onto just its own slice of
       it. Select-all and Clear then act on that dimension alone. */
    const view = {
      has: (tag) => state.activeTags.has(`${dim}|${tag}`),
      add: (tag) => state.activeTags.add(`${dim}|${tag}`),
      delete: (tag) => state.activeTags.delete(`${dim}|${tag}`),
      clear: () => { for (const tag of tags) state.activeTags.delete(`${dim}|${tag}`); },
      get size() { return tags.filter((tag) => state.activeTags.has(`${dim}|${tag}`)).length; },
    };
    const dd = makeDropdown({
      label: meta.label,
      color: meta.color,
      options: tags.map((tag) => ({ value: tag, label: tag.replace(/_/g, " "), color: meta.color })),
      selected: view,
      placeholder: `Search ${meta.label.toLowerCase()}…`,
      /* Redraw EVERYTHING, not just the map: a theme filter changes the
         panel, Trends, Community Insights and Top hazards too. The polygons
         are fetched on the first tick and the map redrawn again once they
         arrive, so the panels update immediately and do not wait on 3 MB. */
      onChange: () => {
        applyFilters({ refit: false });
        if (state.activeTags.size) loadAreas().then(renderMapLayers);
      },
    });
    wrap.appendChild(dd.el);
  }
}

/* The search box on the Community Insights panel. */
function initVoiceSearch() {
  const input = $("#voice-search");
  input.addEventListener("input", () => {
    state.voiceSearch = input.value;
    renderVoices();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; state.voiceSearch = ""; renderVoices(); }
  });
}

/* ------------------------------------------------------- map fit and split */

/* Which map is currently showing this country? Always the first one, unless
   the map is split and the country is the one in the right-hand half. */
function mapShowing(country) {
  const sel = [...state.countries];
  return sel.length === 2 && country === sel[1] && mapB ? mapB : maps[0];
}

/* Hold a half still.

   In split view the two halves each stand for one country, and dragging one of
   them away from its country makes the comparison meaningless without it
   being obvious that anything has moved. So panning is switched off and only
   zoom is left - anchored on the CENTRE rather than the pointer, which is what
   keeps the country in the middle while you zoom. The zoom buttons in the
   corner already work this way.

   Everything switched off here is switched back on when the map is not split,
   so the single-map view keeps behaving normally. */
function setPanLock(m, locked) {
  if (!m) return;
  if (locked) {
    m.dragPan.disable();
    m.dragRotate.disable();
    m.keyboard.disable();
    m.doubleClickZoom.disable();          // would re-centre on the pointer
    m.scrollZoom.enable({ around: "center" });
    m.touchZoomRotate.enable({ around: "center" });
    m.touchZoomRotate.disableRotation();
  } else {
    m.dragPan.enable();
    m.keyboard.enable();
    m.doubleClickZoom.enable();
    m.scrollZoom.enable();
    m.touchZoomRotate.enable();
  }
  m.getContainer().classList.toggle("pan-locked", locked);
}

/* Point one map at a set of bounds. */
function fitMap(m, bounds) {
  if (!m) return;
  m.fitBounds(bounds, { padding: 28, duration: 700, maxZoom: 7 });
}

/* Bring the second map into being, or put it away again.

   It is built the first time two countries are selected and kept afterwards,
   because creating a MapLibre map and its twenty-odd layers is far more
   expensive than hiding a div. The container is shown BEFORE the map is
   constructed: MapLibre measures its container on creation, and a hidden one
   measures zero. */
async function ensureSplit(on) {
  const wrap = $("#map-wrap");
  wrap.classList.toggle("split", on);
  if (on && !mapB) {
    mapB = await initMap("map-b");
    addLayers(mapB);
    maps.push(mapB);
  }
  // Panning is locked while split and released the moment it is not.
  for (const m of maps) { setPanLock(m, on); m.resize(); }
  // Both halves have to be redrawn on the way in AND on the way out: what each
  // one shows depends on whether the map is split, not only on the filter.
  renderMapLayers();
}

/* Put the map where the country filter says it should be. This is the rule the
   dashboard was asked for:
     nothing selected -> the whole region
     one country      -> zoom to it
     two countries    -> split the map and show one in each half
     three or more    -> back to one map, zoomed out to fit them all           */
async function fitToSelection() {
  const sel = [...state.countries];
  await ensureSplit(sel.length === 2);
  if (sel.length === 2) {
    $("#map-a-label").textContent = sel[0];
    $("#map-b-label").textContent = sel[1];
    fitMap(maps[0], boundsFor([sel[0]]));
    fitMap(mapB, boundsFor([sel[1]]));
  } else {
    fitMap(maps[0], sel.length ? boundsFor(sel) : REGION_BOUNDS);
  }
}

/* ========================= 8. BOOT =====================================
 * The starting point. Everything above is a definition; these lines run.
 * ======================================================================== */
(async function boot() {
  // Download the data and create the first map at the same time, then wire up.
  const [, first] = await Promise.all([loadData(), initMap("map-a")]);
  map = first;
  maps.push(map);
  addLayers(map);
  initTimeline();
  initControls();
  initCountryFilter();
  initThemeControls();
  initVoiceSearch();
  drawSparkline();
  window.addEventListener("resize", () => {
    drawSparkline();
    for (const m of maps) m.resize();
  });
  // open the story at the beginning
  renderAll();
})();
