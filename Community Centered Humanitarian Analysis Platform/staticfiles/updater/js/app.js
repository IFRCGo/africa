// Behaviour of the updater page at /updater/: the new-PDF count, the live
// progress bar (Server-Sent Events) and the external-layer freshness table.
// Loaded by updater/templates/updater/index.html with {% static %}.
// Address of the dashboard, read from <body data-dashboard-url> which
// Django fills in from the DASHBOARD_URL setting.
const DASH = document.body.dataset.dashboardUrl;
// Tiny shortcut so we can write $("bar") instead of document.getElementById("bar").
const $ = id => document.getElementById(id);

// ---- Card 1: ask the server how many new PDFs are waiting ------------------
async function refreshStatus() {
  $("btn-refresh").disabled = true;
  try {
    const r = await fetch("/updater/api/status");
    const s = await r.json();
    const c = $("count");
    c.textContent = s.new_count;
    c.classList.toggle("zero", s.new_count === 0);
    $("count-sub").textContent = s.new_count === 0
      ? `No new PDFs. ${s.db_total} documents already in the tracker.`
      : `new PDF${s.new_count===1?"":"s"} ready to ingest - ${s.db_total} already in the tracker`;
    const f = $("files");
    if (s.new_files.length) {
      f.classList.remove("hidden");
      f.innerHTML = s.new_files.map(n => `<div>- ${n}</div>`).join("")
        + (s.more ? `<div style="color:#999">...and ${s.more} more</div>` : "");
    } else { f.classList.add("hidden"); f.innerHTML = ""; }
    // Re-running with 0 new files is still useful: it rebuilds every export.
    $("btn-update").disabled = s.running;
    $("btn-rebuild").disabled = s.running;
    $("btn-update").textContent = s.new_count === 0 ? "Rebuild anyway" : "Update now";
    // Say what is in the way. The buttons are disabled whenever anything holds
    // the tables these runs rewrite - including a pull started from Admin, which
    // this page cannot see any other way.
    if (s.running) {
      $("count-sub").textContent =
        `Waiting: ${s.running_detail || "another run"} is still going.`;
    }
  } catch (e) {
    $("count-sub").textContent = "Could not reach the updater service.";
  }
  $("btn-refresh").disabled = false;
}

function setBusy(b) {
  $("btn-update").disabled = b; $("btn-rebuild").disabled = b; $("btn-refresh").disabled = b;
}

// Add a changing ?t=... so the browser really reloads the dashboard.
function reloadDash() {
  $("dash").src = DASH + (DASH.includes("?") ? "&" : "?") + "t=" + Date.now();
}

// ---- Card 3: open a live connection and follow the pipeline ----------------
function runStream(url, title) {
  setBusy(true);
  $("progress-title").textContent = title;
  $("progress-card").classList.remove("hidden");
  $("done-row").classList.add("hidden");
  const bar = $("bar"); bar.className = ""; bar.style.width = "0%";
  const log = $("log"); log.style.display = "block"; log.textContent = "";
  $("phase").textContent = ""; $("pct").textContent = "0%";

  // EventSource keeps the connection open and fires onmessage for every
  // "data: {...}" line the server sends.
  const es = new EventSource(url);
  es.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "progress") {
      bar.style.width = m.pct + "%";
      $("pct").textContent = Math.round(m.pct) + "%";
      if (m.msg) $("phase").textContent = "- " + m.msg;
    } else if (m.type === "log") {
      log.textContent += m.msg + "\n";
      log.scrollTop = log.scrollHeight;      // keep the newest line in view
    } else if (m.type === "done") {
      bar.classList.add("done"); bar.style.width = "100%"; $("pct").textContent = "100%";
      $("phase").textContent = "- " + m.msg;
      reloadDash();
      $("done-row").classList.remove("hidden");
      es.close(); setBusy(false); refreshStatus(); loadExternal();
    } else if (m.type === "error") {
      bar.classList.add("err");
      $("phase").textContent = "- " + m.msg;
      es.close(); setBusy(false);
    }
  };
  es.onerror = () => { es.close(); setBusy(false); };
}

// ---- Card 2: fill the freshness table -------------------------------------
async function loadExternal() {
  try {
    const r = await fetch("/updater/api/external");
    const d = await r.json();
    const rows = d.layers.map(L => {
      const isMcp = L.kind.indexOf("MCP") >= 0;
      const fresh = L.cached ? `cache <b>${L.cached}</b>`
                  : (L.built ? `built <b>${L.built}</b>` : "-");
      const sub = (L.cached && L.built) ? `<div class="src">layer built ${L.built}</div>` : "";
      return `<tr>
        <td><span class="lyr">${L.label}</span><span class="tag ${isMcp?'mcp':''}">${L.kind}</span>
            <div class="src">${L.source} - ${L.detail}</div></td>
        <td class="fresh">${fresh}${sub}</td></tr>`;
    }).join("");
    $("ext-table").querySelector("tbody").innerHTML = rows;
  } catch (e) {
    $("ext-table").querySelector("tbody").innerHTML = "<tr><td>Could not load layer status.</td></tr>";
  }
}

// ---- Wire the buttons, then load everything once on page open --------------
$("btn-update").addEventListener("click", () => runStream("/updater/api/update", "Updating from new PDFs"));
$("btn-rebuild").addEventListener("click", () => runStream("/updater/api/rebuild-external", "Rebuilding external layers"));
$("btn-refresh").addEventListener("click", () => { refreshStatus(); loadExternal(); });
refreshStatus();
loadExternal();
