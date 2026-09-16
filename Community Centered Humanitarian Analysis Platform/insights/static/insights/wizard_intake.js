/* Step 1 and 2: pick documents on your own machine, see what will be read,
 * then send them one at a time.
 *
 * WHY THE FILTER RUNS BEFORE ANYTHING IS SENT. `webkitdirectory` hands over
 * EVERY file in the chosen folder, recursively - .DS_Store, photographs,
 * spreadsheets, all of it. Sending those to be rejected server-side would
 * upload gigabytes to throw away. They are listed as skipped instead, so the
 * filter is visible rather than silent.
 *
 * WHY ONE REQUEST PER FILE. Django's DATA_UPLOAD_MAX_NUMBER_FILES is 100, so a
 * folder of reports cannot go in one POST at all - and sequential requests give
 * an honest progress bar and a per-file error instead of one opaque failure.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-intake");
  if (!root) { return; }

  var KEEP = /\.(pdf|docx)$/i;
  var chosen = [];

  var preview = document.getElementById("wiz-preview");
  var rows = document.getElementById("wiz-rows");
  var count = document.getElementById("wiz-count");
  var progress = document.getElementById("wiz-progress");
  var fill = document.getElementById("wiz-bar-fill");
  var progressText = document.getElementById("wiz-progress-text");
  var sendButton = document.getElementById("wiz-send");
  /* Step 2 in the chrome above. It is the one step with no page of its own -
   * the preview is this page - so the button is dead until there is a preview
   * to show, and then it just brings it into view. */
  var stepTwo = document.getElementById("wiz-step-preview");

  function showPreview(visible) {
    preview.hidden = !visible;
    if (stepTwo) {
      stepTwo.disabled = !visible;
      stepTwo.title = visible
        ? "Show what will be read." : "Pick files first - the preview appears below.";
    }
  }

  function csrf() {
    var field = root.querySelector("[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  /* Every URL is reversed by Django with a placeholder id of 0 and the real id
   * put in here. Deliberately not assembled from path fragments: the admin owns
   * these URLs, and a path written twice is a path that goes stale once. */
  function withId(template, id) {
    return template.replace("/0/", "/" + id + "/");
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() },
      body: body
    }).then(function (response) {
      if (!response.ok) { throw new Error(response.status); }
      return response.json();
    });
  }

  function human(bytes) {
    if (bytes < 1024) { return bytes + " B"; }
    if (bytes < 1048576) { return Math.round(bytes / 1024) + " KB"; }
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function cell(text) {
    var td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  /* Stage 1 of the preview: what the browser handed over, before a byte is
   * sent. The operator can still walk away at no cost. */
  function show(fileList, label) {
    chosen = [];
    rows.replaceChildren();
    var skipped = 0;

    Array.prototype.forEach.call(fileList, function (file) {
      var relative = file.webkitRelativePath || file.name;
      var row = document.createElement("tr");
      var keep = KEEP.test(file.name);

      if (keep) {
        chosen.push({ file: file, relative: relative, row: row });
      } else {
        skipped += 1;
        row.className = "is-skipped";
      }

      /* textContent, not innerHTML: these names come off the operator's own
       * disk and land in the page unescaped otherwise. */
      row.appendChild(cell(relative));
      row.appendChild(cell(human(file.size)));
      var outcome = cell(keep ? "will be read" : "not a PDF or Word file");
      outcome.className = "wiz-outcome";
      row.appendChild(outcome);
      rows.appendChild(row);
    });

    count.textContent = chosen.length + " document(s)" +
      (skipped ? ", " + skipped + " other file(s) skipped" : "");
    sendButton.disabled = chosen.length === 0;
    root.dataset.batchLabel = label;
    showPreview(true);
    progress.hidden = true;
  }

  /* Stage 2: send them one at a time, filling each row in as it lands. */
  function send() {
    sendButton.disabled = true;
    progress.hidden = false;

    post(root.dataset.batchUrl, new URLSearchParams({
      label: root.dataset.batchLabel
    })).then(function (opened) {
      var jobId = opened.job_id;
      var done = 0;

      function next(index) {
        if (index >= chosen.length) {
          return post(withId(root.dataset.batchReadyUrl, jobId),
                      new URLSearchParams());
        }
        var item = chosen[index];
        var body = new FormData();
        body.append("file", item.file);
        body.append("relative_path", item.relative);

        return post(withId(root.dataset.batchFileUrl, jobId), body)
          .then(function (result) {
            var outcome = item.row.querySelector(".wiz-outcome");
            if (result.outcome === "catalogued") {
              outcome.textContent = result.pages + " page(s)";
            } else if (result.outcome === "duplicate") {
              outcome.textContent = "already catalogued (identical file)";
            } else {
              item.row.className = "is-failed";
              outcome.textContent = result.message;
            }
            done += 1;
            fill.style.width = Math.round(done * 100 / chosen.length) + "%";
            progressText.textContent = "Read " + done + " of " + chosen.length;
            return next(index + 1);
          });
      }

      return next(0).then(function () {
        window.location = withId(root.dataset.jobUrl, jobId);
      });
    }).catch(function (error) {
      progressText.textContent = "Could not finish: " + error.message;
      sendButton.disabled = false;
    });
  }

  document.getElementById("wiz-files").addEventListener("change", function (event) {
    show(event.target.files, event.target.files.length + " files");
  });

  document.getElementById("wiz-folder").addEventListener("change", function (event) {
    var first = event.target.files[0];
    var folder = first && first.webkitRelativePath
      ? first.webkitRelativePath.split("/")[0] : "a folder";
    show(event.target.files, "folder: " + folder);
  });

  document.getElementById("wiz-clear").addEventListener("click", function () {
    chosen = [];
    rows.replaceChildren();
    showPreview(false);
    progress.hidden = true;
  });

  sendButton.addEventListener("click", send);

  if (stepTwo) {
    stepTwo.addEventListener("click", function () {
      preview.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}());
