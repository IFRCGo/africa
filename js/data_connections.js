/*************************************************
 * Script for pulling data from databases        *
 * using AJAX and then flattens data to an array *
 *************************************************/

// Global variables
var urlCall = "http://www.activityinfo.org/resources/sites/points?activity=";
var indicatorsAll = urlCall + 76763;

// Takes AJAX data call GeoJSON response and returns it as an array
function flattenData(response){
    output = [];
    response.features.forEach(function(f){
        row = {};
        for(var key in f.properties){
            if(key=='indicators'){
                for(var key2 in f.properties.indicators){
                    row[key2] = f.properties.indicators[key2];
                }
            } else {
                row[key] = f.properties[key];
            }
        }
        output.push(row);
    });
    //console.log(output);
    return output;
}

// Takes AJAX data call HXL response and returns it as an array
function hxlProxyToJSON(input,headers){
  var output = [];
  var keys=[];
  input.forEach(function(e,i){
      if(headers==true && i==0){
          keys = e;
      } else if(headers==true && i>1) {
          var row = {};
          e.forEach(function(e2,i2){
              row[keys[i2]] = e2;
          });
          output.push(row);
      } else if(headers!=true){
          var row = {};
          e.forEach(function(e2,i2){
              row[keys[i2]] = e2;
          });
          output.push(row);
      }
  });
  //console.log(output);
  return output;
}


/* Perform AJAX data calls and retrieve responses */

// Activity Info
var call01 = $.ajax({
    type: "GET",
    url: indicatorsAll,
    dataType: 'jsonp',
});

// Google Sheets Comms Feed
var call02 = $.ajax({
    type: 'GET',
    url: 'https://proxy.hxlstandard.org/data.json?strip-headers=on&force=on&url=https%3A//docs.google.com/spreadsheets/d/1G-j6_vHgh3pi6vM9TBMtmf9c78W6-TL76ImvEDWMDbQ/pub%3Fgid%3D313855999%26single%3Dtrue%26output%3Dcsv',
    dataType: 'json',
});

// Google Sheets Population Movement Feed
var call03 = $.ajax({
    type: 'GET',
    url: 'https://proxy.hxlstandard.org/data.json?strip-headers=on&force=on&url=https%3A//docs.google.com/spreadsheets/d/1_CvUyxAKmSn_G2vwMcbDlEevxThuP-4Bt30evXK4oMk/pub%3Fgid%3D0%26single%3Dtrue%26output%3Dcsv',
    dataType: 'json',
});

// Google Sheets Italy Locations
var call04 = $.ajax({
    type: 'GET',
    url: 'https://proxy.hxlstandard.org/data.json?strip-headers=on&force=on&url=https%3A//docs.google.com/spreadsheets/d/1crAaiHT0WFyQR3LNG9_tKZxPGWsTpbjljLXbGXhrttc/pub%3Fgid%3D1411482341%26single%3Dtrue%26output%3Dcsv'
})

// When data call is made, perform these operations
$.when(call01,call02,call03,call04).then(function(call01Args,call02Args,call03Args,call04Args){
    // Send data to be flattened
    var data = flattenData(call01Args[0]);
    var feed = hxlProxyToJSON(call02Args[0],true);
    var popMove = hxlProxyToJSON(call03Args[0],true);
    var loc = hxlProxyToJSON(call04Args[0],true);

    // Parse dates and sort by most recent first
    data.forEach(function(d){
        d['endDate']   = d3.timeParse("%Y-%m-%d")(d['endDate']);
        d['startDate'] = d3.timeParse("%Y-%m-%d")(d['startDate']);
    });
    feed.forEach(function(d){
        d['#date'] = d3.timeParse("%d/%m/%Y")(d['#date']);
    });
    popMove.forEach(function(d){
        d['#date'] = d3.timeParse("%d/%m/%Y")(d['#date']);
    });
    loc.forEach(function(d){
        d['#date'] = d3.timeParse("%d/%m/%Y")(d['#date']);
    });

    function sortByDateAscending(a,b) {
        //return a["endDate"] - b["endDate"]; // for earliest first
        return a["endDate"]>b["endDate"] ? -1 : a["endDate"]<b["endDate"] ? 1 : 0; // for most recent first
    }

    data = data.sort(sortByDateAscending);
    feed = feed.sort(sortByDateAscending);
    popMove = popMove.sort(sortByDateAscending);

    console.log("Activity Info: ", data);
    console.log("Comms Feed: ", feed);
    console.log("Pop Movement Appeals: ", popMove);
    console.log("Locations: ", loc);

    generateMaps(loc);
});
