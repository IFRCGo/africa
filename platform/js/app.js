/* Sudan Crisis — Population Movement Tracker
 * Static MapLibre app: drag the timeline to replay the crisis from 15 Apr 2023.
 * Data: platform/data/*.json produced by pipeline/run_all.py from the SQLite story DB.
 */
"use strict";

const DAY = 86400000;
const START = Date.parse("2023-04-15");

// country anchors for thematic bubbles (mirror of pipeline/gazetteer.json)
const ANCHORS = {
  "Chad": [21.3, 13.6], "Egypt": [31.8, 24.5], "South Sudan": [32.8, 11.2],
  "Ethiopia": [36.5, 12.5], "Central African Republic": [22.9, 10.35],
  "Libya": [23.32, 24.18], "Uganda": [32.4, 1.2], "Eritrea": [36.66, 15.11],
  "Sudan": [29.5, 14.5], "Regional": [29.5, 19.5],
};
const FLOW_COLORS = { cross_border: "#ff7043", return: "#4caf50" };
const INFLUX_COLOR = "#29b6f6";
const DIM_META = {
  hazard: { label: "Hazards", color: "#ef5350" },
  vulnerability: { label: "Vulnerabilities", color: "#ab47bc" },
  coping: { label: "Coping mechanisms", color: "#26a69a" },
  need: { label: "Needs", color: "#42a5f5" },
  movement_pattern: { label: "Movement patterns", color: "#ffa726" },
};

const state = {
  data: {},
  endDate: null,
  current: START,
  playing: false,
  activeDims: new Set(),
  showFlows: true, showReturns: true, showEvents: true,
};

const $ = (s) => document.querySelector(s);
const fmtNum = (v) => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : String(v);
const fmtDate = (t) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const monthKey = (t) => new Date(t).toISOString().slice(0, 7);

/* value of a cumulative series at time t = last observation on or before t */
function seriesAt(series, t) {
  let v = null;
  for (const p of series) {
    if (Date.parse(p.date) > t) break;
    v = p.value;
  }
  return v;
}

/* quadratic-bezier arc between two points, bulging perpendicular to the line */
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

/* ------------------------------------------------------------------ load */
async function loadData() {
  const names = ["meta", "flows", "headline", "events", "tags", "documents"];
  const res = await Promise.all(names.map((n) => fetch(`data/${n}.json`).then((r) => r.json())));
  names.forEach((n, i) => (state.data[n] = res[i]));
  state.endDate = Date.parse(state.data.meta.date_max);
  $("#doc-count").textContent = state.data.meta.documents.toLocaleString();
}

/* ------------------------------------------------------------------ map */
let map;
function initMap() {
  map = new maplibregl.Map({
    container: "map",
    style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    center: [29.5, 15.2],
    zoom: 4.35,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  return new Promise((resolve) => map.on("load", resolve));
}

function addLayers() {
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
      "line-opacity": 0.85,
      "line-dasharray": [0.1, 1.6],
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
      "text-halo-color": "#0e1116", "text-halo-width": 1.6,
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
      "circle-color": "#ffd54f", "circle-opacity": 0.18, "circle-blur": 0.6,
    },
  });
  map.addLayer({
    id: "event-dots", type: "circle", source: "events",
    paint: {
      "circle-radius": ["get", "size"],
      "circle-color": ["case", ["==", ["get", "source"], "curated"], "#ffd54f", "#90a4ae"],
      "circle-stroke-color": "#0e1116", "circle-stroke-width": 1.4,
      "circle-opacity": ["get", "opacity"],
    },
  });

  map.on("click", "event-dots", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ closeButton: false })
      .setLngLat(e.lngLat)
      .setHTML(`<b style="color:#ffd54f">${fmtDate(Date.parse(p.date))}</b><br><b>${p.title}</b><br>${p.description || ""}`)
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

  animateDashes();
}

const empty = () => ({ type: "FeatureCollection", features: [] });

/* animated dash offset gives the arcs a sense of direction */
let dashStep = 0;
const DASH_SEQ = [[0.1, 1.6], [0.45, 1.6, 0.1, 1.15], [0.8, 1.6, 0.1, 0.8], [1.15, 1.6, 0.1, 0.45]];
function animateDashes() {
  setInterval(() => {
    if (!map.getLayer("flow-lines")) return;
    dashStep = (dashStep + 1) % DASH_SEQ.length;
    map.setPaintProperty("flow-lines", "line-dasharray", DASH_SEQ[dashStep]);
  }, 180);
}

/* ------------------------------------------------------------------ render */
function corridorName(id) {
  return id.replace(/-/g, " → ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderFlows() {
  const t = state.current;
  const lines = [], labels = [];
  for (const [cid, c] of Object.entries(state.data.flows)) {
    const isReturn = c.flow_type === "return";
    if (isReturn && !state.showReturns) continue;
    if (!isReturn && !state.showFlows) continue;
    const v = seriesAt(c.series, t);
    if (!v) continue;
    const color = cid.endsWith("influx") ? INFLUX_COLOR : FLOW_COLORS[c.flow_type];
    const o = [c.origin.lon, c.origin.lat], d = [c.destination.lon, c.destination.lat];
    const width = Math.max(1.5, Math.min(13, Math.sqrt(v) / 90));
    const pts = arc(o, d, isReturn ? -0.22 : 0.18);
    lines.push({
      type: "Feature", geometry: { type: "LineString", coordinates: pts },
      properties: {
        color, width,
        name: corridorName(cid),
        kind: isReturn ? "Return movement" : cid.endsWith("influx") ? "Influx into Sudan" : "Cross-border displacement",
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

function renderThemes() {
  const mk = monthKey(state.current);
  const feats = [];
  for (const dim of state.activeDims) {
    const tags = state.data.tags[dim] || {};
    const byCountry = {};
    for (const tagData of Object.values(tags))
      for (const row of tagData.monthly)
        if (row.month === mk && ANCHORS[row.country])
          byCountry[row.country] = (byCountry[row.country] || 0) + row.count;
    for (const [country, count] of Object.entries(byCountry)) {
      const [lon, lat] = ANCHORS[country];
      feats.push({
        type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] },
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

function renderThemePanel(mk) {
  const el = $("#theme-detail");
  el.innerHTML = "";
  for (const dim of state.activeDims) {
    const tags = state.data.tags[dim] || {};
    const totals = [];
    for (const [tag, tagData] of Object.entries(tags)) {
      const n = tagData.monthly.filter((r) => r.month === mk).reduce((a, r) => a + r.count, 0);
      if (n) totals.push([tag, n, tagData.snippets[mk]]);
    }
    totals.sort((a, b) => b[1] - a[1]);
    if (!totals.length) continue;
    const g = document.createElement("div");
    g.className = "theme-group";
    g.innerHTML = `<h3 style="color:${DIM_META[dim].color}">${DIM_META[dim].label} — ${new Date(state.current).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h3>`;
    for (const [tag, n, snippet] of totals.slice(0, 8)) {
      const row = document.createElement("div");
      row.className = "tag-row";
      row.innerHTML = `<span>${tag.replace(/_/g, " ")}</span><span class="cnt">${n} mention${n > 1 ? "s" : ""}</span>`;
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
  if (state.activeDims.size && !el.children.length)
    el.innerHTML = `<div style="font-size:12px;color:var(--muted)">No tagged reporting for this month.</div>`;
}

function renderStats() {
  const h = state.data.headline, t = state.current;
  const set = (sel, metric) => {
    const s = h[metric];
    const v = s ? seriesAt(s.series, t) : null;
    $(sel + " .stat-value").textContent = v ? fmtNum(v) : "–";
  };
  set("#stat-displaced", "total_displaced");
  set("#stat-idps", "idps");
  set("#stat-crossborder", "cumulative_arrivals");
  set("#stat-returns", "returns_to_sudan_total");
}

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

function renderAll() {
  renderFlows();
  renderEvents();
  renderThemes();
  renderStats();
  renderEventList();
  $("#current-date").textContent = fmtDate(state.current);
}

/* ------------------------------------------------------------------ sparkline */
function drawSparkline() {
  const canvas = $("#sparkline");
  const w = (canvas.width = canvas.offsetWidth * devicePixelRatio);
  const hpx = (canvas.height = 38 * devicePixelRatio);
  const ctx = canvas.getContext("2d");
  const s = state.data.headline.total_displaced?.series || [];
  if (s.length < 2) return;
  const span = state.endDate - START;
  const vmax = Math.max(...s.map((p) => p.value));
  ctx.strokeStyle = "#ff7043"; ctx.lineWidth = 2 * devicePixelRatio;
  ctx.beginPath();
  s.forEach((p, i) => {
    const x = ((Date.parse(p.date) - START) / span) * w;
    const y = hpx - (p.value / vmax) * (hpx - 6) - 3;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  // events as ticks
  ctx.fillStyle = "rgba(255,213,79,.8)";
  for (const ev of state.data.events.filter((e) => e.source === "curated" && e.severity >= 4)) {
    const x = ((Date.parse(ev.date) - START) / span) * w;
    ctx.fillRect(x, hpx - 5 * devicePixelRatio, 1.5 * devicePixelRatio, 5 * devicePixelRatio);
  }
}

/* ------------------------------------------------------------------ timeline */
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

/* ------------------------------------------------------------------ controls */
function initControls() {
  $("#toggle-flows").addEventListener("change", (e) => { state.showFlows = e.target.checked; renderFlows(); });
  $("#toggle-returns").addEventListener("change", (e) => { state.showReturns = e.target.checked; renderFlows(); });
  $("#toggle-events").addEventListener("change", (e) => { state.showEvents = e.target.checked; renderEvents(); });
  document.querySelectorAll(".dim input").forEach((cb) =>
    cb.addEventListener("change", () => {
      cb.checked ? state.activeDims.add(cb.value) : state.activeDims.delete(cb.value);
      renderThemes();
    }));
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  await Promise.all([loadData(), initMap()]);
  addLayers();
  initTimeline();
  initControls();
  drawSparkline();
  window.addEventListener("resize", drawSparkline);
  // open the story at the beginning
  renderAll();
})();
