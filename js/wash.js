'use strict';
function generateDash(data,geom){
	updateKeyFigures(data);
	createMap(data,geom);
	createTable(data);
}

function createMap(data,geom){

    var baselayer = L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
    var baselayer2 = L.tileLayer('https://data.humdata.org/mapbox-layer-tiles/{z}/{x}/{y}.png', {minZoom:4});
	var region = "Africa";

	map = L.map('map',{
				center: [0,0],
		        zoom: 2,
		        layers: [baselayer,baselayer2]
			});

	var style = function(feature) {
		var color = '#aaaaaa';
		var fillOpacity = 0;
		var cls = 'country';

		if(data.map(function(e) { return e['#country+code']; }).indexOf(feature.properties.ISO_A3)>-1){
			color = '#D33F49';
			fillOpacity = 0.7;
			cls = 'appealcountry country appeal'+feature.properties.ISO_A3;
		}

        return {
                'color': color,
                'fillcolor': color,
                'weight': 1,
                'opacity': 0.7,
                'fillOpacity':fillOpacity,
                'className':cls
            };
    };

	map.overlay = L.geoJson(geom,{
		style:style,
		onEachFeature: function (feature, layer) {
                feature.properties.bounds_calculated=layer.getBounds();
            }
    }).addTo(map);
    var bbox = [[90,180],[-90,-180]];
    map.overlay.eachLayer(function(l){
    	if(data.map(function(e) { return e['#country+code'] }).indexOf(l.feature.properties['ISO_A3'])>-1){
    		if(bbox[0][0]>l.feature.properties.bounds_calculated._southWest.lat){bbox[0][0]=l.feature.properties.bounds_calculated._southWest.lat};
    		if(bbox[0][1]>l.feature.properties.bounds_calculated._southWest.lng){bbox[0][1]=l.feature.properties.bounds_calculated._southWest.lng};
    		if(bbox[1][0]<l.feature.properties.bounds_calculated._northEast.lat){bbox[1][0]=l.feature.properties.bounds_calculated._northEast.lat};
    		if(bbox[1][1]<l.feature.properties.bounds_calculated._northEast.lng){bbox[1][1]=l.feature.properties.bounds_calculated._northEast.lng};
		}
    });
    if(bbox[0][0] === 90){bbox = [[-80,-170],[80,170]];}
    var bounds = new L.LatLngBounds(bbox);
    map.fitBounds(bounds);
}

function updateKeyFigures(data){
	var totalstaff = 0;
	var totalndrt = 0;
	var totalrdrt = 0;
	var totalkit2 = 0;
	var totalkit5 = 0;
	var totalkit10 = 0;
	data.forEach(function(d,i){
		totalstaff+=parseInt(d['#capacity+total']);
		totalndrt+=parseInt(d['#capacity+ndrt']);
		totalrdrt+=parseInt(d['#capacity+rdrt']);
		if(!isNaN(d['#capacity+washkit2']) ) {
			totalkit2+=parseFloat(d['#capacity+washkit2']);
		}
		if(!isNaN(d['#capacity+washkit5']) ) {
			totalkit5+=parseFloat(d['#capacity+washkit5']);
		}
		if(!isNaN(d['#capacity+washkit10']) ) {
			totalkit10+=parseFloat(d['#capacity+washkit10']);
		}
	});
	$('#totalstaff').html(niceFormatNumber(totalstaff,false));
	$('#totalndrt').html(niceFormatNumber(totalndrt,false));
	$('#totalrdrt').html(niceFormatNumber(totalrdrt,false));
	$('#totalkit2').html(niceFormatNumber(totalkit2,false));
	$('#totalkit5').html(niceFormatNumber(totalkit5,false));
	$('#totalkit10').html(niceFormatNumber(totalkit10,false));
}

function niceFormatNumber(num,round){
	if(isNaN(num)){
		return num;
	} else {
		if(!round){
			var format = d3.format("0,000");
			return format(num);
		} else {
			var output = d3.format(".4s")(num);
	        if(output.slice(-1)==='k'){
	            output = Math.round(output.slice(0, -1) * 1000);
	            output = d3.format("0,000")(output);
	        } else if(output.slice(-1)==='M'){
	            output = d3.format(".1f")(output.slice(0, -1))+' million';
	        } else if (output.slice(-1) === 'G') {
	            output = output.slice(0, -1) + ' billion';
	        } else {
	            output = ''+d3.format(".3s")(num);
	        }
	        return output;
		}
	}
}

function hxlProxyToJSON(input,headers){
    var output = [];
    var keys=[];
    input.forEach(function(e,i){
        if(i===0){
            e.forEach(function(e2,i2){
                var parts = e2.split('+');
                var key = parts[0];
                if(parts.length>1){
                    var atts = parts.splice(1,parts.length);
                    atts.sort();
                    atts.forEach(function(att){
                        key +='+'+att;
                    });
                }
                keys.push(key);
            });
        } else {
            var row = {};
            e.forEach(function(e2,i2){
                row[keys[i2]] = e2;
            });
            output.push(row);
        }
    });
    return output;
}

function createTable(data) {
	var table='';
	data.forEach(function(d,i){
		table += '<tr><td>';
		table += d['#org'];
		table += '</td><td>';
		table += d['#capacity+total'];
		table += '</td><td>';
		table += d['#capacity+hq'];
		table += '</td><td>';
		table += d['#capacity+branch'];
		table += '</td><td>';
		table += d['#capacity+ndrt'];
		table += '</td><td>';
		table += d['#capacity+rdrt'];
		table += '</td><td>';
		table += d['#capacity+washkit2'];
		table += '</td><td>';
		table += d['#capacity+washkit5'];
		table += '</td><td>';
		table += d['#capacity+washkit10'];
		table += '</td><td>';
		table += d['#date+update'];
		table += '</td></tr>';
	});

	$('#washtable').append(table);
}
//global vars

var map = '';
var washurl = 'https://proxy.hxlstandard.org/data.json?strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1aYeTU8SaEt8ryxiVEoKqE5jsiLsSnPoDICRoCpwom3A%2Fedit%23gid%3D261283785';
var worldmap = 'https://ifrcgo.org/assets/map/worldmap.json';

var dataCall = $.ajax({
    type: 'GET',
    url: washurl,
    dataType: 'json',
});

var geomCall = $.ajax({
    type: 'GET',
    url: worldmap,
    dataType: 'json'
});

$.when(dataCall, geomCall).then(function(dataArgs, geomArgs){
    var data = hxlProxyToJSON(dataArgs[0]);
    console.log(data);
    var geom = topojson.feature(geomArgs[0],geomArgs[0].objects.geom);
    // $('#loadingmodal').modal('hide');
    generateDash(data,geom);
});
