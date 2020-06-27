function generateDash(data,geom){
	updateKeyFigures(data);
	createMap(data,geom);
}


function createMap(data,geom){

	$("#map-loading").remove();

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
		var cls = 'country'

		if(data.map(function(e) {
			var valISO = ""
			if (e['country'] !== null) {
				valISO = e['country']['iso'];
			}
			return valISO;
		}).indexOf(feature.properties['ISO_A2'].toLowerCase())>-1){
			color = '#D33F49';
			fillOpacity = 0.7;
			cls = 'appealcountry country appeal'+feature.properties['ISO_A2']
		};

        return {
                'color': color,
                'fillcolor': color,
                'weight': 1,
                'opacity': 0.7,
                'fillOpacity':fillOpacity,
                'className':cls
            };
    }

	map.overlay = L.geoJson(geom,{
		style:style,
		onEachFeature: function (feature, layer) {
                feature.properties.bounds_calculated=layer.getBounds();
            }
    }).addTo(map);
    var bbox = [[90,180],[-90,-180]];
    map.overlay.eachLayer(function(l){
    	if(data.map(function(e) {
			var valISO = ""
			if (e['country'] !== null) {
				valISO = e['country']['iso'];
			}
			return valISO;
		 }).indexOf(l.feature.properties['ISO_A2'].toLowerCase())>-1){
    		if(bbox[0][0]>l.feature.properties.bounds_calculated._southWest.lat){bbox[0][0]=l.feature.properties.bounds_calculated._southWest.lat};
    		if(bbox[0][1]>l.feature.properties.bounds_calculated._southWest.lng){bbox[0][1]=l.feature.properties.bounds_calculated._southWest.lng};
    		if(bbox[1][0]<l.feature.properties.bounds_calculated._northEast.lat){bbox[1][0]=l.feature.properties.bounds_calculated._northEast.lat};
    		if(bbox[1][1]<l.feature.properties.bounds_calculated._northEast.lng){bbox[1][1]=l.feature.properties.bounds_calculated._northEast.lng};
		};
    });
    if(bbox[0][0] == 90){bbox = [[-80,-170],[80,170]];}
    var bounds = new L.LatLngBounds(bbox);
    map.fitBounds(bounds);
}

function updateKeyFigures(data){
	var totalappeals = 0;
	var totalfunding = 0;
	var totalDREF = 0;
	var totalappeal = 0;
	var totalBen = 0;
	data.forEach(function(d,i){
		totalappeals+=parseFloat(d['amount_requested']);
		totalfunding+=parseFloat(d['amount_funded']);
		totalBen+=parseFloat(d['num_beneficiaries']);
		if(d['atype']==0){
			totalDREF +=1;
		} else {
			totalappeal +=1;
		}
	});
	$('#totalappeals').html(niceFormatNumber(totalappeals,true));
	$('#totalbens').html(niceFormatNumber(totalBen,true));
	$('#totalea').html(totalappeal);
	$('#totaldref').html(totalDREF);
	$('#totalcoverage').html('');
	createPie('#totalcoverage',120,15,totalfunding/totalappeals);
}

function createPie(id,width,inner,percent){

	var svg = d3.select(id).append("svg")
		.attr("width", width)
		.attr("height", width);

	var radius = width/2;

	var fundingArc = d3.svg.arc()
		.innerRadius(radius-inner)
		.outerRadius(radius)
		.startAngle(0)
		.endAngle(Math.PI*2*percent);

	var budgetArc = d3.svg.arc()
		.innerRadius(radius-inner)
		.outerRadius(radius)
		.startAngle(0)
		.endAngle(Math.PI*2);

	svg.append("path")
		.style("fill", "#dfdfdf")
		.attr("d", budgetArc)
		.attr("transform", "translate("+(width/2)+","+(width/2)+")");

	svg.append("path")
		.style("fill", "#D33F49")
		.attr("d", fundingArc)
		.attr("transform", "translate("+(width/2)+","+(width/2)+")");

	svg.append("text")
		.attr("x",width/2)
		.attr("y",width/2+5)
		.text(d3.format(".0%")(percent))
		.style("text-anchor", "middle");
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
	        if(output.slice(-1)=='k'){
	            output = Math.round(output.slice(0, -1) * 1000);
	            output = d3.format("0,000")(output);
	        } else if(output.slice(-1)=='M'){
	            output = d3.format(".1f")(output.slice(0, -1))+' million';
	        } else if (output.slice(-1) == 'G') {
	            output = output.slice(0, -1) + ' billion';
	        } else {
	            output = ''+d3.format(".3s")(num);
	        }
	        return output;
		}
	}
}


//global vars

var map = '';
var table='';
var appealsGoUrl = 'https://prddsgocdnapi.azureedge.net/api/v2/appeal/?format=json&end_date__gte=999999T00%3A00%3A00&region=0&status=0';
var worldmap = './maps/worldmap.json';
var today = new Date();
var dd = today.getDate();
var mm = today.getMonth()+1;
var yyyy = today.getFullYear();
if(dd<10) {
    dd='0'+dd
}
if(mm<10) {
    mm='0'+mm
}
var date = yyyy + '-' + mm + '-' + dd;
appealsGoUrl = appealsGoUrl.replace('999999',date);

var dataCall = $.ajax({
    type: 'GET',
    url: appealsGoUrl,
    dataType: 'json',
});

var geomCall = $.ajax({
    type: 'GET',
    url: worldmap,
    dataType: 'json'
});

$.when(dataCall, geomCall).then(function(dataArgs, geomArgs){
	var data = dataArgs[0].results;
    console.log(data);
    var geom = topojson.feature(geomArgs[0],geomArgs[0].objects.geom);
    generateDash(data,geom)
});
