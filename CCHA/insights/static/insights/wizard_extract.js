/* Step 3: start the extraction, then watch it.
 *
 * POLLED, NOT STREAMED. An SSE connection would hold one of only eight
 * gunicorn threads (2 workers x 4) for the whole length of an LLM run over
 * every document in the batch. A 2-second poll costs nothing, survives a
 * slept laptop and a proxy timeout, and picks the run back up when the page
 * is reopened.
 *
 * The process itself is detached, so nothing here can kill it - including
 * closing the tab.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-extract");
  if (!root) { return; }

  var STALL_MS = 10 * 60 * 1000;
  var POLL_MS = 2000;

  var fill = document.getElementById("wiz-bar-fill");
  var counters = document.getElementById("wiz-counters");
  var note = document.getElementById("wiz-note");
  var stall = document.getElementById("wiz-stall");
  var stallText = document.getElementById("wiz-stall-text");
  var log = document.getElementById("wiz-log");
  var startButton = document.getElementById("wiz-start");
  var timer = null;

  function csrf() {
    var field = root.querySelector("[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function say(text, kind) {
    note.textContent = text;
    note.className = "wiz-note" + (kind ? " is-" + kind : "");
    note.hidden = false;
  }

  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
  }

  function draw(body) {
    var pct = body.total ? Math.round(body.done * 100 / body.total) : 0;
    fill.style.width = pct + "%";
    counters.textContent =
      body.done + " of " + body.total + " documents · " +
      body.proposed + " statements proposed · " +
      body.unverifiable + " rejected as unverifiable · " +
      body.skipped_reviewed + " already reviewed";

    if (body.log_tail && body.log_tail !== log.textContent) {
      log.textContent = body.log_tail;
      log.scrollTop = log.scrollHeight;
    }

    if (body.status === "loaded") {
      stop();
      stall.hidden = true;
      say("Extraction finished. Opening the review step…", null);
      window.location = root.dataset.reviewUrl;
      return;
    }

    if (body.status === "failed") {
      stop();
      stall.hidden = true;
      startButton.disabled = false;
      startButton.textContent = "Try again";
      say("This run failed. The reason is at the end of the log above; the full " +
          "log is on the job itself.", "bad");
      return;
    }

    if (body.status === "running") {
      startButton.disabled = true;
      var since = body.last_change ? Date.now() - Date.parse(body.last_change) : 0;
      if (since > STALL_MS) {
        /* Reported, never acted on. Nothing here tracks a pid, so nothing here
         * can tell a killed process from a slow document - and resetting a job
         * that is actually still working would let two extractions of it run
         * at once. The button is the person's to press. */
        stallText.textContent =
          "No progress since " + new Date(body.last_change).toLocaleTimeString() +
          ". If the container was restarted, this run is gone and the batch has " +
          "to go back to queued before it can be started again. If it is simply " +
          "on a long document, leave it — nothing here can tell the two apart.";
        stall.hidden = false;
      } else {
        stall.hidden = true;
        note.hidden = true;
      }
    }
  }

  function poll() {
    return fetch(root.dataset.progressUrl, { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(draw)
      .catch(function () { /* a dropped poll is not a failed run; try again */ });
  }

  function watch() {
    if (!timer) { timer = window.setInterval(poll, POLL_MS); }
  }

  startButton.addEventListener("click", function () {
    startButton.disabled = true;
    fetch(root.dataset.extractUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() }
    }).then(function (response) { return response.json(); })
      .then(function (body) {
        if (body.started) { watch(); poll(); return; }
        startButton.disabled = false;
        say(body.message, "warn");
      });
  });

  /* One poll on load. If the batch was already under way when this page was
   * opened - a reload, or coming back to it tomorrow - keep watching. */
  fetch(root.dataset.progressUrl, { credentials: "same-origin" })
    .then(function (response) { return response.json(); })
    .then(function (body) {
      draw(body);
      if (body.status === "running") { watch(); }
    });
}());
