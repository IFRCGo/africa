function generateDash(data,geom){
	updateTable(data);
	updateKeyFigures(data);
	createMap(data,geom);
}


function getAppealDocs(id){
	var url = 'https://proxy.hxlstandard.org/data.json?strip-headers=on&select-query01-01=%23meta%2Bid%3D' + id + '&filter02=cut&filter01=select&cut-include-tags02=%23meta%2Bdocumentname%2C%23date%2C%23meta%2Burl&force=on&url=https%3A//docs.google.com/spreadsheets/d/1gJ4N_PYBqtwVuJ10d8zXWxQle_i84vDx5dHNBomYWdU/edit%3Fusp%3Dsharing';

	console.log(url);

	$.ajax({
		    type: 'GET',
    		url: url,
    		dataType: 'json',
			success: function(result){
				var html = ''
				console.log(result);
				result.forEach(function(row,i){
					console.log(row);
					if(i>0){
						if(row[0].substring(0,1)=='/'){
							row[0] = 'http://www.ifrc.org'+row[0];
						}
						html+='<p><a href="'+row[0]+'" target="blank">'+row[1]+'</a> ('+row[2]+')</p>'
					}
				});
        		$("#"+id).html(html);
    		}
    	});
}

function updateTable(data){
	if ( $.fn.dataTable.isDataTable( '#datatable' ) ) {
    	table.destroy();
	}
	$('#data-table').html("");
	var html = "";
	data.forEach(function(d,i){
		if(d['atype']==0){
			//DREF
			var url = 'http://www.ifrc.org/en/publications-and-reports/appeals/?ac='+d['code']+'&at=0&c=&co=&dt=1&f=&re=&t=&ti=&zo='
		} else {
			//EA
			var url = 'http://ifrcgo.org/appeals/'+d['code'].toLowerCase()
		}
		html += '<tr><td>';
		html += getAppealType(d['atype']);
		html += '</td><td>'+d['name']+'</td><td>';
		html += getDisasterType(d['dtype']);
		html += '</td><td>'+d['start_date'].substr(0,10)+'</td><td>'+d['end_date'].substr(0,10);
		html +='</td><td>'+niceFormatNumber(d['num_beneficiaries'],false)+'</td><td>'+niceFormatNumber(d['amount_requested'],true)+'</td><td>'+niceFormatNumber(d['amount_funded'],true);
		html += '</td><td id="coverage'+i+'"></td><td><a href="'+url+'" target="_blank">'+d['code']+'</a></td></tr>';
	});
	$('#tcontents').html(html);
	data.forEach(function(d,i){
		createPie('#coverage'+i,65,10,d['amount_funded']/d['amount_requested']);
	});
    table = $('#datatable').DataTable({
    	"pageLength": 100,
    	"bFilter": false,
    	"aoColumnDefs" : [
	 		{
	   			'bSortable' : false,
	   			'aTargets' : [ 'sorting_disabled' ]
	 		}
	 	],
	 	"order": [[ 5, "desc" ]]
 	});
 	$('.details-controls').on('click',function () {
 		var appealID = $(this).attr('data-id');
 		var tr = $(this).closest('tr');
        var row = table.row( tr );
        if ( row.child.isShown() ) {
            row.child.hide();
            tr.removeClass('shown');
        }
        else {
            row.child('<h4>Latest Documents</h4><div id="'+appealID+'"></div>').show();
            getAppealDocs(appealID);
            tr.addClass('shown');
        }
 	});
}

function createMap(data,geom){

    var baselayer = L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
    var baselayer2 = L.tileLayer('https://data.humdata.org/mapbox-layer-tiles/{z}/{x}/{y}.png', {minZoom:4});

	map = L.map('map',{
				center: [0,0],
		        zoom: 2,
		        layers: [baselayer,baselayer2]
			});

	var style = function(feature) {
		var color = '#aaaaaa';
		var fillOpacity = 0;
		var cls = 'country'

//		if(data.map(function(e) { return e['country']['iso']; }).indexOf(feature.properties['ISO_A2'].toLowerCase())>-1){
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

function getAppealType(type) {
	var appealType;
	switch(type) {
		case 0:
			appealType = 'DREF';
			break;
		default:
			appealType = 'EA';
	}
	return appealType;
}

function getDisasterType(type) {
	var disaster;
	switch(type) {
		case 1:
			disaster = 'Epidemic';
			break;
		case 2:
			disaster = 'Earthquake';
			break;
		case 4:
			disaster = 'Cyclone';
			break;
		case 5:
			disaster = 'Population Movement';
			break;
		case 6:
			disaster = 'Complex Emergency';
			break;
		case 7:
			disaster = 'Civil Unrest';
			break;
		case 8:
			disaster = 'Volcanic Eruption';
			break;
		case 11:
			disaster = 'Tsunami';
			break;
		case 12:
			disaster = 'Flood';
			break;
		case 13:
			disaster = 'Other';
			break;
		case 14:
			disaster = 'Cold Wave';
			break;
		case 15:
			disaster = 'Fire';
			break;
		case 19:
			disaster = 'Heat Wave';
			break;
		case 20:
			disaster = 'Drought';
			break;
		case 21:
			disaster = 'Food Insecurity';
			break;
		case 23:
			disaster = 'Storm Surge';
			break;
		case 24:
			disaster = 'Landslide';
			break;
		case 27:
			disaster = 'Pluvial/Flash Flood';
			break;
		case 54:
			disaster = 'Transport Accident';
			break;
		case 57:
			disaster = 'Chemical Emergency';
			break;
		case 62:
			disaster = 'Insect Infestation';
			break;
		case 66:
			disaster = 'Biological Emergency';
			break;
		case 67:
			disaster = 'Radiological Emergency';
			break;
		case 68:
			disaster = 'Transport Emergency';
			break;
		default:
			disaster = 'other';
	}
	return disaster;
}

//global vars

var map = '';
var table='';
var appealsGoUrl = 'https://prddsgocdnapi.azureedge.net/api/v2/appeal/?format=json&end_date__gte=999999T00%3A00%3A00&region=0&status=0';
var worldmap = 'http://ifrcgo.org/assets/map/worldmap.json';
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

var downloadurl = 'https://prddsgocdnapi.azureedge.net/api/v2/appeal/?format=csv&end_date__gte=999999T00%3A00%3A00&region=0&status=0';
var downloadurl = downloadurl.replace('999999',date);
$('#download_link').html('<a href="'+downloadurl+'" download="current_appeals.csv">Download Data</a>');

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
    var geom = topojson.feature(geomArgs[0],geomArgs[0].objects.geom);
    generateDash(data,geom)
});
