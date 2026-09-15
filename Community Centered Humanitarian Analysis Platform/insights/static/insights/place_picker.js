/* Country > State/Region > District, refilled as you pick.
 *
 * This is a CONVENIENCE, not the validation. Every one of these dropdowns is
 * also filled server-side by InsightPlaceForm.__init__, and the p-codes are
 * checked against the boundary library in its clean() - so the form is correct
 * with JavaScript switched off, and cannot be fooled by editing the options in
 * a dev console. All this saves is the round trip.
 *
 * The endpoint is read off a data- attribute rather than hardcoded, because the
 * admin owns that URL (insights/admin.py, get_urls) and a path written twice is
 * a path that goes stale once.
 *
 * BOUND TO A CONTAINER, NOT TO IDS. The admin change form has exactly one set
 * of these and it is in the page at load. The wizard's review page has one set
 * PER ROW, each with its own form prefix, and injects them after load - so
 * "id_country" is there neither uniquely nor at all. The three are found by
 * data-place-role instead (set in InsightPlaceForm.__init__), and the review
 * page calls bind() on each panel as it arrives.
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") { fn(); }
    else { document.addEventListener("DOMContentLoaded", fn); }
  }

  function bind(root) {
    var country = root.querySelector("[data-place-role=country]");
    var state = root.querySelector("[data-place-role=state]");
    var district = root.querySelector("[data-place-role=district]");
    if (!country || !state || !district) { return; }

    /* A second bind() on an already-wired panel would stack a duplicate
     * listener, so every change fired two fetches and the later answer won. */
    if (country.dataset.placeBound) { return; }
    country.dataset.placeBound = "1";

    var endpoint = country.dataset.placeOptionsUrl;
    if (!endpoint) { return; }

    /* Replace a dropdown's options, keeping `selected` if it is still offered.
     * Keeping it matters on the way back from a failed save: the page is
     * re-rendered with the reviewer's choices, and this must not wipe the
     * district they picked just because the state list was rebuilt. */
    function fill(select, areas, selected) {
      var blank = new Option("---------", "");
      select.replaceChildren(blank);
      areas.forEach(function (area) {
        select.add(new Option(area.name, area.pcode, false, area.pcode === selected));
      });
      select.disabled = areas.length === 0;
    }

    function load(select, parent, level, selected) {
      if (!parent) {
        fill(select, [], "");
        return Promise.resolve();
      }
      select.disabled = true;
      var url = endpoint + "?parent=" + encodeURIComponent(parent) +
                "&level=" + encodeURIComponent(level);
      return fetch(url, { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) { throw new Error(response.status); }
          return response.json();
        })
        .then(function (body) { fill(select, body.areas || [], selected || ""); })
        .catch(function () {
          /* Leave whatever the server rendered rather than blanking a good
           * selection because one fetch failed. The reviewer can still save. */
          select.disabled = false;
        });
    }

    country.addEventListener("change", function () {
      /* Both children are cleared: a district is meaningless under a state that
       * is no longer selected, and leaving a stale one is exactly the mistake
       * clean() would refuse the save for. */
      fill(district, [], "");
      load(state, country.value, 1, "");
    });

    state.addEventListener("change", function () {
      load(district, state.value, 2, "");
    });
  }

  window.insightsPlacePicker = { bind: bind };
  ready(function () { bind(document); });
}());
