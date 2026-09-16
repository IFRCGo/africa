/* Step 4: fetch an edit panel into a row, and put the row back after a save.
 *
 * The panel is the same InsightPlaceForm the Insights screen uses, rendered
 * server-side with a per-row prefix. Nothing about place resolution is decided
 * here - this file moves markup around and nothing else.
 */
(function () {
  "use strict";

  var root = document.getElementById("wiz-review");
  if (!root) { return; }

  function panelUrl(id) {
    return root.dataset.editUrl.replace("/0/", "/" + id + "/");
  }

  function rowFor(id) {
    return root.querySelector(".wiz-review-row[data-insight='" + id + "']");
  }

  function closePanel(row) {
    if (!row) { return; }
    var open = row.nextElementSibling;
    if (open && open.classList.contains("wiz-edit-holder")) { open.remove(); }
  }

  function wire(holder, id) {
    var form = holder.querySelector("form");
    if (window.insightsPlacePicker) { window.insightsPlacePicker.bind(form); }

    form.querySelector(".wiz-cancel").addEventListener("click", function () {
      closePanel(rowFor(id));
    });

    /* A formset grows by cloning its own empty_form and renumbering it - the
     * __prefix__ placeholder is what Django puts there for exactly this. */
    form.querySelector(".wiz-add-coding").addEventListener("click", function () {
      var total = form.querySelector("[name$='-TOTAL_FORMS']");
      var body = form.querySelector(".wiz-coding-rows");
      var template = form.querySelector(".wiz-coding-template").innerHTML;
      body.insertAdjacentHTML(
        "beforeend", template.replace(/__prefix__/g, total.value));
      total.value = String(Number(total.value) + 1);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      fetch(panelUrl(id), {
        method: "POST",
        credentials: "same-origin",
        body: new FormData(form)
      }).then(function (response) { return response.json(); })
        .then(function (body) {
          if (body.saved) {
            /* Replace the row in place rather than reloading: a reviewer
             * halfway down a long queue should not lose their position over
             * one correction. */
            rowFor(id).outerHTML = body.row;
            closePanel(rowFor(id));
            return;
          }
          holder.querySelector("td").innerHTML = body.panel;
          wire(holder, id);
        });
    });
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest(".wiz-edit");
    if (!button) { return; }

    var id = button.dataset.insight;
    var row = rowFor(id);
    if (row.nextElementSibling &&
        row.nextElementSibling.classList.contains("wiz-edit-holder")) {
      closePanel(row);
      return;
    }

    fetch(panelUrl(id), { credentials: "same-origin" })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var holder = document.createElement("tr");
        holder.className = "wiz-edit-holder";
        holder.innerHTML = "<td colspan='3'></td>";
        holder.querySelector("td").innerHTML = html;
        row.insertAdjacentElement("afterend", holder);
        wire(holder, id);
      });
  });
}());
