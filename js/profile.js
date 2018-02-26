// Flatten hxl proxy data into JSON
function hxlProxyToJSON(input,headers){
    var output = [];
    var keys=[]
    input.forEach(function(e,i){
        if(i==0){
            e.forEach(function(e2,i2){
                var parts = e2.split('+');
                var key = parts[0]
                if(parts.length>1){
                    var atts = parts.splice(1,parts.length);
                    atts.sort();
                    atts.forEach(function(att){
                        key +='+'+att
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

// Number formatting
function niceFormatNumber(num,round){
    if(isNaN(parseFloat(num))){
        return num;
    } else {
        if(!round){
            var format = d3.format("0,000");
            return format(parseFloat(num));
        } else {
            var output = d3.format(".4s")(parseFloat(num));
            if(output.slice(-1)=='k'){
                output = Math.round(output.slice(0, -1) * 1000);
                output = d3.format("0,000")(output);
            } else if(output.slice(-1)=='M'){
                output = d3.format(".1f")(output.slice(0, -1))+' million';
            } else if (output.slice(-1) == 'G') {
                output = output.slice(0, -1) + ' billion';
            } else {
                output = ''+d3.format(".3s")(parseFloat(num));
            }
            return output;
        }
    }
}

// Generate tables for appeals and DREFs
function createAppealsTable(data){
    // Initialize html tables
    var html = "";

    // Run through data and prep for tables
    data.forEach(function(d,i){

        if(d['#severity']==='Emergency'){
            html += '<tr><td>'+d['#crisis+name']+'</td><td>'+d['#crisis+type']+'</td><td>Appeal</td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td><td>'+niceFormatNumber(d['#targeted'])+'</td><td>'+niceFormatNumber(d['#meta+value'])+'</td><td>'+d['#meta+id']+'</td></tr>';
        }
        if(d['#severity']==='Minor Emergency'){
            html += '<tr><td>'+d['#crisis+name']+'</td><td>'+d['#crisis+type']+'</td><td>DREF</td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td><td>'+niceFormatNumber(d['#targeted'])+'</td><td>'+niceFormatNumber(d['#meta+value'])+'</td><td>'+d['#meta+id']+'</td></tr>';
        }
    });
    // Send data to appeals or DREFs html tables
    $('#appealstable').append(html);
    
}

function createGovernanceTable(url) {
    // Initialize html tables
    var html = "";

	$.ajax({
		type: 'GET',
		url: url,
		dataType: 'json',
		success: function(result){
			var data = hxlProxyToJSON(result);
			console.log(data);

			// Run through data and prep for tables
			data.forEach(function(d,i){
				html += '<tr><th>President</th><td>'+d['#org+president']+'</td></tr>';
				html += '<tr><th>Last and next election</th><td>'+d['#date+election+last']+' / '+d['#date+election+next']+'</td></tr>';
				html += '<tr><th>Last Constitutional review</th><td>'+d['#date+constitutionalreview']+'</td></tr>';
				html += '<tr><th>Stategic Plan period</th><td>'+d['#org+strategicplan']+'</td></tr>';
				html += '<tr><th>Secretary General</th><td>'+d['#org+president']+'</td></tr>';
				html += '<tr><th>Programme Director</th><td>'+d['#org+sg']+'</td></tr>';
				html += '<tr><th>Latest Youth Policy</th><td>'+d['#date+policy+youth']+'</td></tr>';
				html += '<tr><th>Latest Volunteer Policy</th><td>'+d['#date+policy+volunteer']+'</td></tr>';
				html += '<tr><th>Latest Resource Mobilisation Policy</th><td>'+d['#date+policy+rm']+'</td></tr>';
				html += '<tr><th>Date OCAC / BOCA conducted</th><td>OCAC: '+d['#date+ocac']+' - BOCA: '+d['#date+boca']+'</td></tr>';
				html += '<tr><th>Last consolidated audit</th><td>'+d['#date+audit']+'</td></tr>';
			});
					// Send data to appeals or DREFs html tables
			$('#NSgovernanceTable').append(html);
			if (html!="") {
				$('#Overview').css("height","340px");
				$('#Overview').css("visibility","visible");
			}
		}
	})

    // Send data to appeals or DREFs html tables
    
	
}

// Generate tables for PNS projects
function createPNSsTable(url){
    // Initialize html tables
    var html = "";

	$.ajax({
		type: 'GET',
		url: url,
		dataType: 'json',
		success: function(result){
			var data = hxlProxyToJSON(result);
			console.log(data);

		// Run through data and prep for tables
			data.forEach(function(d,i){

				html += '<tr><td>'+d['#org+partner']+'</td><td>'+d['#activity+name']+'</td><td>'+d['#activity+sector']+'</td><td>'+d['#activity+budget']+'</td><td>'+d['#meta+funding']+'</td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td></tr>';
			});
			// Send data to appeals or DREFs html tables
			$('#pnstable').append(html);
		}
	})
}

// Fill the Key Figures
function loadFDRS(url){
    $.ajax({
            type: 'GET',
            url: url,
            dataType: 'json',
            success: function(result){
                var data = hxlProxyToJSON(result);
                console.log(data);
                data.forEach(function(d){

					$('#NoVolunteers').html( fillKeyFigureCard( 'People volunteering their time', d['#volunteer']) );
					
					if (d['#volunteer+f'] == '' || d['#volunteer'] == '') {
						$('#PercVolunteers').html( fillKeyFigureCard('Percentage of volunteers who are women', 'n/a' ) );
					} else {
						$('#PercVolunteers').html( fillKeyFigureCard('Percentage of volunteers who are women', Math.round(d['#volunteer+f'] / d['#volunteer'] * 100) ) );
					}


					$('#NoStaff').html( fillKeyFigureCard('Paid staff', d['#staff']) );

					$('#NoLocUnit').html( fillKeyFigureCard('Local units', d['#org+offices']) );

					$('#NoReachDR').html( fillKeyFigureCard('People Reached by Disaster Response Programmes', d['#reached+disaster_response']) );

					$('#NoReachedDev').html( fillKeyFigureCard('People Reached by Resilience Programmes', d['#reached+development_programme']) );

					$('#Income').html( fillKeyFigureCard('Income (in CHF)', d['#value+income']) );

					$('#Expenditure').html( fillKeyFigureCard('Expenditure (in CHF)', d['#value+expenditure']) );
					
					var NSname = d['#org+name'];
					var FDRSlink = 'http://data.ifrc.org/fdrs/societies/';
					FDRSlink += NSname.replace( / /g, '-');
					FDRSlink = FDRSlink.toLowerCase();
					
					$('#FDRSlink').prop( 'href', FDRSlink );
					
					$('#page-title').html( 'National Society Profile - ' + d['#org+name'] );
					
					$('#breadcrumb-country').html( d['#country+name'] );
					if (d['#region+name'] == 'Africa') {
						$('#breadcrumb-region').html( '<a href="/africa/profile_overview.html">Africa</a>' );
					} else {
						$('#breadcrumb-region').html( d['#region+name'] );
					}
					
                });
            }
    });
}


function fillKeyFigureCard (title, value) {
	if (value == '') {
		value = 'n/a';
	}
	
	var html = '<h4 class="keyfiguretitle text-center minheight">'+title+'</h4>';
	html += '<p class="keyfigure text-center">'+ niceFormatNumber(value,true) +'</p>';
	return html;
}

function loadINFORMindex(url) {
	var lvlNatural = [0,1.3,2.8,4.7,6.9];
	var lvlHuman = [0,1,3.1,7,9];
	var lvlHazard = [0,1.5,2.7,4.1,6.1];
	var lvlSocEc = [0,1.8,3.5,5.4,7.1];
	var lvlVulGrp = [0,1.6,2.9,4.4,6.3];
	var lvlVulna = [0,2,3.2,4.8,6.4];
	var lvlInstit = [0,3.3,4.9,6,7.3];
	var lvlInfra = [0,2.1,3.5,5.4,7.4];
	var lvlCoping = [0,3.2,4.7,6,7.4];
	var lvlRisk	= [0,2,3.5,5,6.5];
	var lvlClass = ["Very Low","Low","Medium","High","Very High"];
   $.ajax({
            type: 'GET',
            url: url,
            dataType: 'json',
            success: function(result){
                var data = hxlProxyToJSON(result);
                console.log(data);
                data.forEach(function(d){
					
					$('#hazard').html( fillRiskCard ( 'HAZARD &amp; EXPOSURE' , [ ['Overall',d['#index+hazard'],lvlHazard],  ['Natural',d['#index+natural'],lvlNatural] , ['Human',d['#index+human'],lvlHuman]], 'haz') ); 

					$('#vulnerability').html( fillRiskCard ( 'VULNERABILITY' , [ ['Overall',d['#index+vulnarability'],lvlVulna],  ['Socio-Economic',d['#index+socioeconomic'],lvlSocEc] , ['Vulnerable Groups',d['#index+vulnarablegroups'],lvlVulGrp]], 'vul') ); 
					
					$('#lack_of_coping').html( fillRiskCard ( 'LACK OF COPING CAPACITY' , [ ['Overall',d['#index+lackcopingcapacity'],lvlCoping],  ['Institutional',d['#index+institutional'],lvlInstit] , ['Infrastructure',d['#index+infrastructure'],lvlInfra]], 'cap') ); 

					$('#INFORM_sum').html( fillRiskCard ( 'SUMMARY' , [ ['Inform Risk',d['#index+informrisk'],lvlRisk],  ['Risk Class',d['#index+class'],lvlClass] ], 'sum') ); 
				
                });

            }
	
    });
}


function fillRiskCard (title, data, csscat) {
	var html = '<h4 class="keyfiguretitle text-center minheight">'+title+'</h4>';
	data.forEach( function (v,i) {
		html += '<h5 class="text-center minheight">'+v[0]+'</h5>';
		html += '<p class="keyfigure text-center INF_'+ csscat 
		if (i>0) { html += '_sub'}
		html += '_level'+determineLevel(v[1], v[2])+'">'+v[1]+'</p>';
	});
	return html;
}

function determineLevel(val, range) {
	var lvl = 1;
 	range.forEach(function(item,index){
		if (isNaN(val)) {
			if (val == item){
				lvl = index+1;
			}
		} else {
			if (val >= item){
				lvl = index+1;
			}
		}
	});		
	return lvl;
}

function generateMap(geom, ISO3) {

	var baselayer = L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
	var baselayer2 = L.tileLayer('https://data.humdata.org/mapbox-layer-tiles/{z}/{x}/{y}.png', {minZoom:4});

	map = L.map('map',{
				center: [0,0],
				zoom: 2,
				layers: [baselayer,baselayer2]
			});

	map.overlay = L.geoJson(geom,{
		onEachFeature:onEachFeature,
		style:style
	}).addTo(map);

	function style(feature) {
		var color = '#aaaaaa';
		var fillOpacity = 0;
		var weight =0
		var cls = 'country'
		if(feature.properties['ISO_A3']==ISO3){
			color = '#D33F49';
			fillOpacity = 0.7;
			weight = 1
		};

		return {
				'color': color,
				'fillcolor': color,
				'weight': weight,
				'opacity': 0.7,
				'fillOpacity':fillOpacity,
				'className':cls
			};
	}
    function onEachFeature(feature, layer){
		if(feature.properties['ISO_A3']==ISO3){
			var bounds = layer.getBounds();
			map.fitBounds(bounds);
		}
	}

}

// Identify for which country / National Society
var hash = decodeURIComponent(window.location.hash).substring(1);
var patt = new RegExp("^[a-zA-Z]{3}$");
if ( patt.test(hash) ) {
	hash = hash.toUpperCase();
} else {
	hash = "KEN";
}

// get the world map
var worldmap = 'http://ifrcgo.org/assets/map/worldmap.json';
$.ajax({
    type: 'GET',
    url: worldmap,
    dataType: 'json',
    success:function(response){
		console.log(response);
		var geom = topojson.feature(response,response.objects.geom);
		generateMap(geom,hash)
    }
});

//Load Governance data
var hxlGovernanceURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1cL39UdUqbyF4llbtTUHes8N9jpjOzgC-rpoq0oIc6jk%2Fedit%23gid%3D0';
hxlGovernanceURL = hxlGovernanceURL.replace('COUNTRYCODE',hash);
console.log(hxlGovernanceURL);
createGovernanceTable(hxlGovernanceURL);

// Load the PNS data
var hxlPNSCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23country%2Bcode%3DCOUNTRYCODE&filter02=sort&sort-tags02=%23project%2Bpartner%2C+%23data%2Bstart&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1SqZRFRsJSRXeyic3QUDWOqrwp5mDsUiOQIfeTRxKVEk%2Fedit%23gid%3D1941804323'
hxlPNSCallURL = hxlPNSCallURL.replace('COUNTRYCODE',hash);
createPNSsTable(hxlPNSCallURL);

// Load the Key Figures with FDRS data
var hxlFDRSCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23date%2Breported%3D2016&filter02=select&select-query02-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&header-row=2&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1uuxSSLYBerjlbvM2Xuye5nONrdHKHyJu8NitjPk93eA%2Fedit%23gid%3D206658392';
hxlFDRSCallURL = hxlFDRSCallURL.replace('COUNTRYCODE',hash);
loadFDRS(hxlFDRSCallURL);

// Get the INFORM index numbers
var hxlINFORMCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1qO4nDJqgRyjxi-Uj5uwSJwFEVf7mloTrtFa9pP3qPwY%2Fedit%23gid%3D646091966';
hxlINFORMCallURL = hxlINFORMCallURL.replace('COUNTRYCODE',hash);
loadINFORMindex(hxlINFORMCallURL);

// Identify URL for appeals and DREFs data
var hxlAppealsCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=merge&merge-url01=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1GugpfyzridvfezFcDsl6dNlpZDqI8TQJw-Jx52obny8%2Fedit%23gid%3D0&merge-keys01=%23country%2Bname&merge-tags01=%23country%2Bcode&filter02=clean&clean-date-format02=%23date&filter03=replace-map&replace-map-url03=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1hTE0U3V8x18homc5KxfA7IIrv1Y9F1oulhJt0Z4z3zo%2Fedit%23gid%3D0&filter04=select&select-query04-01=%23country%2Bcode%3DCOUNTRYCODE&filter05=sort&sort-tags05=%23date%2Bend&sort-reverse05=on&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F19pBx2NpbgcLFeWoJGdCqECT2kw9O9_WmcZ3O41Sj4hU%2Fedit%23gid%3D0&sheet=1';

hxlAppealsCallURL = hxlAppealsCallURL.replace('COUNTRYCODE',hash);

// Get appeals and DREFs data
$.ajax({
    type: 'GET',
    url: hxlAppealsCallURL,
    dataType: 'json',
    success:function(response){
        var data = hxlProxyToJSON(response);
        createAppealsTable(data);
    }
});
