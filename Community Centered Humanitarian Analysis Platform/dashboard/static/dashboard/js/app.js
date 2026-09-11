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

/* The seasonal calendar and the food-security files are keyed by ISO3, because
   that is how the database stores them. This turns the dropdown's country name
   into that key. */
const COUNTRY_TO_ISO3 = {
  "Sudan": "SDN", "Chad": "TCD", "Egypt": "EGY", "Ethiopia": "ETH",
  "Libya": "LBY", "South Sudan": "SSD", "Uganda": "UGA",
  "Central African Republic": "CAF", "Eritrea": "ERI",
};

/* Corridor ids in flows.json are built from country slugs - "sudan-chad",
   "chad-sudan-return", "south_sudan-sudan-influx". This turns a slug back into
   the country name the rest of the dashboard uses. */
const SLUG_TO_COUNTRY = {
  sudan: "Sudan", chad: "Chad", egypt: "Egypt", libya: "Libya",
  ethiopia: "Ethiopia", uganda: "Uganda", eritrea: "Eritrea",
  south_sudan: "South Sudan", car: "Central African Republic",
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
// Humanitarian service points. Deliberately not one of the pillar colours:
// a service is a response, not a finding about a place.
const COLOR_HSP = paletteColor("--hsp", "#6b3a90");

/* The four theme groups, their display names and their colours. These match
   the "dimension" values the pipeline writes into tags.json, and each one is
   given the IFRC thematic palette that means the same thing.

   THIS OBJECT IS THE SWITCH. Every panel that shows narrative reporting - the
   theme dropdowns, the map pillars, the area popups, Community Insights, the
   theme detail list - walks DIM_META or DIM_ORDER, so a dimension that is not
   named here does not appear anywhere on the page.

   movement_pattern used to be the fifth. It was reporting ABOUT movement,
   counted in mentions, sitting beside a map and a headline row that carry the
   movement itself, counted in people - and the two never agreed. The mention
   counts stay in tags.json; the dashboard now says what it knows about
   movement with the Movement trends graph, which plots people. */
const DIM_META = {
  hazard: { label: "Hazards", color: paletteColor("--dim-hazard", "#d22730") },
  vulnerability: { label: "Vulnerabilities", color: paletteColor("--dim-vulnerability", "#6b3a90") },
  coping: { label: "Coping mechanisms", color: paletteColor("--dim-coping", "#009775") },
  need: { label: "Needs", color: paletteColor("--dim-need", "#1874a0") },
};

/* The order the pillar bands are nested in, outermost first. Hazards are
   outside because they are the thing that happens TO a place; the pillars that
   describe the people there sit within it. */
const DIM_ORDER = ["hazard", "vulnerability", "coping", "need"];
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
  voiceTab: "community",   // which Community Insights tab is showing
  /* The three lines of the Movement trends graph, worked out once per FILTER
     change rather than per timeline move - see computeTrendSeries(). */
  trend: { series: [], vmax: 1 },
  // Which layers are switched on. These match the checkboxes in index.html.
  showFlows: true, showReturns: true, showEvents: true,
  showIDP: false, showIDPStates: false, showRefugees: false, showFoodsec: false,
  showCrossings: true, showAOI: false, showHSP: false,
};

/* ========================= 2. HELPERS =================================== */

/* IPC republishes its food-security map a few times a year. This finds the
   most recent published version that existed on the timeline date `t`. */
function ipcPeriodAt(t, payload) {
  const dates = (payload && payload._meta && payload._meta.dates) || [];
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
  if (w > e) return HOME_BOUNDS;     // nothing recognised - show the region
  const pad = 0.6;
  // Clamp to the LOCK, not to home: fitting to a box the map may not pan to
  // would leave MapLibre quietly framing something else.
  return [
    [Math.max(PAN_BOUNDS[0][0], w - pad), Math.max(PAN_BOUNDS[0][1], s - pad)],
    [Math.min(PAN_BOUNDS[1][0], e + pad), Math.min(PAN_BOUNDS[1][1], n + pad)],
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

  /* The Areas of Operation name their country by ISO3 ("TCD", "SDN"), which is
     what build_aoi writes and what admin_areas stores. This was reading them
     through a two-letter table, so EVERY area resolved to null - and because
     filterFC() keeps a feature only when its .country is in scope, picking any
     country at all emptied the layer completely. */
  for (const f of (state.data.aoi || { features: [] }).features)
    f.properties.country = ISO3_TO_COUNTRY[f.properties.ipc_country] || null;
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

/* Keep only the areas in the selected countries. Returns the collection
   unchanged when no filter is on, so the common case copies nothing. */
function filterFC(fc) {
  if (!filtered() || !fc) return fc;
  const s = scopeCountries();
  return { type: "FeatureCollection",
           features: fc.features.filter((f) => s.has(f.properties.country)) };
}

/* ---------------------------------------------------------------- sidebars
   Both sidebars can be dragged wider. The panels carry long place names, whole
   quotes and the ACAPS seasonal descriptions, and at their default width those
   wrap awkwardly - but the default is deliberately unchanged, so the page opens
   exactly as it always has and only widens when someone asks it to.

   The chosen width is remembered per browser. It is a reading preference, not
   data: if localStorage is unavailable or the stored value is nonsense, the
   default stands and nothing breaks.
*/
const SIDEBAR_LIMITS = {
  sidebar:  { varName: "--sidebar-w",  min: 260, max: 720, def: 320, edge: "right" },
  rightbar: { varName: "--rightbar-w", min: 240, max: 640, def: 290, edge: "left" },
};

/* How much smaller than life the page is being drawn - app.css sets zoom on
   <body> from --ui-scale so the dashboard opens at the size it was designed at
   (see the --ui-scale block there). Measured, not read from the property, and
   the same measurement MapLibre makes for its own pointer maths: the rendered
   width against the laid-out width. Returns 1 when nothing is scaled. */
function uiScale() {
  const b = document.body;
  return b.getBoundingClientRect().width / b.offsetWidth || 1;
}

function initSidebarResize() {
  for (const [id, cfg] of Object.entries(SIDEBAR_LIMITS)) {
    const el = document.getElementById(id);
    if (!el) continue;

    const stored = Number(safeGet(`width:${id}`));
    if (stored >= cfg.min && stored <= cfg.max)
      document.documentElement.style.setProperty(cfg.varName, `${stored}px`);

    const grip = document.createElement("div");
    grip.className = "side-grip";
    grip.title = "Drag to resize · double-click to reset";
    el.appendChild(grip);

    let startX = 0, startW = 0;

    const onMove = (ev) => {
      // The left sidebar grows as the pointer moves right; the right one grows
      // as it moves left, so the delta is signed by which edge is being pulled.
      // Divided by uiScale() because the pointer is reported in real screen
      // pixels while the width we set is a laid-out one - without it the edge
      // moves only 80% as far as the cursor and the grip slides out from under
      // the hand. Measured rather than read from --ui-scale so it is 1, and
      // this a no-op, if the page is ever drawn at its natural size again.
      const raw = cfg.edge === "right" ? ev.clientX - startX : startX - ev.clientX;
      const delta = raw / uiScale();
      const w = Math.round(Math.min(cfg.max, Math.max(cfg.min, startW + delta)));
      document.documentElement.style.setProperty(cfg.varName, `${w}px`);
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.classList.remove("resizing");
      grip.classList.remove("dragging");
      const w = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue(cfg.varName), 10);
      safeSet(`width:${id}`, String(w));
      // The map canvas is sized in pixels, so it has to be told the viewport
      // changed - otherwise it keeps the old width and the picture stretches.
      resizeMaps();
    };

    grip.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      startX = ev.clientX;
      startW = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue(cfg.varName), 10) || cfg.def;
      document.body.classList.add("resizing");
      grip.classList.add("dragging");
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });

    grip.addEventListener("dblclick", () => {
      document.documentElement.style.setProperty(cfg.varName, `${cfg.def}px`);
      safeSet(`width:${id}`, String(cfg.def));
      resizeMaps();
    });
  }
}

/* Both map panes, told that their box changed. */
function resizeMaps() {
  for (const m of maps) { try { m.resize(); } catch (e) { /* not ready yet */ } }
}

/* localStorage can throw outright - a private window, or site data blocked - so
   a remembered width must never be able to stop the dashboard loading. */
function safeGet(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function safeSet(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* preference only */ }
}

/* ========================= 3. LOAD ===================================== */

/* Fetch every data file once, at start-up, and remember it in state.data.
   Promise.all downloads them all at the same time rather than one by one. */
async function loadData() {
  const names = ["meta", "flows", "headline", "events", "tags", "documents",
                 "crossings", "idp_localities", "idp_states", "refugee_camps", "seasonal"];
  const res = await Promise.all(names.map((n) => fetch(`data/${n}.json`).then((r) => r.json())));
  names.forEach((n, i) => (state.data[n] = res[i]));
  // boundary context layers (country outlines, state lines, IFRC Areas of Operation + IPC)
  const [admin0, admin1, aoi, hsps] = await Promise.all([
    fetch("data/boundaries/admin0.geojson").then((r) => r.json()),
    fetch("data/boundaries/admin1_lines.geojson").then((r) => r.json()),
    fetch("data/aoi_ipc.geojson").then((r) => r.json()),
    fetch("data/hsps.geojson").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  state.data.admin0 = admin0; state.data.admin1 = admin1; state.data.aoi = aoi;
  state.data.hsps = hsps;
  // Community insights are the one panel that reads the database live, so a
  // statement published in Admin appears on the next refresh. Failure is not
  // fatal: the panel falls back to the analyst snippets from tags.json.
  state.data.insights = await fetch("api/insights/?limit=2000")
    .then((r) => (r.ok ? r.json() : { results: [] }))
    .then((body) => body.results)
    .catch(() => []);
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

/* TWO DIFFERENT BOXES, and they used to be one - which is why panning out to
   the rest of Africa was impossible without also changing where the map opens.

   PAN_BOUNDS is the LOCK: how far a user may pan and zoom out. It is now the
   whole continent, so neighbouring and coastal countries can be looked at in
   context. The edges take in the islands as well as the mainland - Cape Verde
   reaches 25.4°W and Mauritius 57.8°E, so a mainland-only box (17.5°W to
   51.4°E) would clip them off - with a degree of slack so the outermost
   coastlines are not pinned against the edge of the viewport.

   HOME_BOUNDS is the VIEW: where the map points with no country selected. That
   stays the operational region, because opening on the whole continent would
   push Sudan down to a thumbnail and bury the detail this dashboard exists to
   show. Widening the lock is not the same as changing the subject.

   HOME_BOUNDS's top edge is 34.5°N rather than the region's 32°N because Libya
   reaches 33.18°N: with a lower cap, fitBounds() would silently clamp and never
   frame Libya properly. */
const PAN_BOUNDS  = [[-26.0, -37.0], [64.0, 39.0]];
const HOME_BOUNDS = [[8.0, -3.0], [56.0, 34.5]];

/* ---- Talking to Mapbox --------------------------------------------------

   The basemap under everything else is the official IFRC GO basemap
   ("LIVE - GO - IFRC Basemap v1"), hosted by Mapbox and shared with go.ifrc.org
   so our map reads as an IFRC map. It is named in config/settings.py and
   reaches us through window.BASEMAP, set by the template.

   There is one wrinkle. Mapbox styles address their own pieces with a private
   "mapbox://" scheme instead of ordinary web addresses:

       style   mapbox://styles/go-ifrc/ckrfe16ru4c8718phmckdfjh0
       sprite  mapbox://sprites/go-ifrc/ckrfe16ru4c.../e0kzxuqku4v...
       fonts   mapbox://fonts/mapbox/{fontstack}/{range}.pbf
       source  mapbox://go-ifrc.go-districts-1,go-ifrc.go-countries,...

   Mapbox's own library understands that scheme. MapLibre - the free library we
   draw with - deliberately does not, so left alone it would ask the browser for
   "mapbox://..." and get nothing back: a blank grey map.

   MapLibre hands EVERY address it is about to fetch to transformRequest first,
   which is where mapboxUrl() below steps in and rewrites the four shapes above
   into the real https addresses, adding the access token. Tiles themselves need
   no rewriting: the tile list Mapbox sends back already carries the token. */
const MAPBOX_API = "https://api.mapbox.com";

/* Rewrite one "mapbox://" address into the https one it stands for. Anything
   that is not a mapbox:// address (our own GeoJSON, the tile requests) comes
   back untouched. */
function mapboxUrl(url, token) {
  if (!url.startsWith("mapbox://")) return url;
  const rest = url.slice("mapbox://".length);
  const sign = (u) => `${MAPBOX_API}${u}${u.includes("?") ? "&" : "?"}access_token=${token}`;

  // mapbox://styles/go-ifrc/ckrfe...  ->  /styles/v1/go-ifrc/ckrfe...
  if (rest.startsWith("styles/")) return sign(`/styles/v1/${rest.slice(7)}`);

  // mapbox://fonts/mapbox/Poppins Regular/0-255.pbf  ->  /fonts/v1/mapbox/...
  if (rest.startsWith("fonts/")) return sign(`/fonts/v1/${rest.slice(6)}`);

  /* mapbox://sprites/go-ifrc/ckrfe.../e0kz...  ->  /styles/v1/.../sprite
     MapLibre appends "@2x" and ".png" or ".json" before we ever see it, and
     those must end up AFTER the word "sprite", not after the style id - which
     is the part that is easy to get wrong. */
  if (rest.startsWith("sprites/")) {
    const m = rest.slice(8).match(/^(.+?)(@[0-9]+x)?\.(png|json)$/);
    if (m) return sign(`/styles/v1/${m[1]}/sprite${m[2] || ""}.${m[3]}`);
  }

  // Anything else is a list of tileset ids; ask for its tile catalogue.
  return sign(`/v4/${rest}.json?secure`);
}

/* Create one map on the IFRC GO basemap, locked to Africa so a user cannot
   accidentally pan away to Europe, but opening on the operational region.
   Resolves once the style has loaded, because layers cannot be added before
   then. */
function initMap(containerId) {
  const basemap = window.BASEMAP || {};
  const m = new maplibregl.Map({
    container: containerId,
    style: basemap.style,
    transformRequest: (url) => ({ url: mapboxUrl(url, basemap.token) }),
    center: [29.5, 15.2],
    zoom: 4.35,
    // 2.5, not 3: at zoom 3 a short viewport cannot fit Africa's 76 degrees of
    // latitude, so the new lock would be unreachable from inside the old floor.
    minZoom: 2.5,
    maxBounds: PAN_BOUNDS,
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

  // ---- boundary context: state lines, country outlines, IFRC Areas of Operation ----
  m.addSource("admin1lines", { type: "geojson", data: state.data.admin1 || empty() });
  m.addLayer({
    id: "admin1-line", type: "line", source: "admin1lines",
    paint: { "line-color": "#bfc4cb", "line-width": 0.6, "line-dasharray": [2, 2] },
  });
  m.addSource("aoi", { type: "geojson", data: empty() });
  /* OUTLINE ONLY. This fill is deliberately invisible and is deliberately still
     here: it is the click target for the area popup (a line layer only catches
     clicks within a couple of pixels of the edge, so without it the popup would
     be unreachable everywhere except on the boundary itself). The IPC phase it
     used to be shaded by is still read - and still named, in the popup - it is
     just no longer painted, because a per-phase fill made the Areas of
     Operation look like fourteen different kinds of thing. */
  m.addLayer({
    id: "aoi-fill", type: "fill", source: "aoi",
    paint: { "fill-color": "rgba(0,0,0,0)", "fill-opacity": 0 },
  });
  m.addLayer({
    id: "aoi-line", type: "line", source: "aoi",
    paint: { "line-color": COLOR_EVENT, "line-width": 1.2 },
  });
  /* The national wash. About two-thirds of tagged reporting names no place
     ("shelter needs remain acute across Chad"), and that reporting is real. It
     shades the whole country in NEUTRAL GREY, darker where there is more of
     it. Grey deliberately: the pillar colours belong to the bands, so a
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

     DRAWN EXACTLY LIKE THE IPC CHOROPLETH: a solid fill and a thin dark
     hairline on the admin area, and NOTHING ELSE ON THE EDGE. That last clause
     is the whole lesson of this layer's history.

     WHAT MADE IT LOOK BLOBBY WAS NEVER THE GEOMETRY. The pillars used to draw
     line bands inset from the boundary with line-offset, one step further
     per pillar. line-offset is measured in PIXELS, and at the zoom where a
     Sudanese state fills the screen one pixel is two to five kilometres - so an
     offset of 3.5 to 14px pushed the outline ten to seventy kilometres off the
     boundary, rounding every corner and doubling every edge. The polygons
     underneath were fine all along: the areas this layer draws carry about 27
     vertices per 100km of edge, against 22 for the IPC areas beside them.
     Simplification runs at 550m, a fifth of a pixel at that zoom, and cannot
     bulge anything.

     SO CONVERGENCE MOVED OFF THE EDGE. The pillars are still meant to be
     read together, but an area now shows the HIGHEST-PRECEDENCE pillar reported
     on it and says the rest in its popup, which lists every pillar with its
     tags and counts. Trying to say "three pillars converge here" in the outline
     is what kept the layer unreadable for anyone trying to see where anything
     was at all.

     One source holds all 336 polygons and is set once. What each pillar shows
     on it is carried by FEATURE STATE rather than by four copies of the
     geometry - see renderThemes().

     SEEDED FROM WHAT IS ALREADY LOADED, and this is not optional. Every other
     layer here is filled by a render function, so a map built later fills
     itself on the next redraw. This one is filled ONCE, by loadAreas(), which
     hands the geometry only to the maps that exist the moment its download
     finishes. The second half of the split view is built later than that - the
     first time two countries are picked - so starting it empty left it empty
     for good: renderThemes() then wrote feature states onto features that were
     not there, and the right-hand half could never highlight anything. */
  m.addSource("areas", {
    type: "geojson", data: state.data.areas || empty(), promoteId: "id",
  });
  // The fill, in the leading pillar's colour. Keeps the id "area-wash" because
  // the popup is bound to it; it is no longer a wash in anything but name.
  m.addLayer({
    id: "area-wash", type: "fill", source: "areas",
    paint: {
      "fill-color": ["coalesce", ["feature-state", "topColor"], "rgba(0,0,0,0)"],
      "fill-opacity": ["coalesce", ["feature-state", "wash"], 0],
    },
  });
  /* The hairline that makes a fill read as a place rather than a smudge - the
     same one IPC's areas get. Its opacity is on feature state, NOT a constant:
     an outline drawn on all 245 areas would put a permanent mesh over the map
     and break the rule that admin levels are colourless until a pillar asks
     for them. Only a lit area gets an edge. */
  m.addLayer({
    id: "area-line", type: "line", source: "areas",
    paint: {
      "line-color": "#0e1116", "line-width": 0.5,
      "line-opacity": ["coalesce", ["feature-state", "edge"], 0],
    },
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
    `<b style="color:${COLOR_EVENT}">${fmtDate(Date.parse(p.date))}</b><br><b>${p.title}</b><br>${p.description || ""}`, "Key event");
  popup(m, "flow-lines", (p) =>
    `<b>${p.name}</b><br>${p.kind}<br><b style="color:${p.color}">${p.labelFull}</b> people (cumulative)`, "Movement corridor");

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

  // ---- humanitarian service points ----
  // Drawn as a ring whose size grows with the number of services offered, so a
  // district doing eight things reads as busier than one doing one.
  m.addSource("hsps", { type: "geojson", data: empty() });
  m.addLayer({
    id: "hsp-dots", type: "circle", source: "hsps",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "n_services"], 1, 5, 11, 12],
      "circle-color": COLOR_HSP,
      "circle-opacity": 0.75,
      "circle-stroke-color": WHITE, "circle-stroke-width": 1.6,
    },
  });

  // ---- border crossings ----
  m.addSource("crossings", { type: "geojson", data: empty() });
  m.addLayer({
    id: "crossing-dots", type: "circle", source: "crossings",
    /* THE SAME DOT THE TOGGLE SHOWS: white, one thin muted ring, 10px across -
       .dot-swatch in app.css to the pixel. A crossing used to swell to a red
       disc on dates when people moved through it, which meant the legend's dot
       and the map's dot were two different marks and neither one was "a border
       crossing". Whether a corridor is moving today is now said in the popup,
       where it can be said in people rather than in radius. */
    paint: {
      "circle-radius": 5,
      "circle-color": WHITE,
      "circle-stroke-color": COLOR_MUTED, "circle-stroke-width": 1,
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
    <b style="color:${COLOR_IDP_LOCALITY}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM via HDX</span>`, "IDPs — locality");
  popup(m, "idp-state-circles", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(Sudan — state level)</span><br>
    <b style="color:${COLOR_IDP_STATE}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM / UNHCR (Sudan IDPs.xlsx)</span>`, "IDPs — state");
  popup(m, "ref-country", (p) => `<b style="color:${COLOR_IN_HOST}">${p.country}</b><br>
    <b>${p.valFull}</b> Sudanese refugees · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">UNHCR${p.note ? " · " + p.note : ""}</span>`, "Refugees — country total");
  popup(m, "ref-camps", (p) => `<b style="color:${COLOR_IN_HOST}">${p.name}</b><br>${p.type} · ${p.country}<br>
    Opened ${p.opened}<br><span style="color:${COLOR_MUTED}">Location curated (UNHCR RRP); magnitude shown by country total</span>`, "Refugee site");
  /* The highlighted area. Returns null when nothing was reported here, so
     hovering an unhighlighted state stays silent rather than showing an empty
     box - every one of the 336 polygons is in this layer, only some are lit. */
  popup(m, "area-wash", (p) => {
    const detail = (state.areaDetail || {})[p.id];
    if (!detail) return null;
    const month = monthLabel(state.areaMonth || monthKey(state.current));
    let html = `<div class="pp-head"><b>${escapeHTML(p.name)}</b>
      <span class="pp-sub">${escapeHTML(p.country || "IFRC area of interest")}${
        p.level === "adm2" ? " · locality" : p.level === "adm1" ? " · state" : ""} · ${month}</span></div>`;
    for (const dim of DIM_ORDER) {
      const tags = detail[dim];
      if (!tags) continue;
      const rows = Object.entries(tags).sort((a, b) => b[1] - a[1]);
      const total = rows.reduce((a, r) => a + r[1], 0);
      html += `<div class="pp-dim" style="border-color:${DIM_META[dim].color}">
        <div class="pp-dim-h" style="color:${DIM_META[dim].color}">${DIM_META[dim].label}
          <span class="pp-n">${total} mention${total > 1 ? "s" : ""}</span></div>` +
        rows.map(([tag, n]) =>
          `<div class="pp-row"><span>${escapeHTML(tag.replace(/_/g, " "))}</span><span class="pp-n">${n}</span></div>`).join("");
      // A sentence from the reporting behind the biggest tag, so the number is
      // never the only thing offered as evidence.
      const td = (state.data.tags[dim] || {})[rows[0][0]];
      const quote = td && snippetFor(td, state.areaMonth || monthKey(state.current));
      if (quote) html += `<div class="pp-quote">“…${escapeHTML(quote.slice(0, 180))}…”</div>`;
      html += `</div>`;
    }
    if ((p.water || []).length)
      html += `<div class="pp-water">Water nearby: ${escapeHTML((p.water || []).slice(0, 4).join(", "))}</div>`;
    html += `<div class="pp-note">Counts are mentions in the reporting for this month,
      not people affected — the source documents do not give a per-hazard caseload.
      Switch on the IDP or IPC layers for population figures.</div>`;
    return html;
  }, "Community reporting");
  popup(m, "water-core", (p) =>
    `<b style="color:${COLOR_WATER}">${escapeHTML(p.name)}</b>
     <span class="pp-sub">${p.kind}</span>`, "Water");

  popup(m, "crossing-dots", (p) => `<b>${p.name}</b><br>Crossing to ${p.country}<br>
    ${p.active ? `<b style="color:${COLOR_EVENT}">Active corridor</b> — ${p.flowLabel} people moved (cumulative)` : "No recorded movement at this date"}`, "Border crossing");
  popup(m, "ipc-fill", (p) => `<b>${p.area}</b><br>IPC <b>Phase ${p.ph}</b>${p.fam ? ` · <b style="color:${COLOR_ACCENT}">Famine (P5)</b>` : ""}<br>
    ${p.p3 != null ? `<b>${Math.round(p.p3 * 100)}%</b> in Phase 3+ (Crisis or worse)<br>` : ""}
    ${sourceLine(p.src)}`, "Food security");
  popup(m, "hsp-dots", (p) => {
    const services = (typeof p.services === "string" ? JSON.parse(p.services) : p.services) || [];
    return `<b>${escapeHTML(p.place)}</b> <span style="color:${COLOR_MUTED}">(${escapeHTML(p.country || "")})</span><br>
      <b>${p.n_services}</b> service${p.n_services === 1 ? "" : "s"} offered in this district<br>
      <span style="color:${COLOR_MUTED}">${services.map(escapeHTML).join(" · ")}</span><br>
      <span style="color:${COLOR_MUTED}">District-level: the source publishes no site coordinates.</span><br>
      ${sourceLine("kobo", "reported " + (p.date_reported || ""))}`;
  }, "Humanitarian service points");
  /* WHERE IFRC WORKS, AND NOTHING ELSE. This bubble used to go on to report the
     worst IPC phase inside the area and the share of its sub-areas in Phase 3+.
     That is a food-security finding; the IPC layer two rows up in the layer
     control exists to say it, says it per area rather than per operation, and
     says it in IPC's own colours. Repeating it here made an IFRC operational
     boundary read as an IPC classification of its own - the same confusion the
     per-phase fill on this layer used to cause before it was taken off.

     The joined phase is still computed and still in the file (see
     s06_mcp_layers.build_aoi); it is simply not this layer's to tell. */
  popup(m, "aoi-fill", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.country || ""})</span><br>
    <b style="color:${COLOR_EVENT}">IFRC Area of Operation</b>`, "IFRC area of operation");

  // Every layer has now said what it would show. From here the registry is
  // closed, and one handler per map serves all of them from a single bubble.
  popupSpecsBuilt = true;
  bindPopups(m);
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
      maxWidth: "330px",
    }));
  return hoverBubbles.get(m);
}

/* ===================== ONE BUBBLE, NOT FIVE =============================
 * The layers on this map deliberately sit on top of each other: a state can
 * carry a hazard band, a vulnerability band, an IPC phase, IDP figures and a
 * river, all at the same point. Giving each its own popup meant several bubbles
 * stacked on one another, four of them unreadable.
 *
 * So nothing binds its own popup. Each layer REGISTERS what it would say, and
 * one handler per map asks "what is under the cursor?" and writes a single
 * bubble with a section for each answer, in the order below.
 *
 * Hovering shows it. Clicking PINS it: the bubble stops following the mouse,
 * gains a close button and becomes scrollable, so a tall stack of sections can
 * actually be read. Clicking the map again, or the close button, releases it.
 * ======================================================================== */
const POPUP_SPECS = [];     // { layer, title, html } in the order they appear
let popupSpecsBuilt = false;

/* Register what a layer says when the cursor is over it. `html` builds the
   section body from the feature's properties; `title` heads the section when
   several are shown at once. */
function popup(m, layer, html, title) {
  if (!popupSpecsBuilt) POPUP_SPECS.push({ layer, html, title });
}

// Which map, if any, currently has its bubble pinned open.
let pinnedOn = null;

/* Everything under the cursor, as ready-to-show sections. */
function sectionsAt(m, point) {
  const ids = POPUP_SPECS.map((s) => s.layer).filter((id) => m.getLayer(id));
  let feats = [];
  try {
    feats = m.queryRenderedFeatures(point, { layers: ids });
  } catch (err) {
    return [];                                   // style still loading
  }
  const out = [], seen = new Set();
  for (const spec of POPUP_SPECS) {              // fixed order, not hit order
    for (const f of feats) {
      if (f.layer.id !== spec.layer) continue;
      // One section per feature, not per overlapping copy of it.
      const key = spec.layer + "|" + (f.id != null ? f.id : JSON.stringify(f.properties));
      if (seen.has(key)) continue;
      seen.add(key);
      const body = spec.html(f.properties, f, m);
      if (body) out.push({ title: spec.title, body });
    }
  }
  return out;
}

function showCombined(m, e) {
  const sections = sectionsAt(m, e.point);
  const bubble = hoverBubble(m);
  if (!sections.length) { bubble.remove(); m.getCanvas().style.cursor = ""; return; }
  m.getCanvas().style.cursor = "pointer";
  const many = sections.length > 1;
  bubble
    .setLngLat(e.lngLat)
    .setHTML(
      (many ? `<div class="pp-count">${sections.length} layers here</div>` : "") +
      sections.map((s) => `<div class="pp-sec">${
        many && s.title ? `<div class="pp-title">${s.title}</div>` : ""}${s.body}</div>`).join("") +
      `<div class="pp-hint">click to pin${many ? " and scroll" : ""}</div>`)
    .addTo(m);
}

/* Pin the bubble where it is, so it can be read and scrolled. */
function pinBubble(m, e) {
  const sections = sectionsAt(m, e.point);
  if (!sections.length) { unpin(); return; }
  unpin();
  pinnedOn = m;
  const bubble = hoverBubble(m);
  bubble.setLngLat(e.lngLat).setHTML(
    `<button type="button" class="pp-close" aria-label="Close">×</button>` +
    (sections.length > 1 ? `<div class="pp-count">${sections.length} layers here</div>` : "") +
    sections.map((s) => `<div class="pp-sec">${
      s.title ? `<div class="pp-title">${s.title}</div>` : ""}${s.body}</div>`).join("")
  ).addTo(m);
  const el = bubble.getElement();
  el.classList.add("pinned");
  const close = el.querySelector(".pp-close");
  if (close) close.addEventListener("click", unpin);
}

function unpin() {
  if (!pinnedOn) return;
  const bubble = hoverBubble(pinnedOn);
  const el = bubble.getElement();
  if (el) el.classList.remove("pinned");
  bubble.remove();
  pinnedOn = null;
}

/* One set of handlers per map, replacing the per-layer ones. */
function bindPopups(m) {
  m.on("mousemove", (e) => { if (!pinnedOn) showCombined(m, e); });
  m.on("mouseout", () => { if (!pinnedOn) hoverBubble(m).remove(); });
  m.on("click", (e) => (pinnedOn ? unpin() : pinBubble(m, e)));
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
                     need: [0.55, -0.35] };

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
  /* What the popup will say about each area: not just which pillars are on it
     but WHICH TAGS, how many mentions each, and a sentence from the reporting.
     Worked out here because this is the one place that already walks the rows;
     the popup then only has to look it up. */
  const detail = {};

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
        const d = (detail[row.area] = detail[row.area] || {});
        const dd = (d[dim] = d[dim] || {});
        dd[tag] = (dd[tag] || 0) + row.count;
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
    /* WHICH PILLAR OWNS THE FILL: the first one present in DIM_ORDER, not the
       most-mentioned one. The workflow this map is for is "put hazards up, add
       vulnerabilities, then look for coping in the same places" - and ranking by
       count breaks it, because adding a second pillar would recolour areas that
       are already on screen the moment its mentions overtook the first. A fixed
       precedence means a hazard area stays hazard-red as more pillars go on. */
    const top = DIM_ORDER.find((d) => dims[d] != null) || null;
    if (top) {
      st.topColor = DIM_META[top].color;
      /* Opacity still carries volume, but over a NARROW band that starts where
         a colour is already unmistakable. The old floor of 0.07 is what made a
         lightly-reported area indistinguishable from an empty one; IPC sits at
         a flat 0.6 and is legible everywhere, so this brackets that. */
      st.wash = Math.max(0.5, Math.min(0.72, 0.46 + Math.sqrt(dims[top]) * 0.05));
      st.edge = 0.55;
    }
    areaStates[areaId] = st;
  }
  setStates("areas", areaStates);
  state.areaDetail = detail;
  state.areaMonth = mk;

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
   displacement.

   All three are POPULATION FIGURES, read from the same series the headline row
   and the Movement trends graph read. The panel used to end with the month's
   most-reported hazard and top need, which are mention counts from the
   documents - a different unit answering a different question, and already
   answered better by Top reported hazards and by the theme panel. */
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
  el.innerHTML = items.length
    ? items.map((i) => `<div class="insight ${i.good ? "good" : ""}"><span class="ico">${i.ico}</span><span>${i.html}</span></div>`).join("")
    : `<div class="panel-note">${filtered()
        ? "Nothing to report for the selected countries on this date."
        : "Drag the timeline forward to see insights build up."}</div>`;
}

// "2024-08" -> "August 2024", for labelling a quote with the month it is from.
const monthLabel = (mk) =>
  new Date(mk + "-01").toLocaleDateString("en-GB", { month: "long", year: "numeric" });

/* Every quote the panel can show, from both sources, in one shape.

   Two sources, deliberately not merged into one table upstream:
     - tags.json snippets: regex matches on analyst prose, rebuilt by s03_parse
       on every pipeline run. These are secondary_analysis by definition.
     - /api/insights/: statements a person reviewed and published.

   Both filters are applied HERE, as the comment on monthTagTotals requires, so
   the panel and the map cannot drift apart. */
function allVoices() {
  const rows = [];

  // Analyst voice: the regex snippets, exactly as before.
  for (const [dim, tags] of Object.entries(state.data.tags)) {
    if (!DIM_META[dim]) continue;
    const only = activeTagsIn(dim);
    for (const [tag, tagData] of Object.entries(tags)) {
      if (only && !only.has(tag)) continue;
      for (const mk of Object.keys(tagData.snippets)) {
        if (filtered() && !tagCount(tagData, mk)) continue;
        const text = snippetFor(tagData, mk);
        if (text) rows.push({ dim, tag, mk, text, full: text, voice: "secondary_analysis" });
      }
    }
  }

  // Published insights, community and analyst alike.
  for (const row of state.data.insights || []) {
    // Same country filter every other panel applies, through the one place
    // that decides it - see countryOn(). A row whose country cannot be
    // resolved (or has none) drops out under a filter, same as an analyst
    // snippet with no count in the selected countries that month.
    if (!countryOn(ISO3_TO_COUNTRY[row.iso3])) continue;
    const mk = (row.date || "").slice(0, 7);
    for (const coding of row.codings.length ? row.codings : [{ dimension: null, tag: null }]) {
      const dim = coding.dimension;
      if (dim && !DIM_META[dim]) continue;
      // Same theme filter the map layers use - one filter, four consumers.
      if (dim) {
        const only = activeTagsIn(dim);
        if (only && !only.has(coding.tag)) continue;
      }
      rows.push({
        dim: dim || "need", tag: coding.tag || "other", mk,
        text: row.quote, full: row.quote, translated: row.quote_translated,
        voice: row.voice_type, place: row.place_name, date: row.date,
        source: row.source_document, matchMethod: row.match_method,
        lat: row.lat, lon: row.lon, id: row.id,
      });
    }
  }

  return rows.sort((a, b) => (a.mk < b.mk ? 1 : a.mk > b.mk ? -1 : 0));
}

/* The rows the active tab shows. Search is scoped to this, which is the point
   of the tabs: with Community selected, a search never returns analyst prose. */
function voicesForTab() {
  const all = allVoices();
  if (state.voiceTab === "community") return all.filter((v) => v.voice === "community");
  if (state.voiceTab === "analyst") return all.filter((v) => v.voice === "secondary_analysis");
  return all;
}

/* Verbatim sentences from the reports - the human voice behind the numbers.

   With the search box empty this shows up to three quotes for the month the
   timeline is on, one per dimension, as it always has. Type anything and it
   searches the WHOLE archive instead: any single month holds only a handful
   of quotes, so a search confined to one month would almost always come back
   empty. Each result is labelled with its month and clicking it moves the
   timeline there. */
function renderVoices() {
  const el = $("#voices"), q = state.voiceSearch.trim().toLowerCase();
  const searching = q.length > 0;
  const pool = voicesForTab();
  let picks;

  if (searching) {
    picks = pool.filter((v) =>
      v.full.toLowerCase().includes(q) ||
      (v.translated || "").toLowerCase().includes(q) ||
      (v.place || "").toLowerCase().includes(q) ||
      v.tag.replace(/_/g, " ").toLowerCase().includes(q) ||
      DIM_META[v.dim].label.toLowerCase().includes(q)).slice(0, 40);
  } else {
    const mk = monthKey(state.current);
    const month = pool.filter((v) => v.mk === mk);
    // Community voice is scarce, so show all of it for the month. Analyst
    // snippets are plentiful: keep the old one-per-dimension behaviour.
    picks = state.voiceTab === "analyst" ? month.slice(0, 3) : month.slice(0, 12);
  }

  if (!picks.length) {
    el.innerHTML = `<div class="voices-empty">${searching
      ? `No quote matches “${escapeHTML(state.voiceSearch)}” in this tab.`
      : state.voiceTab === "community"
        ? "No community statement recorded for this month."
        : "No narrative reporting captured for this month."}</div>`;
    $("#voice-count").textContent = "";
    return;
  }

  $("#voice-count").textContent = searching
    ? `${picks.length}${picks.length === 40 ? "+" : ""} across all months` : "";

  const unmapped = picks.filter((v) => v.voice === "community" && v.lat == null).length;

  el.innerHTML = picks.map((p, i) => `<div class="voice${
      p.voice === "community" ? " is-community" : ""}${searching ? " voice-hit" : ""}"
      style="border-color:${DIM_META[p.dim].color}"
      data-month="${p.mk}" data-i="${i}" data-id="${p.id || ""}">
      <div class="v-full">${searching ? highlight(p.full, q) : escapeHTML(p.full)}</div>
      ${p.translated ? `<div class="v-translated">${escapeHTML(p.translated)}</div>` : ""}
      <div class="v-meta">
        <span class="v-voice">${p.voice === "community" ? "Community" : "Analyst"}</span>
        · ${DIM_META[p.dim].label} · ${escapeHTML(p.tag.replace(/_/g, " "))}
        ${p.place ? ` · ${escapeHTML(p.place)}` : ""} · ${monthLabel(p.mk)}
        ${p.source ? ` · ${escapeHTML(p.source)}` : ""}
      </div>
    </div>`).join("") + (unmapped
      ? `<div class="voices-unmapped">${unmapped} of these could not be placed on the map.</div>`
      : "");

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

/* THE ONE WAY THE TIMELINE MOVES. Four things ask for a different date - the
   slider, the play loop, a month link in the insights panel, and a click on the
   Movement trends graph - and every one of them has to do the same three
   things: set the date, put the slider where the date is, and redraw. Written
   out four times it is four chances for the slider to end up saying one date
   while the map shows another, so it is written once.

   Days, not milliseconds: the slider's resolution is a day, so a date that is
   not on a day boundary would set a slider position that rounds back to a
   different date - and the next drag would jump. */
function setCurrentDate(t) {
  const days = Math.round((clamp(t, START, state.endDate) - START) / DAY);
  state.current = START + days * DAY;
  $("#time-slider").value = days;
  renderAll();
}

function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

/* Move the timeline to the first day of a month and redraw everything. */
function goToMonth(mk) {
  setCurrentDate(Date.parse(mk + "-01"));
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
/* Food insecurity, for every country in scope rather than Sudan alone.

   Each country is a separate file and keeps its own analysis calendar - IPC
   redraws its units per round and no two countries publish on the same date - so
   the period in effect is worked out PER COUNTRY at the current timeline date and
   the results are concatenated. Showing one global period would blank every
   country that had not published in that particular month. */
function renderFoodsec() {
  if (!state.showFoodsec) { setSource("ipc", empty()); return; }
  const scope = scopeCountries();
  let feats = [];
  for (const [iso3, payload] of Object.entries(state.data.ipcByCountry || {})) {
    const country = ISO3_TO_COUNTRY[iso3];
    if (scope.size && country && !scope.has(country)) continue;
    const d = ipcPeriodAt(state.current, payload);
    if (d && payload.periods[d]) feats = feats.concat(payload.periods[d].features);
  }
  setSource("ipc", { type: "FeatureCollection", features: feats });
}

/* Fetch the food-security file for each country in scope that is not loaded
   yet. One file per country, on demand: together they are far larger than any
   one of them, and a reader looking at Chad has no use for Sudan's polygons. */
async function loadFoodsecForScope() {
  state.data.ipcByCountry = state.data.ipcByCountry || {};
  const scope = scopeCountries();
  const wanted = COUNTRIES
    .filter((c) => !scope.size || scope.has(c))
    .map((c) => COUNTRY_TO_ISO3[c])
    .filter((iso) => iso && IPC_COUNTRIES.includes(iso) && !(iso in state.data.ipcByCountry));
  if (!wanted.length) return;
  const loaded = await Promise.all(wanted.map((iso) =>
    fetch(`data/ipc_fs/${iso}.geojson`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)));
  wanted.forEach((iso, i) => {
    if (!loaded[i]) return;
    // Stamp the country name each area belongs to, once, from the file it came
    // in - no bounding-box guessing needed now that the data carries its iso3.
    for (const fc of Object.values(loaded[i].periods))
      for (const f of fc.features) f.properties.country = ISO3_TO_COUNTRY[iso];
    state.data.ipcByCountry[iso] = loaded[i];
  });
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

/* The 14 IFRC Areas of Operation, drawn as a uniform outline. The IPC phase
   joined onto them is deliberately neither drawn nor named - see aoi-fill. */
/* Service points for the countries in scope. */
function renderHSP() {
  if (!state.showHSP || !state.data.hsps) { setSource("hsps", empty()); return; }
  setSource("hsps", filterFC(state.data.hsps));
}

function renderAOI() {
  setSource("aoi", state.showAOI ? filterFC(state.data.aoi) : empty());
}

/* iso3 -> the country name the rest of the dashboard uses. */
const ISO3_TO_COUNTRY = Object.fromEntries(
  Object.entries(COUNTRY_TO_ISO3).map(([name, iso]) => [iso, name]));

/* Which countries have a food-security file to fetch. Egypt and Libya have no
   classification from ANY source - neither IPC nor FEWS NET covers them - so
   asking for a file would 404 on every toggle. Ethiopia is here because its
   FEWS NET phases have been matched to the boundary library by name; IPC itself
   has published nothing for it since 2021. */
const IPC_COUNTRIES = ["SDN", "TCD", "CAF", "SSD", "ETH"];

/* WHO PUBLISHED A NUMBER, AND WHERE TO GO AND READ IT.

   A popup used to say "via IPC MCP". MCP is how this project fetches the data,
   which is a fact about our plumbing and of no interest to a reader deciding
   whether to trust a phase classification. What matters is who assessed it, so
   each source is named and linked to its own site. */
const SOURCES = {
  ipc:     { name: "IPC",      url: "https://www.ipcinfo.org/" },
  ch:      { name: "Cadre Harmonisé", url: "https://www.ipcinfo.org/ch/" },
  fewsnet: { name: "FEWS NET", url: "https://fews.net/" },
  hdx:     { name: "IOM DTM via HDX", url: "https://data.humdata.org/" },
  unhcr:   { name: "UNHCR",    url: "https://data.unhcr.org/" },
  excel:   { name: "IFRC operational reporting", url: "" },
  kobo:    { name: "IFRC HSP Mapping", url: "" },
  curated: { name: "Curated by the operation", url: "" },
};

/* One line of attribution: the publisher's name, linked where it has a site. */
function sourceLine(key, extra) {
  const src = SOURCES[key] || { name: key || "unknown", url: "" };
  const label = src.url
    ? `<a href="${src.url}" target="_blank" rel="noopener">${escapeHTML(src.name)}</a>`
    : escapeHTML(src.name);
  return `<span class="pp-src">${label}${extra ? " · " + escapeHTML(extra) : ""}</span>`;
}

const CAL_MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

/* WHAT EACH BAND OF THE CALENDAR MEANS, and the order the bands are read in.

   Keyed on the normalised `season_type`, so one kind of season is one colour
   in EVERY country: a reader who learns pale blue is the rains in Sudan can
   then read Chad's strip without going back to the key. The colours themselves
   live in app.css (--season-*) and are read from there, so the brand block
   stays the single place colour is defined.

   The order is the story the calendar tells, not the alphabet: the climate
   first, because it drives everything under it; then the agricultural cycle in
   the sequence it happens; then the lean season, which is the consequence; then
   the hazards and the herds. ACAPS's own event_type is NOT used for the
   headings - it files rainy and dry seasons under "Seasonal hazard", which
   would put a blue band under a heading that reads as a warning. */
const SEASON_META = {
  Rainy:     { label: "Rainy season",   varName: "--season-rain",      fallback: "#8dcde2" },
  Dry:       { label: "Dry season",     varName: "--season-dry",       fallback: "#ffb25b" },
  Planting:  { label: "Planting and land preparation",
                                        varName: "--season-planting",  fallback: "#47d7ac" },
  Harvest:   { label: "Harvest",        varName: "--season-harvest",   fallback: "#009775" },
  Lean:      { label: "Lean season",    varName: "--season-lean",      fallback: "#6b3a90" },
  Hazard:    { label: "Seasonal hazard", varName: "--season-hazard",   fallback: "#d22730" },
  Livestock: { label: "Livestock movement",
                                        varName: "--season-livestock", fallback: "#ff8200" },
  Other:     { label: "Unclassified",   varName: "--season-other",     fallback: "#bdbdbd" },
};
const SEASON_ORDER = ["Rainy", "Dry", "Planting", "Harvest", "Lean", "Hazard",
                      "Livestock", "Other"];

/* The colour of one band, read from the stylesheet so app.css stays the one
   place the palette is defined. */
function seasonColor(type) {
  const meta = SEASON_META[type] || SEASON_META.Other;
  return paletteColor(meta.varName, meta.fallback);
}

/* The seasonal calendar strip: lean, rainy and harvest bands, with the month
   the timeline is currently in highlighted. */
function renderSeasonal() {
  const el = $("#seasonal-cal");
  const data = state.data.seasonal && state.data.seasonal.countries;
  if (!el || !data) return;

  // Whichever countries are selected, in the dropdown's own order. An empty
  // filter means no filter, so every country we hold a calendar for is shown.
  const scope = scopeCountries();
  const wanted = COUNTRIES.filter((c) => (scope.size === 0 || scope.has(c)) && COUNTRY_TO_ISO3[c]);

  const cur = new Date(state.current).getMonth();   // 0-11
  let html = "";
  let shown = 0;
  const absent = [];
  // The kinds of season actually on screen. The legend lists only these: a key
  // to bands the reader cannot see is noise, and it changes with the filter.
  const seen = new Set();

  for (const country of wanted) {
    const entry = data[COUNTRY_TO_ISO3[country]];
    // A country FEWS NET does not cover is named rather than skipped: Egypt has
    // crop seasons but no lean season, and Libya has a single placeholder band.
    // Silence would read as "we did not look".
    if (!entry || !entry.items || !entry.items.length) { absent.push(country); continue; }

    shown++;
    const src = entry.source === "acaps" ? "ACAPS" : "FEWS NET";
    html += `<div class="cal-country">${escapeHTML(country)}
      <span class="cal-src">${src}</span></div>`;

    // ACAPS groups its events - planting, harvest, hazards - and the grouping is
    // most of what makes it readable: a reader looks for "when is the lean
    // season", not for the twelfth row of an undifferentiated list.
    const groups = new Map();
    for (const it of entry.items) {
      const g = SEASON_META[it.season_type] ? it.season_type : "Other";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(it);
      seen.add(g);
    }
    const names = [...groups.keys()].sort(
      (a, b) => SEASON_ORDER.indexOf(a) - SEASON_ORDER.indexOf(b));

    html += `<div class="cal-row cal-head"><span class="cal-label"></span>`;
    for (let m = 0; m < 12; m++)
      html += `<span class="cal-cell ${m === cur ? "cal-now" : ""}">${CAL_MONTHS[m]}</span>`;
    html += `</div>`;

    for (const g of names) {
      html += `<div class="cal-group">${escapeHTML(SEASON_META[g].label)}</div>`;
      for (const it of groups.get(g)) {
        // Everything ACAPS says about this event, in the tooltip: the sentence of
        // explanation, the regions it applies to when it is not national, and who
        // assessed it. That detail is the reason this calendar was asked for.
        const bits = [];
        if (it.note) bits.push(it.note);
        if (it.event && it.event !== it.label) bits.push(it.event);
        if (it.country_wide === false && (it.areas || []).length)
          bits.push("Regions: " + it.areas.join(", "));
        if (it.source_org) bits.push(`Source: ${it.source_org}${it.source_date ? " (" + it.source_date.slice(0, 4) + ")" : ""}`);
        const title = escapeHTML(bits.join(" — "));
        const partial = it.country_wide === false ? " cal-partial" : "";
        html += `<div class="cal-row"><span class="cal-label${partial}" title="${title}">${escapeHTML(it.label)}</span>`;
        for (let m = 1; m <= 12; m++) {
          const on = it.months.includes(m);
          // data-season, not an inline colour: the stylesheet decides what a
          // rainy season looks like, and it decides it once for every country.
          html += `<span class="cal-cell ${m - 1 === cur ? "cal-now" : ""}"${on ? ` data-season="${g}"` : ""}></span>`;
        }
        html += `</div>`;
      }
    }
  }

  if (seen.size) {
    const keys = SEASON_ORDER.filter((k) => seen.has(k)).map((k) =>
      `<span class="cal-key"><i style="background:${seasonColor(k)}"></i>${escapeHTML(SEASON_META[k].label)}</span>`);
    html += `<div class="cal-legend">${keys.join("")}</div>`;
  }
  if (absent.length)
    html += `<div class="panel-note">No seasonal calendar published for
      ${absent.map(escapeHTML).join(", ")}.</div>`;
  if (shown)
    html += `<div class="panel-note">Hover a row for the description, the regions it
      covers and who assessed it. Source:
      <a href="https://www.acaps.org/en/thematics/all-topics/seasonal-events-calendar"
         target="_blank" rel="noopener">ACAPS Seasonal Events Calendar</a>.</div>`;
  if (!shown && !absent.length)
    html += `<div class="panel-note">No seasonal calendar for this selection.</div>`;
  el.innerHTML = html;
}

/* Every layer of ONE map, for whatever scope is currently in force. */
function drawMapLayers() {
  renderFoodsec();
  renderFlows();
  renderCrossings();
  renderHSP();
  renderIDP();
  renderIDPStates();
  renderRefugees();
  renderEvents();
  renderThemes();
  /* The Areas of Operation used to be drawn only when their checkbox moved,
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
  drawMovementTrends();
  renderTrendLegend();
  $("#current-date").textContent = fmtDate(state.current);
}

/* Everything renderAll() does, plus the things that only change when a FILTER
   changes rather than when the date does: the points behind the Movement
   trends graph and, if asked, the map viewport.

   Fitting the map is deliberately not part of renderAll(): renderAll runs
   about eight times a second while the timeline is playing, and re-fitting the
   camera at that rate would make the map unusable. Rebuilding the trend series
   is kept out of it for the same reason - see computeTrendSeries(). */
function applyFilters({ refit = true } = {}) {
  computeTrendSeries();
  renderAll();
  if (refit) fitToSelection();
  // Widening the country filter can bring a country into scope whose
  // food-security file has never been fetched. Load it, then redraw that one
  // layer - the rest of the page has already been drawn from what it had.
  if (state.showFoodsec) loadFoodsecForScope().then(renderFoodsec);
}

/* ---------------- the Movement trends graph ----------------------------
 *
 * Three population series on one pair of axes: everyone displaced, everyone
 * who crossed a border out of Sudan, and everyone who has gone back.
 *
 * It used to be a 48px sparkline drawn BEHIND the timeline slider, where it
 * was a texture rather than a chart - no scale, no year marks, no way to read
 * a value off it, and a slider thumb sitting on top of the lines. It is now a
 * panel of its own on the right, which leaves the timeline as just a timeline.
 *
 * ONE VERTICAL SCALE for all three. They are all counts of people, so plotting
 * them against a shared axis is the only way their relative size stays honest;
 * a second axis would let the smallest series be drawn as tall as the biggest.
 * ------------------------------------------------------------------------ */

/* The three lines, in the order they are drawn and listed. Colours are the
   ones the map already uses for the same idea: orange leaving, green
   returning. Checked as a set for colour blindness - the closest pair is
   10.4 apart - but the orange is pale against white, so identity is carried
   by the labelled key below the graph as well as by the colour. */
const TREND_SERIES = [
  { metric: "total_displaced", color: COLOR_OUT, label: "Total displaced" },
  { metric: "cumulative_arrivals", color: COLOR_ACCENT, label: "Fled across a border" },
  { metric: "returns_to_sudan_total", color: COLOR_IN, label: "Returns to Sudan" },
];

/* Work out the points and cache them on state.

   Kept apart from the drawing because statSeries() is cheap unfiltered and
   expensive under a filter - it rebuilds a series by asking statAt() for every
   date any corridor reported on. The graph is redrawn on every timeline move,
   about eight times a second while the story plays; the points behind it only
   change when a FILTER changes, so that is when this runs. */
function computeTrendSeries() {
  const series = TREND_SERIES.map((s) => ({ ...s, points: statSeries(s.metric) }));
  state.trend = {
    series,
    vmax: Math.max(...series.flatMap((s) => s.points.map((p) => p.value)), 1),
  };
}

/* Round a maximum up to something a person would say out loud, so the top of
   the scale reads "13M" rather than "12,994,517".

   TWO significant figures, not one. A ladder of round numbers - 1, 2, 5, 10 -
   would push a peak of 13M up to a scale of 15M and spend a fifth of the
   panel's height on empty air, which is a lot of height in a panel this size.
   Rounding to the second digit costs nothing in readability and keeps the
   lines as tall as they can be. */
function niceMax(v) {
  const mag = Math.pow(10, Math.floor(Math.log10(v)) - 1);
  return Math.ceil(v / mag) * mag;
}

/* THE PLOT BOX, in CSS pixels, and the one place its shape is written down.
   The drawing multiplies these by the device pixel ratio; the click handler
   uses them as they are, because a click arrives in CSS pixels. Both have to
   agree about where the box starts and ends, or clicking the graph would set a
   date other than the one under the cursor - so neither gets its own copy.

   The gutters are what pay for the axes. Left holds the tick figures and the
   rotated axis title; bottom holds the year marks and "Date". The 132px of plot
   between them is exactly the height the lines had when the panel was 132px
   tall and had no axes at all: the labels were added to the canvas, not taken
   out of the chart. */
const TREND_CSS_H = 176;
const TREND_PAD = { t: 10, r: 4, b: 34, l: 46 };
const TREND_TICKS = 4;                     // gridlines above zero

/* Where the plot box sits across a canvas of this width. */
function trendBox(canvas) {
  return { x0: TREND_PAD.l, x1: canvas.offsetWidth - TREND_PAD.r };
}

/* A click's x, in CSS pixels, back into the date standing at it - xAt() run
   backwards. Clamped, so a click in either gutter takes the nearer end of the
   timeline rather than a date off the end of the war. */
function dateAtTrendX(canvas, cssX) {
  const { x0, x1 } = trendBox(canvas);
  const f = clamp((cssX - x0) / Math.max(x1 - x0, 1), 0, 1);
  return START + f * (state.endDate - START);
}

/* Draw the graph from the cache. Plain canvas - no charting library.

   Styled the way seaborn draws a whitegrid: soft gridlines in both directions,
   figures on both axes, a named axis on each, and no top or right spine. The
   panel used to carry a single number - the top of the scale - floating
   unlabelled above the lines, which gave the shape a ceiling but no way to read
   a value at any other height. */
function drawMovementTrends() {
  const canvas = $("#movement-trends");
  if (!canvas || !canvas.offsetWidth || !state.endDate) return;
  const dpr = devicePixelRatio || 1;
  const w = (canvas.width = canvas.offsetWidth * dpr);
  const h = (canvas.height = TREND_CSS_H * dpr);
  canvas.style.height = TREND_CSS_H + "px";
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);

  const box = trendBox(canvas);
  const x0 = box.x0 * dpr, x1 = box.x1 * dpr;
  const y0 = TREND_PAD.t * dpr, y1 = h - TREND_PAD.b * dpr;
  const span = state.endDate - START;
  const vmax = niceMax(state.trend.vmax);
  const xAt = (t) => x0 + ((t - START) / span) * (x1 - x0);
  const yAt = (v) => y1 - (v / vmax) * (y1 - y0);

  ctx.font = `${9.5 * dpr}px "Open Sans", Arial, sans-serif`;
  ctx.textBaseline = "alphabetic";

  const GRID = "rgba(1,30,65,.10)";
  const SPINE = "rgba(1,30,65,.28)";

  // ---- horizontal gridlines, and the figure each one stands for ---------
  ctx.lineWidth = 1 * dpr;
  for (let i = 0; i <= TREND_TICKS; i++) {
    const v = (vmax / TREND_TICKS) * i;
    const y = Math.round(yAt(v)) + 0.5;
    if (i > 0) {                           // zero is the spine, drawn below
      ctx.strokeStyle = GRID;
      ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
    }
    ctx.fillStyle = COLOR_MUTED;
    ctx.textAlign = "right";
    ctx.fillText(v ? fmtNum(v) : "0", x0 - 6 * dpr, y + 3.4 * dpr);
  }

  // ---- year marks: gridline above, figure below -------------------------
  /* The axis starts on 15 April 2023, so the loop below - which wants 1 January
     - can never label the origin, and with real axes an unlabelled end reads as
     a gap. So 2023 is written on the spine itself, left-aligned to stay inside
     the box, and with no gridline of its own because the spine is already the
     line it would draw. */
  ctx.fillStyle = COLOR_MUTED;
  ctx.textAlign = "left";
  ctx.fillText("2023", x0, y1 + 14 * dpr);

  const lastYear = new Date(state.endDate).getFullYear();
  for (let y = 2024; y <= lastYear; y++) {
    const t = Date.parse(`${y}-01-01`);
    if (t < START || t > state.endDate) continue;
    const x = Math.round(xAt(t)) + 0.5;
    ctx.strokeStyle = GRID;
    ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke();
    ctx.fillStyle = COLOR_MUTED;
    ctx.textAlign = "center";
    ctx.fillText(String(y), x, y1 + 14 * dpr);
  }

  // ---- the spines. Left and bottom only, seaborn-despined ---------------
  ctx.strokeStyle = SPINE;
  ctx.beginPath();
  ctx.moveTo(Math.round(x0) + 0.5, y0);
  ctx.lineTo(Math.round(x0) + 0.5, Math.round(y1) + 0.5);
  ctx.lineTo(x1, Math.round(y1) + 0.5);
  ctx.stroke();

  // ---- what each axis is counting ---------------------------------------
  ctx.fillStyle = COLOR_MUTED;
  ctx.textAlign = "center";
  ctx.fillText("Date", (x0 + x1) / 2, h - 4 * dpr);
  ctx.save();                              // the y title reads bottom-to-top
  ctx.translate(11 * dpr, (y0 + y1) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("People", 0, 0);
  ctx.restore();

  // ---- the defining events, as ticks standing on the zero line ----------
  ctx.fillStyle = "rgba(200,110,0,.8)";
  for (const ev of (state.data.events || []).filter((e) =>
    e.source === "curated" && e.severity >= 4 && (e.country === "Regional" || countryOn(e.country)))) {
    const t = Date.parse(ev.date);
    if (t < START || t > state.endDate) continue;
    ctx.fillRect(Math.round(xAt(t)), y1 - 5 * dpr, 1.5 * dpr, 5 * dpr);
  }

  // ---- where the timeline is standing -----------------------------------
  // The graph no longer sits under the slider, so it has to say for itself
  // which date the rest of the page is showing. Drawn under the lines.
  const xNow = Math.round(xAt(state.current)) + 0.5;
  ctx.strokeStyle = "rgba(1,30,65,.45)";
  ctx.lineWidth = 1 * dpr;
  ctx.setLineDash([3 * dpr, 3 * dpr]);
  ctx.beginPath(); ctx.moveTo(xNow, y0 - 4 * dpr); ctx.lineTo(xNow, y1); ctx.stroke();
  ctx.setLineDash([]);

  // ---- the three lines ---------------------------------------------------
  for (const s of state.trend.series) {
    if (s.points.length < 2) continue;
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2 * dpr;
    ctx.lineJoin = "round";
    ctx.beginPath();
    s.points.forEach((p, i) => {
      const x = xAt(Date.parse(p.date)), y = yAt(p.value);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }

  // ---- a dot on each line at the current date ----------------------------
  // This is what ties a line to its row in the key underneath, which carries
  // the figure. The white ring keeps two dots apart where the lines cross.
  for (const s of state.trend.series) {
    const v = statAt(s.metric, state.current);
    if (!v) continue;
    ctx.beginPath();
    ctx.arc(xNow, yAt(v), 3.2 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = s.color;
    ctx.fill();
    ctx.lineWidth = 1.6 * dpr;
    ctx.strokeStyle = WHITE;
    ctx.stroke();
  }
}

/* CLICKING THE GRAPH MOVES THE WHOLE DASHBOARD. The graph draws the war end to
   end while every other panel shows a single date, so it is the one place a
   reader can SEE the moment they want - the bend where returns start, the step
   where a corridor opened - and until now the only way to get to that moment
   was to hunt for it with the slider.

   The story is stopped first. A click during playback would otherwise be
   overwritten by the play timer 120ms later, which reads as the click having
   done nothing at all. */
function initTrendsClick() {
  const canvas = $("#movement-trends");
  if (!canvas) return;
  canvas.addEventListener("click", (e) => {
    if (!state.endDate) return;
    stopPlaying();
    // Worked out from the cursor and the canvas's own box rather than taken
    // from e.offsetX, because the page is drawn smaller than it is laid out
    // (see uiScale) and offsetX is reported at the size it is DRAWN, while
    // dateAtTrendX measures against offsetWidth, which is the size it is laid
    // out at. Straight from offsetX the click landed a fifth of the war early.
    const box = canvas.getBoundingClientRect();
    const scale = box.width / canvas.offsetWidth || 1;
    setCurrentDate(dateAtTrendX(canvas, (e.clientX - box.left) / scale));
  });
}

/* The key under the graph: one row per line, each carrying its figure for the
   date the timeline is on. The figures are the point of it. Colour alone would
   leave the orange series - the palest of the three against white - identified
   by something a reader may not be able to see, and would leave the graph a
   shape with no numbers anywhere on it. */
function renderTrendLegend() {
  const el = $("#trend-key");
  if (!el) return;
  el.innerHTML = state.trend.series.map((s) => {
    const v = statAt(s.metric, state.current);
    return `<div class="tk-row">
      <span class="tk-line" style="background:${s.color}"></span>
      <span class="tk-label">${s.label}</span>
      <span class="tk-val">${v ? fmtNum(v) : "–"}</span>
    </div>`;
  }).join("");
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
    setCurrentDate(START + Number(slider.value) * DAY);
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
  play.addEventListener("click", () => {
    if (state.playing) { stopPlaying(); return; }
    state.playing = true;
    play.textContent = "❚❚";
    if (Number(slider.value) >= days) slider.value = 0;
    playTimer = setInterval(() => {
      const v = Number(slider.value) + 4;
      if (v >= days) { slider.value = days; stopPlaying(); }
      else slider.value = v;
      setCurrentDate(START + Number(slider.value) * DAY);
    }, 120);
  });
}

/* The play loop's handle, lifted out of initTimeline() so that anything which
   moves the timeline by hand can stop the story first. Without that, clicking
   the trends graph mid-play sets a date the timer overwrites 120ms later, and
   the click reads as broken. */
let playTimer = null;
function stopPlaying() {
  clearInterval(playTimer);
  playTimer = null;
  state.playing = false;
  const play = $("#play-btn");
  if (play) play.textContent = "▶";
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
  $("#toggle-hsps").addEventListener("change", (e) => {
    state.showHSP = e.target.checked;
    renderMapLayers();
  });
  $("#toggle-foodsec").addEventListener("change", async (e) => {
    state.showFoodsec = e.target.checked;
    if (state.showFoodsec) {
      e.target.disabled = true;
      await loadFoodsecForScope();
      e.target.disabled = false;
    }
    renderMapLayers();
  });
  // The key-events switch also empties the banner above the map.
  $("#toggle-events").addEventListener("change", renderEventBanner);
}

/* ---------------------------------------------------------------- dropdown
 * ONE searchable multi-select, built six times: once for the country filter
 * and once for each of the four narrative dimensions. Everything about how a
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
    /* activeTags is one flat set of "dimension|tag" keys shared by all four
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
  for (const tab of document.querySelectorAll(".voice-tab"))
    tab.addEventListener("click", () => {
      state.voiceTab = tab.dataset.tab;
      for (const other of document.querySelectorAll(".voice-tab"))
        other.classList.toggle("is-active", other === tab);
      renderVoices();
      if (typeof renderInsightBubbles === "function") renderInsightBubbles();
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
    fitMap(maps[0], sel.length ? boundsFor(sel) : HOME_BOUNDS);
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
  initSidebarResize();
  initVoiceSearch();
  computeTrendSeries();
  /* The graph is sized in pixels off its panel, and the right sidebar can be
     resized by dragging its grip - which changes that width without any window
     resize to listen for. Watching the canvas itself catches both. */
  new ResizeObserver(() => drawMovementTrends()).observe($("#movement-trends"));
  initTrendsClick();
  window.addEventListener("resize", () => { for (const m of maps) m.resize(); });
  // open the story at the beginning
  renderAll();
})();
