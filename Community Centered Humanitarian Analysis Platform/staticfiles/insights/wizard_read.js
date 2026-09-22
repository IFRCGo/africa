/* Step 2: read the documents with Docling, then watch it happen.
 *
 * The same polling loop as wizard_extract.js, for the same reasons: an SSE
 * connection would hold one of only eight gunicorn threads (2 workers x 4) for
 * the whole length of a run, and with OCR on every page this is the LONGER of
 * the two runs. A 2-second poll costs nothing, survives a slept laptop and a
 * proxy timeout, and picks the run back up when the page is reopened.
 *
 * The process itself is detached, so nothing here can kill it - including
 * closing the tab.
 *
 * WHY THIS RELOADS RATHER THAN RENDERING. The preview of what the model will
 * read is built by Django from the stored DocumentText rows. Assembling it
 * here would mean shipping every page of every document through the progress
 * endpoint, and rendering markdown in the browser - which would show something
 * other than the text that is actually stored, the one thing a preview of it
 * must not do.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-read");
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
  var continueButton = document.getElementById("wiz-continue");
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
    /* WHETHER THIS PAGE WAS WATCHING A RUN, captured before stop() clears it.
     * It is the whole difference between "a conversion just finished, so the
     * preview below is stale" and "this page was opened on a batch that was
     * already converted, and the preview below is the current one". Reloading
     * in the second case reloads forever: the new page polls on load, is told
     * "converted" again, and reloads again.
     *
     * Deliberately NOT the status the page was rendered at. A converted batch
     * can be read again - the Start button is on this page for exactly that -
     * and when that re-read finishes the preview really is stale and really
     * must be reloaded, even though the page was rendered "converted". */
    var wasWatching = timer !== null;
    var pct = body.total ? Math.round(body.done * 100 / body.total) : 0;
    fill.style.width = pct + "%";
    counters.textContent = body.done + " of " + body.total + " documents read";

    if (body.log_tail && body.log_tail !== log.textContent) {
      log.textContent = body.log_tail;
      log.scrollTop = log.scrollHeight;
    }

    if (body.status === "converted") {
      stop();
      stall.hidden = true;
      if (!wasWatching) { return; }
      say("Reading finished. Showing what the model will read…", null);
      window.location.reload();
      return;
    }

    if (body.status === "convert_failed") {
      stop();
      stall.hidden = true;
      startButton.disabled = false;
      startButton.textContent = "Try again";
      say("This run failed. The reason is at the end of the log above; the full " +
          "log is on the job itself. Nothing was lost — each document still has " +
          "the text it came in with.", "bad");
      return;
    }

    if (body.status === "converting") {
      startButton.disabled = true;
      var since = body.last_change ? Date.now() - Date.parse(body.last_change) : 0;
      if (since > STALL_MS) {
        /* Reported, never acted on. Nothing here tracks a pid, so nothing here
         * can tell a killed process from a slow document - and with OCR on, a
         * single scanned 40-page report legitimately takes a long time. The
         * button is the person's to press. */
        stallText.textContent =
          "No progress since " + new Date(body.last_change).toLocaleTimeString() +
          ". If the container was restarted, this run is gone and the batch has " +
          "to go back before it can be started again. If it is simply on a long " +
          "scanned document, leave it — nothing here can tell the two apart.";
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
    fetch(root.dataset.readUrl, {
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

  /* Only on the page once the reading is done - this is what moves the batch
   * to "queued", so that the operator has to have had the chance to look. */
  if (continueButton) {
    continueButton.addEventListener("click", function () {
      continueButton.disabled = true;
      fetch(root.dataset.doneUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf() }
      }).then(function (response) { return response.json(); })
        .then(function (body) {
          if (body.moved) { window.location = root.dataset.jobUrl; return; }
          continueButton.disabled = false;
          say(body.message, "warn");
        });
    });
  }

  /* One poll on load. If the batch was already being read when this page was
   * opened - a reload, or coming back to it tomorrow - keep watching. */
  fetch(root.dataset.progressUrl, { credentials: "same-origin" })
    .then(function (response) { return response.json(); })
    .then(function (body) {
      draw(body);
      if (body.status === "converting") { watch(); }
    });
}());
