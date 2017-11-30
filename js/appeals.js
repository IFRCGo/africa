
function generateMaps(loc) {

    var itLocs = [];
        grLocs = [];
        huLocs = [];
        hrLocs = [];
        mkLocs = [];
        rsLocs = [];

    // Push locations to separate arrays by country
    for(var i = 0; i < loc.length; i++) {

        switch(loc[i]["#iso"]) {
            case "ITA":
                itLocs.push(loc[i]);
                break;
            case "GRC":
                grLocs.push(loc[i]);
                break;
            case "HRV":
                hrLocs.push(loc[i]);
                break;
            case "HUN":
                huLocs.push(loc[i]);
                break;
            case "MKD":
                itLocs.push(loc[i]);
                break;
            default:
                break;
        }
    }

  //var countryArray = [hr,mk,gr,hu,it,rs];

  // Create a unit projection.
  var projection = d3.geoEquirectangular();

  // Create a path generator.
  var path = d3.geoPath()
      .projection(projection);

  var svg = d3.select("div#map")
     .append("div")
     .classed("svg-container", true) //container class to make it responsive
     .append("svg")
     //responsive SVG needs these 2 attributes and no width and height attr
     .attr("preserveAspectRatio", "xMinYMin meet")
     .attr("viewBox", "0 0 600 650")
     //class to make it responsive
     .classed("svg-content-responsive", true);

  d3.json("../geo/IT.json", function(error, it) {
      if (error) throw error;

      var width = 500,
          height = 500;

      console.log(it);

      var country = topojson.feature(it, it.objects.ITA_adm1);

      projection
          .scale(1)
          .translate([0, 0]);

      // Compute the bounds of a feature of interest, then derive scale & translate.
      var b = path.bounds(country),
          s = .95 / Math.max((b[1][0] - b[0][0]) / width, (b[1][1] - b[0][1]) / height),
          t = [(width - s * (b[1][0] + b[0][0])) / 2, (height - s * (b[1][1] + b[0][1])) / 2];

      // Update the projection to use computed scale & translate.
      projection
          .scale(s)
          .translate(t);

      svg.append("path")
          .datum(country)
          .attr("class", "adm")
          .attr("d", path);

      svg.append("path")
          .datum(topojson.mesh(it, it.objects.ITA_adm1, function(a, b) { return a.id !== b.id; }))
          .attr("class", "adm-border")
          .attr("d", path);

      svg.selectAll("circle")
           .data(itLocs)
           .enter()
           .append("circle")
           .attr("cx", function(d) {
                   return projection([d['#geo+lon'], d['#geo+lat']])[0];
           })
           .attr("cy", function(d) {
                   return projection([d['#geo+lon'], d['#geo+lat']])[1];
           })
           .attr("r", 1)
           .style("fill", "#B71C1C");

      });

  function sizeChange() {
      d3.select("g").attr("transform", "scale(" + $("#map").width()/900 + ")");
      $("svg").height($("#map").width()*0.618);
}

}



