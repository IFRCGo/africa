/* The banner on the Data sources page.
 *
 * WHY THIS EXISTS: so nobody has to open Pull jobs to find out whether a pull
 * worked. It polls only while something is running, and it keeps showing the
 * last outcome afterwards - a pull that failed while you were on another tab is
 * still on the page when you come back.
 */
(function () {
  "use strict";

  var box = document.getElementById("api-calls-activity");
  if (!box) return;

  var IDLE_MS = 15000;   // nothing running: check rarely
  var BUSY_MS = 3000;    // something running: keep the count moving
  var timer = null;

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function bar(job) {
    if (!job.total) return "";
    var pct = Math.round((job.done / job.total) * 100);
    return '<div class="api-calls-track"><div class="api-calls-fill" style="width:' + pct + '%"></div></div>' +
           '<span class="api-calls-note">' + job.done + " of " + job.total + "</span>";
  }

  function line(job) {
    var right;
    if (job.status === "succeeded") {
      right = '<span class="api-calls-note">' + esc(job.message || "done") + "</span>";
    } else if (job.status === "failed") {
      right = '<span class="api-calls-note">' + esc(job.message || "failed") + "</span>";
    } else {
      right = bar(job) + (job.note ? ' <span class="api-calls-note">' + esc(job.note) + "</span>" : "");
    }
    return '<div class="api-calls-job ' + esc(job.status) + '">' +
             '<span class="api-calls-target">' + esc(job.target) + "</span>" +
             '<span class="api-calls-note">' + esc(job.status) + "</span>" +
             '<span class="api-calls-spacer"></span>' + right +
             ' <a href="' + esc(job.url) + '">log</a>' +
           "</div>";
  }

  var wasBusy = false;

  function render(data) {
    var jobs = data.running.concat(data.finished);
    box.hidden = jobs.length === 0;
    box.innerHTML = jobs.map(line).join("");

    var busy = data.running.length > 0;
    // A run that has just ended changed the table underneath us - the freshness
    // dates, the row counts and which buttons are live are all stale now.
    if (wasBusy && !busy) { window.location.reload(); return; }
    wasBusy = busy;
    schedule(busy ? BUSY_MS : IDLE_MS);
  }

  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(poll, ms);
  }

  function poll() {
    fetch("activity/", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) render(d); else schedule(IDLE_MS); })
      .catch(function () { schedule(IDLE_MS); });   // a blip must not kill the poll
  }

  poll();
})();
