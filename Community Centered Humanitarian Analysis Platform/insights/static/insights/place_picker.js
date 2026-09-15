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
 */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") { fn(); }
    else { document.addEventListener("DOMContentLoaded", fn); }
  }

  ready(function () {
    var country = document.getElementById("id_country");
    var state = document.getElementById("id_state");
    var district = document.getElementById("id_district");
    if (!country || !state || !district) { return; }

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
  });
}());
