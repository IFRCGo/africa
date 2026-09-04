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

// EVERYTHING the page currently shows is described by this one object.
// Change something here, call renderAll(), and the map catches up.
const state = {
  data: {},                // every file loaded from data/, keyed by name
  endDate: null,           // the most recent date we have data for
  current: START,          // the date the timeline is pointing at RIGHT NOW
  playing: false,          // is the play button running?
  activeTags: new Set(),   // ticked theme boxes, stored as "dimension|tag"
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
  $("#doc-count").textContent = state.data.meta.documents.toLocaleString();
  $("#last-updated").textContent = fmtDate(state.endDate);
}

/* ========================= 4. MAP ====================================== */

let map;   // the MapLibre map object, created by initMap() below
// zoom lock to the Sudan + neighbours region (matches the HSP dashboard)
const REGION_BOUNDS = [[9.0, -2.5], [55.0, 32.0]];
/* Create the map: a light CARTO Positron basemap, locked to the Sudan and
   neighbours region so a user cannot accidentally pan away to Europe. */
function initMap() {
  map = new maplibregl.Map({
    container: "map",
    style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    center: [29.5, 15.2],
    zoom: 4.35,
    minZoom: 3,
    maxBounds: REGION_BOUNDS,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  return new Promise((resolve) => map.on("load", resolve));
}

/* Declare every layer the map can draw, once, in the order they stack from
   bottom to top. They all start EMPTY: the render*() functions in section 5
   fill them with the right shapes for whatever date the timeline shows. */
function addLayers() {
  // ---- IPC food-security choropleth, area level (bottom of the stack) ----
  map.addSource("ipc", { type: "geojson", data: empty() });
  map.addLayer({
    id: "ipc-fill", type: "fill", source: "ipc",
    paint: {
      "fill-color": ["case", [">=", ["get", "ph"], 1], ["get", "color"], "rgba(0,0,0,0)"],
      "fill-opacity": 0.6,
    },
  });
  map.addLayer({
    id: "ipc-line", type: "line", source: "ipc",
    paint: { "line-color": "#0e1116", "line-width": 0.4, "line-opacity": 0.5 },
  });
  map.addLayer({
    id: "ipc-famine", type: "line", source: "ipc",
    filter: ["==", ["get", "fam"], true],
    paint: { "line-color": COLOR_ACCENT, "line-width": 1.8 },
  });

  // ---- boundary context: state lines, country outlines, IFRC Areas of Interest ----
  map.addSource("admin1lines", { type: "geojson", data: state.data.admin1 || empty() });
  map.addLayer({
    id: "admin1-line", type: "line", source: "admin1lines",
    paint: { "line-color": "#bfc4cb", "line-width": 0.6, "line-dasharray": [2, 2] },
  });
  map.addSource("aoi", { type: "geojson", data: empty() });
  map.addLayer({
    id: "aoi-fill", type: "fill", source: "aoi",
    paint: { "fill-color": ["get", "ipc_color"], "fill-opacity": 0.5 },
  });
  map.addLayer({
    id: "aoi-line", type: "line", source: "aoi",
    paint: { "line-color": COLOR_EVENT, "line-width": 2.4 },
  });
  map.addSource("admin0lines", { type: "geojson", data: state.data.admin0 || empty() });
  map.addLayer({
    id: "admin0-line", type: "line", source: "admin0lines",
    paint: { "line-color": "#5b6470", "line-width": 1.3 },
  });

  map.addSource("flows", { type: "geojson", data: empty() });
  map.addSource("flow-labels", { type: "geojson", data: empty() });
  map.addSource("events", { type: "geojson", data: empty() });
  map.addSource("themes", { type: "geojson", data: empty() });

  map.addLayer({
    id: "flow-lines", type: "line", source: "flows",
    layout: { "line-cap": "round" },
    paint: {
      "line-color": ["get", "color"],
      "line-width": ["get", "width"],
      "line-opacity": 0.8,
    },
  });
  // chevrons repeated along the line, auto-rotated to the direction of travel
  map.addLayer({
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
  map.addLayer({
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
  map.addLayer({
    id: "theme-bubbles", type: "circle", source: "themes",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": ["get", "color"],
      "circle-opacity": 0.35,
      "circle-stroke-color": ["get", "color"],
      "circle-stroke-width": 1.2,
    },
  });
  map.addLayer({
    id: "event-glow", type: "circle", source: "events",
    paint: {
      "circle-radius": ["*", ["get", "size"], 2.1],
      "circle-color": COLOR_EVENT, "circle-opacity": 0.22, "circle-blur": 0.6,
    },
  });
  map.addLayer({
    id: "event-dots", type: "circle", source: "events",
    paint: {
      "circle-radius": ["get", "size"],
      "circle-color": ["case", ["==", ["get", "source"], "curated"], COLOR_EVENT, "#78909c"],
      "circle-stroke-color": WHITE, "circle-stroke-width": 1.4,
      "circle-opacity": ["get", "opacity"],
    },
  });

  map.on("click", "event-dots", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ closeButton: false })
      .setLngLat(e.lngLat)
      .setHTML(`<b style="color:${COLOR_EVENT}">${fmtDate(Date.parse(p.date))}</b><br><b>${p.title}</b><br>${p.description || ""}`)
      .addTo(map);
  });
  map.on("mouseenter", "event-dots", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "event-dots", () => (map.getCanvas().style.cursor = ""));

  map.on("click", "flow-lines", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ closeButton: false })
      .setLngLat(e.lngLat)
      .setHTML(`<b>${p.name}</b><br>${p.kind}<br><b style="color:${p.color}">${p.labelFull}</b> people (cumulative)`)
      .addTo(map);
  });

  // ---- IDP localities (IOM-DTM, admin2) ----
  map.addSource("idp", { type: "geojson", data: empty() });
  map.addLayer({
    id: "idp-circles", type: "circle", source: "idp",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IDP_LOCALITY, "circle-opacity": 0.5,
      "circle-stroke-color": COLOR_IDP_LOCALITY, "circle-stroke-width": 1,
    },
  });

  // ---- IDP by state (admin1, Sudan IDPs.xlsx) ----
  map.addSource("idp-states", { type: "geojson", data: empty() });
  map.addLayer({
    id: "idp-state-circles", type: "circle", source: "idp-states",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IDP_STATE, "circle-opacity": 0.4,
      "circle-stroke-color": COLOR_IDP_STATE, "circle-stroke-width": 1.4,
    },
  });

  // ---- refugees: host-country totals + curated camp markers ----
  map.addSource("refcountry", { type: "geojson", data: empty() });
  map.addLayer({
    id: "ref-country", type: "circle", source: "refcountry",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IN_HOST, "circle-opacity": 0.22,
      "circle-stroke-color": COLOR_IN_HOST, "circle-stroke-width": 1.4,
    },
  });
  map.addSource("refcamps", { type: "geojson", data: empty() });
  map.addLayer({
    id: "ref-camps", type: "circle", source: "refcamps",
    paint: {
      "circle-radius": ["get", "radius"],
      "circle-color": COLOR_IN_HOST, "circle-opacity": 0.85,
      "circle-stroke-color": "#0e1116", "circle-stroke-width": 1.2,
    },
  });

  // ---- border crossings ----
  map.addSource("crossings", { type: "geojson", data: empty() });
  map.addLayer({
    id: "crossing-dots", type: "circle", source: "crossings",
    paint: {
      "circle-radius": ["case", ["get", "active"], 7, 4.5],
      "circle-color": ["case", ["get", "active"], COLOR_EVENT, WHITE],
      "circle-stroke-color": COLOR_INK, "circle-stroke-width": 1.4,
    },
  });
  map.addLayer({
    id: "crossing-labels", type: "symbol", source: "crossings",
    layout: {
      "text-field": ["get", "name"], "text-size": 10, "text-font": ["Open Sans Bold"],
      "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true,
    },
    paint: { "text-color": COLOR_INK, "text-halo-color": WHITE, "text-halo-width": 1.6 },
  });

  popup("idp-circles", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.state})</span><br>
    <b style="color:${COLOR_IDP_LOCALITY}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM via HDX</span>`);
  popup("idp-state-circles", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(Sudan — state level)</span><br>
    <b style="color:${COLOR_IDP_STATE}">${p.valFull}</b> IDPs · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">IOM-DTM / UNHCR (Sudan IDPs.xlsx)</span>`);
  popup("ref-country", (p) => `<b style="color:${COLOR_IN_HOST}">${p.country}</b><br>
    <b>${p.valFull}</b> Sudanese refugees · ${p.dateLabel}<br><span style="color:${COLOR_MUTED}">UNHCR${p.note ? " · " + p.note : ""}</span>`);
  popup("ref-camps", (p) => `<b style="color:${COLOR_IN_HOST}">${p.name}</b><br>${p.type} · ${p.country}<br>
    Opened ${p.opened}<br><span style="color:${COLOR_MUTED}">Location curated (UNHCR RRP); magnitude shown by country total</span>`);
  popup("crossing-dots", (p) => `<b>${p.name}</b><br>Crossing to ${p.country}<br>
    ${p.active ? `<b style="color:${COLOR_EVENT}">Active corridor</b> — ${p.flowLabel} people moved (cumulative)` : "No recorded movement at this date"}`);
  popup("ipc-fill", (p) => `<b>${p.area}</b><br>IPC <b>Phase ${p.ph}</b>${p.fam ? ` · <b style="color:${COLOR_ACCENT}">Famine (P5)</b>` : ""}<br>
    <b>${Math.round(p.p3 * 100)}%</b> in Phase 3+ (Crisis or worse)<br><span style="color:${COLOR_MUTED}">IPC analysis via IPC MCP</span>`);
  popup("aoi-fill", (p) => `<b>${p.name}</b> <span style="color:${COLOR_MUTED}">(${p.ipc_country || ""})</span><br>
    <b style="color:${COLOR_EVENT}">IFRC Area of Interest</b><br>
    ${p.ipc_phase ? `IPC <b>Phase ${p.ipc_phase}</b> — <b>${Math.round((p.ipc_p3 || 0) * 100)}%</b> in Phase 3+
      <span style="color:${COLOR_MUTED}">(${p.ipc_n_phase3plus}/${p.ipc_n_areas} sub-areas)</span>` : `<span style="color:${COLOR_MUTED}">No current IPC analysis</span>`}`);
}

/* Attach a click-for-details bubble to a layer, and turn the mouse pointer
   into a hand when hovering over it. `html` builds the bubble text from the
   properties of whatever feature was clicked. */
function popup(layer, html) {
  map.on("click", layer, (e) => {
    new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat)
      .setHTML(html(e.features[0].properties)).addTo(map);
  });
  map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
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
  map.getSource("flows").setData({ type: "FeatureCollection", features: lines });
  map.getSource("flow-labels").setData({ type: "FeatureCollection", features: labels });
}

/* Event dots, plus the banner across the top of the map.

   Recent events (under 45 days old on the timeline) are drawn big and bright.
   Older ones fade, and minor old ones disappear entirely, so the map keeps
   showing what matters now instead of every dot since 2023. */
function renderEvents() {
  const t = state.current;
  const feats = [];
  let banner = null;
  if (state.showEvents) {
    for (const ev of state.data.events) {
      const et = Date.parse(ev.date);
      if (et > t || !ev.lat) continue;
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
      if (recent && ev.source === "curated" && (!banner || Date.parse(banner.date) < et)) banner = ev;
    }
  }
  map.getSource("events").setData({ type: "FeatureCollection", features: feats });

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
function renderThemes() {
  const mk = monthKey(state.current);
  const byDimCountry = {};   // dim -> country -> count, for the active tags only
  for (const key of state.activeTags) {
    const [dim, tag] = key.split("|");
    const tagData = (state.data.tags[dim] || {})[tag];
    if (!tagData) continue;
    for (const row of tagData.monthly) {
      if (row.month !== mk || !ANCHORS[row.country]) continue;
      byDimCountry[dim] = byDimCountry[dim] || {};
      byDimCountry[dim][row.country] = (byDimCountry[dim][row.country] || 0) + row.count;
    }
  }
  const feats = [];
  for (const [dim, countries] of Object.entries(byDimCountry)) {
    const [ox, oy] = DIM_OFFSET[dim] || [0, 0];
    for (const [country, count] of Object.entries(countries)) {
      const [lon, lat] = ANCHORS[country];
      feats.push({
        type: "Feature", geometry: { type: "Point", coordinates: [lon + ox, lat + oy] },
        properties: {
          radius: Math.max(6, Math.min(34, 5 + Math.sqrt(count) * 3.2)),
          color: DIM_META[dim].color,
        },
      });
    }
  }
  map.getSource("themes").setData({ type: "FeatureCollection", features: feats });
  renderThemePanel(mk);
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
      const n = tagData.monthly.filter((r) => r.month === mk).reduce((a, r) => a + r.count, 0);
      rows.push([tag, n, tagData.snippets[mk]]);
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

/* The four big numbers at the top. Each also shows a small arrow comparing
   the current value with 30 days earlier - green when the direction is good
   news (returns rising), red when it is bad news (displacement rising). */
function renderStats() {
  const h = state.data.headline, t = state.current;
  const set = (sel, metric, risingIsGood) => {
    const s = h[metric];
    const v = s ? seriesAt(s.series, t) : null;
    const prev = s ? seriesAt(s.series, t - 30 * DAY) : null;
    let trend = "";
    if (v && prev && Math.abs(v - prev) > v * 0.005) {
      const up = v > prev;
      const good = up === risingIsGood;
      trend = `<span class="trend" style="color:${good ? COLOR_IN : COLOR_EVENT}">${up ? "▲" : "▼"}</span>`;
    }
    $(sel + " .stat-value").innerHTML = (v ? fmtNum(v) : "–") + trend;
  };
  set("#stat-displaced", "total_displaced", false);
  set("#stat-idps", "idps", false);
  set("#stat-crossborder", "cumulative_arrivals", false);
  set("#stat-returns", "returns_to_sudan_total", true);
}

/* --------- right-hand panel: insights, voices and triggers -------------- */

/* All tags of one dimension for one month, as [tag, count, sample sentence],
   biggest first. */
function monthTagTotals(dim, mk) {
  const out = [];
  for (const [tag, tagData] of Object.entries(state.data.tags[dim] || {})) {
    const n = tagData.monthly.filter((r) => r.month === mk).reduce((a, r) => a + r.count, 0);
    if (n) out.push([tag, n, tagData.snippets[mk]]);
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
    const now = seriesAt(c.series, t), prev = seriesAt(c.series, t - 90 * DAY);
    if (now && prev && now > prev && (!best || now - prev > best.delta))
      best = { cid, delta: now - prev, now };
  }
  if (best)
    items.push({ ico: "🔺", html: `Largest recent outflow: <b>${corridorName(best.cid)}</b> grew by <b>${fmtNum(best.delta)}</b> people in the last 3 months (now ${fmtNum(best.now)}).` });
  // returns trend
  const rs = state.data.headline.returns_to_sudan_total;
  const rNow = rs && seriesAt(rs.series, t), rPrev = rs && seriesAt(rs.series, t - 90 * DAY);
  if (rNow && rPrev && rNow > rPrev)
    items.push({ ico: "🟢", good: true, html: `Returns to Sudan rising: <b>+${fmtNum(rNow - rPrev)}</b> in 3 months, <b>${fmtNum(rNow)}</b> in total.` });
  // IDP direction
  const is = state.data.headline.idps;
  const iNow = is && seriesAt(is.series, t), iPrev = is && seriesAt(is.series, t - 90 * DAY);
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
    : `<div style="font-size:12px;color:var(--muted)">Drag the timeline forward to see insights build up.</div>`;
}

/* Up to three verbatim sentences from the reports for this month - the human
   voice behind the numbers. */
function renderVoices() {
  const mk = monthKey(state.current), el = $("#voices");
  const picks = [];
  for (const dim of Object.keys(DIM_META)) {
    for (const [tag, n, snippet] of monthTagTotals(dim, mk)) {
      if (snippet) { picks.push({ dim, tag, snippet }); break; }
    }
    if (picks.length >= 3) break;
  }
  el.innerHTML = picks.length
    ? picks.map((p) => `<div class="voice" style="border-color:${DIM_META[p.dim].color}">“…${p.snippet}…”
        <div class="v-meta">${DIM_META[p.dim].label} · ${p.tag.replace(/_/g, " ")} · ${new Date(state.current).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</div></div>`).join("")
    : `<div style="font-size:12px;color:var(--muted)">No narrative reporting captured for this month.</div>`;
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
  const shown = state.data.events
    .filter((e) => Date.parse(e.date) <= t && (e.source === "curated" || e.severity >= 2))
    .slice(-40).reverse();
  for (const ev of shown) {
    const div = document.createElement("div");
    div.className = `event-item ${ev.source} ${ev.severity >= 4 ? "major" : ""}`;
    div.innerHTML = `<div class="ev-date">${fmtDate(Date.parse(ev.date))}${ev.location ? " · " + ev.location : ""}</div>
      <div class="ev-title">${ev.title}</div>`;
    if (ev.lat) div.addEventListener("click", () => map.flyTo({ center: [ev.lon, ev.lat], zoom: 6 }));
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
  if (!state.showFoodsec || !state.data.ipc) { map.getSource("ipc").setData(empty()); return; }
  const d = ipcPeriodAt(state.current);
  map.getSource("ipc").setData(d ? state.data.ipc.periods[d] : empty());
}

/* One bubble per locality (admin2) inside Sudan, sized by its IDP count. This
   is genuine per-location data from the IOM Displacement Tracking Matrix. */
function renderIDP() {
  if (!state.showIDP) { map.getSource("idp").setData(empty()); return; }
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
  map.getSource("idp").setData({ type: "FeatureCollection", features: feats });
}

/* The same idea one level up: one bubble per Sudanese state (admin1). */
function renderIDPStates() {
  if (!state.showIDPStates || !state.data.idp_states) {
    map.getSource("idp-states").setData(empty());
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
  map.getSource("idp-states").setData({ type: "FeatureCollection", features: feats });
}

/* Two things at once: a big bubble per host country sized by its refugee
   total (the only level at which a time series exists), and small dots for
   individual camps, which appear on the map from the month they opened. */
function renderRefugees() {
  if (!state.showRefugees) {
    map.getSource("refcountry").setData(empty());
    map.getSource("refcamps").setData(empty());
    return;
  }
  const t = state.current, cfeats = [];
  for (const c of state.data.refugee_camps.countries) {
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
  map.getSource("refcountry").setData({ type: "FeatureCollection", features: cfeats });
  const cam = [];
  for (const m of state.data.refugee_camps.camps) {
    if (Date.parse(m.opened + "-01") > t) continue;
    cam.push({
      type: "Feature", geometry: { type: "Point", coordinates: [m.lon, m.lat] },
      properties: { radius: 3 + m.size * 1.6, name: m.name, type: m.type,
                    country: m.country, opened: m.opened },
    });
  }
  map.getSource("refcamps").setData({ type: "FeatureCollection", features: cam });
}

/* Border crossings. A crossing lights up when either of its corridors had
   people moving through it on this date. */
function renderCrossings() {
  if (!state.showCrossings) { map.getSource("crossings").setData(empty()); return; }
  const t = state.current, feats = [];
  for (const c of state.data.crossings.points) {
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
  map.getSource("crossings").setData({ type: "FeatureCollection", features: feats });
}

/* The 14 IFRC Areas of Interest, coloured by their current IPC phase. */
function renderAOI() {
  map.getSource("aoi").setData(state.showAOI ? state.data.aoi : empty());
}

const CAL_MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

/* The seasonal calendar strip: lean, rainy and harvest bands, with the month
   the timeline is currently in highlighted. */
function renderSeasonal() {
  const el = $("#seasonal-cal");
  if (!el || !state.data.seasonal) return;
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

/* Redraw everything for state.current. This runs on every slider move, so
   each render*() function above must stay fast and must not fetch anything. */
function renderAll() {
  renderFoodsec();
  renderFlows();
  renderCrossings();
  renderIDP();
  renderIDPStates();
  renderRefugees();
  renderEvents();
  renderThemes();
  renderStats();
  renderEventList();
  renderInsights();
  renderVoices();
  renderTriggers();
  renderSeasonal();
  $("#current-date").textContent = fmtDate(state.current);
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
  const vmax = Math.max(...SERIES.flatMap(([m]) =>
    (state.data.headline[m]?.series || []).map((p) => p.value)), 1);
  for (const [metric, color] of SERIES) {
    const s = state.data.headline[metric]?.series || [];
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
  for (const ev of state.data.events.filter((e) => e.source === "curated" && e.severity >= 4)) {
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
  $("#toggle-flows").addEventListener("change", (e) => { state.showFlows = e.target.checked; renderFlows(); });
  $("#toggle-returns").addEventListener("change", (e) => { state.showReturns = e.target.checked; renderFlows(); });
  $("#toggle-events").addEventListener("change", (e) => { state.showEvents = e.target.checked; renderEvents(); });
  $("#toggle-idp").addEventListener("change", (e) => { state.showIDP = e.target.checked; renderIDP(); });
  $("#toggle-idp-states").addEventListener("change", (e) => { state.showIDPStates = e.target.checked; renderIDPStates(); });
  $("#toggle-refugees").addEventListener("change", (e) => { state.showRefugees = e.target.checked; renderRefugees(); });
  $("#toggle-foodsec").addEventListener("change", async (e) => {
    state.showFoodsec = e.target.checked;
    if (state.showFoodsec && !state.data.ipc) {
      e.target.disabled = true;
      state.data.ipc = await fetch("data/ipc_areas_fs.geojson").then((r) => r.json());
      e.target.disabled = false;
    }
    renderFoodsec();
  });
  $("#toggle-crossings").addEventListener("change", (e) => { state.showCrossings = e.target.checked; renderCrossings(); });
  $("#toggle-aoi").addEventListener("change", (e) => { state.showAOI = e.target.checked; renderAOI(); });
}

/* Build the theme toggles from the data itself: one expandable group per
   dimension, and inside it one checkbox per tag the pipeline actually found.
   Add a new tag to taxonomy.json and it appears here automatically. */
function initThemeControls() {
  const wrap = $("#dim-groups");
  for (const [dim, meta] of Object.entries(DIM_META)) {
    const tags = Object.keys(state.data.tags[dim] || {}).sort();
    if (!tags.length) continue;
    const g = document.createElement("div");
    g.className = "dim-group";
    const header = document.createElement("button");
    header.className = "dim-header";
    header.innerHTML = `<span class="caret">▸</span>
      <span class="dim-dot" style="background:${meta.color}"></span>${meta.label}
      <span class="dim-count">${tags.length}</span>`;
    const body = document.createElement("div");
    body.className = "dim-body";
    for (const tag of tags) {
      const key = `${dim}|${tag}`;
      const label = document.createElement("label");
      label.className = "tag-check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.addEventListener("change", () => {
        cb.checked ? state.activeTags.add(key) : state.activeTags.delete(key);
        renderThemes();
      });
      label.appendChild(cb);
      label.insertAdjacentHTML("beforeend",
        `<span class="dot" style="background:${meta.color}"></span>${tag.replace(/_/g, " ")}`);
      body.appendChild(label);
    }
    header.addEventListener("click", () => {
      g.classList.toggle("open");
      header.querySelector(".caret").textContent = g.classList.contains("open") ? "▾" : "▸";
    });
    g.appendChild(header);
    g.appendChild(body);
    wrap.appendChild(g);
  }
}

/* ========================= 8. BOOT =====================================
 * The starting point. Everything above is a definition; these lines run.
 * ======================================================================== */
(async function boot() {
  // Download the data and create the map at the same time, then wire it up.
  await Promise.all([loadData(), initMap()]);
  addLayers();
  initTimeline();
  initControls();
  initThemeControls();
  drawSparkline();
  window.addEventListener("resize", drawSparkline);
  // open the story at the beginning
  renderAll();
})();
