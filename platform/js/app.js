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
// binary colour rule: red = movement out of Sudan, green = movement back into Sudan
const COLOR_OUT = "#e53935";
const COLOR_IN = "#43a047";
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
  activeTags: new Set(),   // "dimension|tag" keys toggled on
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
  $("#last-updated").textContent = fmtDate(state.endDate);
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
      "text-halo-color": "#0e1116", "text-halo-width": 1.2,
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
}

const empty = () => ({ type: "FeatureCollection", features: [] });

/* ------------------------------------------------------------------ render */
function corridorName(id) {
  return id.replace(/-/g, " → ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

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
      trend = `<span class="trend" style="color:${good ? "#43a047" : "#ef5350"}">${up ? "▲" : "▼"}</span>`;
    }
    $(sel + " .stat-value").innerHTML = (v ? fmtNum(v) : "–") + trend;
  };
  set("#stat-displaced", "total_displaced", false);
  set("#stat-idps", "idps", false);
  set("#stat-crossborder", "cumulative_arrivals", false);
  set("#stat-returns", "returns_to_sudan_total", true);
}

/* ---------------- right panel: insights, voices, triggers ---------------- */
function monthTagTotals(dim, mk) {
  const out = [];
  for (const [tag, tagData] of Object.entries(state.data.tags[dim] || {})) {
    const n = tagData.monthly.filter((r) => r.month === mk).reduce((a, r) => a + r.count, 0);
    if (n) out.push([tag, n, tagData.snippets[mk]]);
  }
  return out.sort((a, b) => b[1] - a[1]);
}

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
  renderInsights();
  renderVoices();
  renderTriggers();
  $("#current-date").textContent = fmtDate(state.current);
}

/* ------------------------------------------------------------------ sparkline */
function drawSparkline() {
  const canvas = $("#sparkline");
  const w = (canvas.width = canvas.offsetWidth * devicePixelRatio);
  const hpx = (canvas.height = 48 * devicePixelRatio);
  const ctx = canvas.getContext("2d");
  const span = state.endDate - START;
  // all series share one scale so relative magnitudes stay honest
  const SERIES = [
    ["total_displaced", "#ff7043"],
    ["cumulative_arrivals", "#e53935"],
    ["returns_to_sudan_total", "#43a047"],
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
  ctx.fillStyle = "rgba(255,213,79,.8)";
  for (const ev of state.data.events.filter((e) => e.source === "curated" && e.severity >= 4)) {
    const x = ((Date.parse(ev.date) - START) / span) * w;
    ctx.fillRect(x, hpx - 6 * devicePixelRatio, 1.5 * devicePixelRatio, 6 * devicePixelRatio);
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
}

/* build one expandable group per dimension, with a checkbox per specific tag */
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

/* ------------------------------------------------------------------ boot */
(async function boot() {
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
