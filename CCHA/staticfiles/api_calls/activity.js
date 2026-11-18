/* The banner on the Data sources page.
 *
 * WHY THIS EXISTS: so nobody has to open Pull jobs to find out whether a pull
 * worked. It polls only while something is running, and it keeps showing the
 * last outcome afterwards - a pull that failed while you were on another tab is
 * still on the page when you come back.
 *
 * ONE BAR PER PRESS. "Pull everything out of date" claims a job per source - it
 * must, or the status column on each row has nothing to read - but those jobs
 * are not drawn: the server hides them (`parent` is set) and the batch's own bar
 * cites them from `items` instead. Nine bars for one press was the old page.
 */
(function () {
  "use strict";

  var box = document.getElementById("api-calls-activity");
  if (!box) return;

  var IDLE_MS = 15000;   // nothing running: check rarely
  var BUSY_MS = 3000;    // something running: keep the count moving
  // How long the per-source list stays up after a batch ends. Long enough to
  // read what failed, short enough that the summary line is what is left on the
  // page for the rest of the thirty-minute window.
  var RESULTS_MS = 120000;
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

  /* Should this job's per-source list be drawn?
   *
   * While it runs, and for two minutes after it ends. Computed from the
   * server's finished_at rather than held in a variable, because render()
   * reloads the page the moment a batch finishes - anything kept only in this
   * file is gone by the time the results matter.
   */
  function showResults(job) {
    if (!job.items || !job.items.length) return false;
    if (!job.finished_at) return true;
    var ended = Date.parse(job.finished_at);
    return !isFinite(ended) || (Date.now() - ended) < RESULTS_MS;
  }

  var WAITING = "waiting its turn";

  function item(entry) {
    var status = entry.status || "pending";
    var note = entry.message || (status === "pending" ? WAITING : "");
    return '<li class="api-calls-item ' + esc(status) + '">' +
             '<span class="api-calls-item-status">' + esc(status) + "</span>" +
             '<span class="api-calls-item-label">' + esc(entry.label) + "</span>" +
             (note ? '<span class="api-calls-note">' + esc(note) + "</span>" : "") +
           "</li>";
  }

  /* The count the summary under the list reads. Named states, not "done": a
   * batch that skipped four sources and pulled none has finished, and reading
   * "4 done" off it is how a person stops trusting the page. */
  function tally(items) {
    var seen = {};
    items.forEach(function (i) {
      var s = i.status || "pending";
      seen[s] = (seen[s] || 0) + 1;
    });
    return ["succeeded", "failed", "skipped", "running", "pending"]
      .filter(function (s) { return seen[s]; })
      .map(function (s) { return seen[s] + " " + (s === "pending" ? "still to come" : s); })
      .join(", ");
  }

  function results(job) {
    // The job's status rides along so the coloured spine down the left of the
    // bar continues past it: the list is part of that bar, not a second one.
    return '<div class="api-calls-results ' + esc(job.status) + '">' +
             "<ul>" + job.items.map(item).join("") + "</ul>" +
             '<div class="api-calls-note api-calls-tally">' + esc(tally(job.items)) + "</div>" +
           "</div>";
  }

  function block(job) {
    return line(job) + (showResults(job) ? results(job) : "");
  }

  var wasBusy = false;

  function render(data) {
    var jobs = data.running.concat(data.finished);
    box.hidden = jobs.length === 0;
    box.innerHTML = jobs.map(block).join("");

    var busy = data.running.length > 0;
    // A run that has just ended changed the table underneath us - the freshness
    // dates, the row counts and which buttons are live are all stale now.
    if (wasBusy && !busy) { window.location.reload(); return; }
    wasBusy = busy;
    // Keep polling through the results window even with nothing running: the
    // list has to take itself down without the operator reloading the page.
    // At the idle rate, though - it is a list expiring, not a count moving.
    if (busy) return schedule(BUSY_MS);
    schedule(IDLE_MS);
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
