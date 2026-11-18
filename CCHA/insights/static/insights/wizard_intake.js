/* Step 1 and 2: pick documents on your own machine or paste links to them,
 * see what will be read, then send them one at a time.
 *
 * WHY THE FILTER RUNS BEFORE ANYTHING IS SENT. `webkitdirectory` hands over
 * EVERY file in the chosen folder, recursively - .DS_Store, photographs,
 * spreadsheets, all of it. Sending those to be rejected server-side would
 * upload gigabytes to throw away. They are listed as skipped instead, so the
 * filter is visible rather than silent.
 *
 * A LINK CANNOT BE FILTERED THE SAME WAY, and is not. What is behind a URL is
 * unknown until it is fetched, and the fetch has to happen server-side anyway:
 * a cross-origin PDF is not readable by script, and the bytes have to reach
 * the container to be catalogued at all. So a link's row says "web link" until
 * the server answers, and it is the server that decides it was a PDF, a Word
 * file, or a web page nobody wanted.
 *
 * WHY ONE REQUEST PER ITEM. Django's DATA_UPLOAD_MAX_NUMBER_FILES is 100, so a
 * folder of reports cannot go in one POST at all - and sequential requests give
 * an honest progress bar and a per-item error instead of one opaque failure.
 * Links are sent the same way for the second reason: one dead URL in a pasted
 * list of thirty must be one red row, not a failed batch.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-intake");
  if (!root) { return; }

  var KEEP = /\.(pdf|docx)$/i;

  /* Everything queued for this batch, files and links together, in the order
   * it was added. Appended to rather than replaced, so a folder and a handful
   * of links can go in as one batch. */
  var chosen = [];
  var skipped = 0;
  var sources = [];

  var preview = document.getElementById("wiz-preview");
  var rows = document.getElementById("wiz-rows");
  var count = document.getElementById("wiz-count");
  var progress = document.getElementById("wiz-progress");
  var fill = document.getElementById("wiz-bar-fill");
  var progressText = document.getElementById("wiz-progress-text");
  var sendButton = document.getElementById("wiz-send");
  var linkToggle = document.getElementById("wiz-link-toggle");
  var linkBox = document.getElementById("wiz-link-box");
  var linkText = document.getElementById("wiz-link-text");
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

  function cell(text, className) {
    var td = document.createElement("td");
    td.textContent = text;
    if (className) { td.className = className; }
    return td;
  }

  /* One line of the preview. textContent throughout, never innerHTML: these
   * names come off the operator's own disk or out of a pasted URL and would
   * land in the page unescaped otherwise. */
  function addRow(name, size, outcome, className) {
    var row = document.createElement("tr");
    if (className) { row.className = className; }
    row.appendChild(cell(name, "wiz-name"));
    row.appendChild(cell(size));
    row.appendChild(cell(outcome, "wiz-outcome"));
    rows.appendChild(row);
    return row;
  }

  /* Redraw the tally and the buttons after anything is added or cleared. */
  function refresh() {
    count.textContent = chosen.length + " document(s)" +
      (skipped ? ", " + skipped + " other file(s) skipped" : "");
    sendButton.disabled = chosen.length === 0;
    root.dataset.batchLabel = sources.join(" + ");
    showPreview(chosen.length > 0 || skipped > 0);
    progress.hidden = true;
  }

  /* Stage 1 of the preview: what the browser handed over, before a byte is
   * sent. The operator can still walk away at no cost. */
  function addFiles(fileList, label) {
    Array.prototype.forEach.call(fileList, function (file) {
      var relative = file.webkitRelativePath || file.name;
      var keep = KEEP.test(file.name);
      var row = addRow(
        relative, human(file.size),
        keep ? "will be read" : "not a PDF or Word file",
        keep ? "" : "is-skipped");

      if (keep) {
        chosen.push({ file: file, relative: relative, row: row });
      } else {
        skipped += 1;
      }
    });
    sources.push(label);
    refresh();
  }

  /* The same queue, from the textarea. Blank lines are dropped; nothing else
   * is judged here, because only the fetch can tell a report from a web page. */
  function addLinks(text) {
    var links = text.split("\n").map(function (line) {
      return line.trim();
    }).filter(function (line) {
      return line !== "";
    });

    links.forEach(function (link) {
      chosen.push({
        url: link,
        relative: link,
        row: addRow(link, "web link", "will be fetched")
      });
    });

    if (links.length) {
      sources.push(links.length + " link(s)");
      refresh();
    }
    return links.length;
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
      var taken = 0;

      function next(index) {
        if (index >= chosen.length) {
          /* NOTHING TAKEN MEANS STAY HERE. The reasons each item was left out
           * are the rows on this page, and navigating to the batch throws all
           * of them away - which is how an empty job that nobody can explain
           * gets made. Most likely with links: a report's landing page pasted
           * instead of the attachment on it is the common miss, and the row is
           * the only thing that says so. */
          if (taken === 0) {
            progressText.textContent =
              "Nothing could be read. Each row above says why - fix the links " +
              "or pick other files, then send again.";
            return Promise.resolve(null);
          }
          return post(withId(root.dataset.batchReadyUrl, jobId),
                      new URLSearchParams()).then(function () { return jobId; });
        }
        var item = chosen[index];
        var url;
        var body;

        if (item.url) {
          url = withId(root.dataset.linkUrl, jobId);
          body = new URLSearchParams({ url: item.url });
        } else {
          url = withId(root.dataset.batchFileUrl, jobId);
          body = new FormData();
          body.append("file", item.file);
          body.append("relative_path", item.relative);
        }

        return post(url, body)
          .then(function (result) {
            var outcome = item.row.querySelector(".wiz-outcome");
            if (result.outcome === "catalogued") {
              taken += 1;
              outcome.textContent = result.pages + " page(s)";
            } else if (result.outcome === "duplicate") {
              /* Counted: a duplicate is attached to this batch and extracted
               * with it, so a batch of nothing but duplicates is a full one. */
              taken += 1;
              outcome.textContent = "already catalogued (identical file)";
            } else {
              /* "skipped" is not a failure - a link to a web page is the same
               * outcome as a photograph inside a chosen folder, and is greyed
               * rather than reddened. */
              item.row.className =
                result.outcome === "skipped" ? "is-skipped" : "is-failed";
              outcome.textContent = result.message;
            }
            done += 1;
            fill.style.width = Math.round(done * 100 / chosen.length) + "%";
            progressText.textContent = "Read " + done + " of " + chosen.length;
            return next(index + 1);
          });
      }

      return next(0).then(function (closed) {
        /* Null when nothing was taken: the message is already on the page and
         * this one stays put. Send is left disabled - re-sending would fetch
         * the same bad links again; "Start again" is the way on. */
        if (closed) { window.location = withId(root.dataset.jobUrl, closed); }
      });
    }).catch(function (error) {
      progressText.textContent = "Could not finish: " + error.message;
      sendButton.disabled = false;
    });
  }

  document.getElementById("wiz-files").addEventListener("change", function (event) {
    addFiles(event.target.files, event.target.files.length + " files");
    /* Cleared so choosing the SAME files again still fires a change event -
     * without this, adding a file, clearing, and re-picking it does nothing. */
    event.target.value = "";
  });

  document.getElementById("wiz-folder").addEventListener("change", function (event) {
    var first = event.target.files[0];
    var folder = first && first.webkitRelativePath
      ? first.webkitRelativePath.split("/")[0] : "a folder";
    addFiles(event.target.files, "folder: " + folder);
    event.target.value = "";
  });

  document.getElementById("wiz-clear").addEventListener("click", function () {
    chosen = [];
    skipped = 0;
    sources = [];
    rows.replaceChildren();
    showPreview(false);
    progress.hidden = true;
  });

  if (linkToggle) {
    linkToggle.addEventListener("click", function () {
      linkBox.hidden = !linkBox.hidden;
      linkToggle.setAttribute("aria-expanded", String(!linkBox.hidden));
      if (!linkBox.hidden) { linkText.focus(); }
    });
  }

  if (linkText) {
    document.getElementById("wiz-add-links").addEventListener("click", function () {
      /* Emptied on success so the same links cannot be queued twice by a second
       * click - the server would dedup them, but only after fetching each one
       * again, which is the cost this avoids. */
      if (addLinks(linkText.value)) { linkText.value = ""; }
    });
  }

  sendButton.addEventListener("click", send);

  if (stepTwo) {
    stepTwo.addEventListener("click", function () {
      preview.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}());
