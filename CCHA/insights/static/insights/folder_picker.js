/* Click down to a folder instead of typing a container path.
 *
 * WHY THIS IS NOT <input webkitdirectory>. That returns a path on the
 * reviewer's own machine - C:\Users\...\DTM Round 12 - and InsightFolder.path
 * has to name a directory inside THIS container. The two filesystems have
 * nothing to say to each other, so the browsing is done server-side and this
 * only draws the answers. See insights/admin_views.py.
 *
 * The typed field is left exactly as it was: this writes into it, and
 * InsightFolder.clean() still has the last word on save.
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") { fn(); }
    else { document.addEventListener("DOMContentLoaded", fn); }
  }

  ready(function () {
    var field = document.getElementById("id_path");
    if (!field) { return; }

    var endpoint = field.dataset.folderBrowseUrl;
    if (!endpoint) { return; }

    var open = document.createElement("button");
    open.type = "button";           /* not "submit" - this is inside the form */
    open.className = "button";
    open.textContent = "Browse\u2026";
    open.style.marginLeft = "0.5em";

    var panel = document.createElement("div");
    panel.hidden = true;
    panel.style.cssText =
      "margin-top:.6em;padding:.6em;border:1px solid var(--hairline-color,#e0e0e0);" +
      "background:var(--darkened-bg,#f8f8f8);max-width:46em;";

    field.insertAdjacentElement("afterend", open);
    open.insertAdjacentElement("afterend", panel);

    function row(label, onClick, muted) {
      var item = document.createElement("div");
      item.style.padding = ".15em 0";
      if (onClick) {
        var link = document.createElement("a");
        link.href = "#";
        link.textContent = label;
        link.addEventListener("click", function (event) {
          event.preventDefault();
          onClick();
        });
        item.appendChild(link);
      } else {
        item.textContent = label;
        if (muted) { item.style.color = "var(--body-quiet-color,#666)"; }
      }
      return item;
    }

    function render(body) {
      panel.replaceChildren();

      if (!body.path) {
        panel.appendChild(row("Start from:", null, true));
        (body.roots || []).forEach(function (root) {
          panel.appendChild(row(root.label, function () { show(root.path); }));
        });
        return;
      }

      var here = document.createElement("div");
      here.style.cssText = "font-weight:600;word-break:break-all;margin-bottom:.4em;";
      here.textContent = body.path;
      panel.appendChild(here);

      /* The count is what tells you this is the right folder before you commit
       * to it. Counted in this folder only - see the note in admin_views.py. */
      panel.appendChild(row(
        body.document_count === 1
          ? "1 PDF or DOCX directly in this folder"
          : body.document_count + " PDFs or DOCX files directly in this folder",
        null, true));

      var use = document.createElement("button");
      use.type = "button";
      use.className = "button";
      use.textContent = "Use this folder";
      use.style.margin = ".4em 0";
      use.addEventListener("click", function () {
        field.value = body.path;
        panel.hidden = true;
      });
      panel.appendChild(use);

      if (body.parent) {
        panel.appendChild(row("\u2191 up one level", function () { show(body.parent); }));
      }
      (body.entries || []).forEach(function (entry) {
        panel.appendChild(row("\u{1F4C1} " + entry.name, function () { show(entry.path); }));
      });
      if (!(body.entries || []).length) {
        panel.appendChild(row("No sub-folders here.", null, true));
      }
    }

    function show(path, note) {
      var url = endpoint + (path ? "?path=" + encodeURIComponent(path) : "");
      fetch(url, { credentials: "same-origin" })
        .then(function (response) {
          return response.json().then(function (body) {
            if (!response.ok) { throw new Error(body.error || response.status); }
            return body;
          });
        })
        .then(function (body) {
          render(body);
          if (note) { panel.prepend(row(note, null, true)); }
        })
        .catch(function (error) {
          var message = String(error.message || error);
          /* A path that cannot be listed - typed wrong, or a folder that has
           * since moved - must not strand the reviewer with nowhere to click.
           * Fall back to the roots, carrying the reason with us. */
          if (path) { show("", message); }
          else { panel.replaceChildren(row(message, null, true)); }
        });
    }

    open.addEventListener("click", function () {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) {
        /* Reopen where the field already points, so editing an existing folder
         * starts from that folder rather than back at the roots. */
        show(field.value.trim());
      }
    });
  });
}());
