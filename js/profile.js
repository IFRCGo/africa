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

// Determine PacScoreCard value: Good, Medium, Bad
function scorePac(val, check, correction, grace) {
	var score = 'Bad';
// year year-year  year/year  no  yes  ongoing

	if (val == 'ongoing') {
		score = 'Medium';
	}

	if (check == 'yn') {
		if (val == 'yes') {
			score = 'Good';
		}
	}

	if (check == 'period') {
		var patt = /-/i;
		if (patt.test(val)) {
			val = val.substr(val.indexOf('-')+1);
			if (val.length == 2) {
				val = concat('20',val);
			}
			check = 'year';
		}
	}

	if (check == 'year') {
		if (!isNaN(val)) {
			if ((new Date()).getFullYear()+correction <= val) {
				score = 'Good';
			} else if ((new Date()).getFullYear()+grace <= val) {
				score = 'Medium';
			}
		}
	}
	return score;
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
    var htmlGov = "";
	var htmlPac = "";
	var hasWASH = false;

	$.ajax({
		type: 'GET',
		url: url,
		dataType: 'json',
		success: function(result){
			var data = hxlProxyToJSON(result);
			console.log(data);

			// Run through data and prep for tables
			data.forEach(function(d,i){
				// only show governance data when this is available (read: sg field is filled)
				if (d['#org+sg'].length>0) {
					htmlGov += '<tr><th>President</th><td>'+d['#org+president']+'</td></tr>';
					htmlGov += '<tr><th>Last and next election</th><td>'+d['#date+election+last']+' / '+d['#date+election+next']+'</td></tr>';
					htmlGov += '<tr><th>No. of Governing Board members</th><td>'+d['#org+board']+'</td></tr>';
					htmlGov += '<tr><th>Stategic Plan period</th><td>'+d['#org+strategicplan']+'</td></tr>';
					htmlGov += '<tr><th>Secretary General</th><td>'+d['#org+sg']+'</td></tr>';
					htmlGov += '<tr><th>Programme Director</th><td>'+d['#org+director+programmes']+'</td></tr>';
					htmlGov += '<tr><th>Latest Youth Policy</th><td>'+d['#date+policy+youth']+'</td></tr>';
					htmlGov += '<tr><th>Latest Volunteer Policy</th><td>'+d['#date+policy+volunteer']+'</td></tr>';
					htmlGov += '<tr><th>Latest Resource Mobilisation Policy</th><td>'+d['#date+policy+rm']+'</td></tr>';
					htmlGov += '<tr><th>Date OCAC / BOCA conducted</th><td>OCAC: '+d['#date+ocac']+' - BOCA: '+d['#date+boca']+'</td></tr>';
					htmlGov += '<tr><th>Last consolidated audit</th><td>'+d['#date+audit']+'</td></tr>';
				}

				htmlPac += '<tr>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind1'],'yn',0)+'">Receiving government financial / in-kind support</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind2'],'yn',0)+'">&lt;50% domestically generated income </td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind3'],'yn',0)+'">Audited and produce fin statements annually</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind4'],'yn',0)+'">Self-assessment or peer review process</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind5'],'yn',0)+'">Reporting annually to FDRS</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind6'],'yn',0)+'">Youth policy / programme and implementation YABC</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind7'],'yn',0)+'">Updated Act / statutes in last 5 years</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac9+ind1'],'yn',0)+'">Risk management framework</td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac9+ind3'],'yn',0)+'">Complying with CMC dashboard</td>';
				htmlPac += '</tr>';
				htmlPac += '<tr>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind1'],'yn',0)+'"><strong>'+d['#pac8+ind1'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind2'],'yn',0)+'"><strong>'+d['#pac8+ind2'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind3'],'yn',0)+'"><strong>'+d['#pac8+ind3'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind4'],'yn',0)+'"><strong>'+d['#pac8+ind4'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind5'],'yn',0)+'"><strong>'+d['#pac8+ind5'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind6'],'yn',0)+'"><strong>'+d['#pac8+ind6'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac8+ind7'],'yn',0)+'"><strong>'+d['#pac8+ind7'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac9+ind1'],'yn',0)+'"><strong>'+d['#pac9+ind1'].toUpperCase()+'</strong></td>';
				htmlPac += '<td class="pacScore'+scorePac(d['#pac9+ind3'],'yn',0)+'"><strong>'+d['#pac9+ind3'].toUpperCase()+'</strong></td>';
				htmlPac += '</tr>';

				// only show WASH data when this is available (read: NoTotalStaff is filled)
				if (d['#capacity+total'].length>0) {
					$('#NoWashStaff').html( fillKeyFigureCard('Total WASH Staff', d['#capacity+total']) );
					$('#NoWashKit2').html( fillKeyFigureCard('WASH Kit2', d['#capacity+washkit2']) );
					$('#NoWashKit5').html( fillKeyFigureCard('WASH Kit5', d['#capacity+washkit5']) );
					$('#NoWashKit10').html( fillKeyFigureCard('WASH Kit10', d['#capacity+washkit10']) );
					$('#NoWashHQ').html( fillKeyFigureCard('WASH Staff at HQ', d['#capacity+hq']) );
					$('#NoWashBranch').html( fillKeyFigureCard('WASH Staff at Branch', d['#capacity+branch']) );
					$('#NoWashNDRT').html( fillKeyFigureCard('NDRT Trained', d['#capacity+ndrt']) );
					$('#NoWashRDRT').html( fillKeyFigureCard('RDRT Trained', d['#capacity+rdrt']) );
				} else {
					$('#NoWashStaff').html( fillKeyFigureCard('', 'No data' ) );
				}
			});
					// Send data to appeals or DREFs html tables
			$('#NSgovernanceTable').append(htmlGov);
			$('#PacScorecardTable').append(htmlPac);
			if (htmlGov!="") {
				$('#Overview').css("height","360px");
				$('#Overview').css("visibility","visible");
			}
//			if (hash == 'COG') {
				$('#PacIndicators').css("height","187px");
				$('#PacIndicators').css("visibility","visible");
//			}
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

      var dayNow = new Date();
      var dayEnd = new Date();
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      var pnsList = new Array();
      var sectorList = new Array();

		// Run through data and prep for tables
			data.forEach(function(d,i){
        pnsList.push(d['#org+partner']);
        sectorList.push(d['#activity+sector']);

        if (isNaN(d['#date+end'].substr(0,1))) {
          dayEnd.setFullYear(d['#date+end'].substr(4,4));
          dayEnd.setMonth(months.indexOf(d['#date+end'].substr(0,3)));
        }
        if (dayNow > dayEnd) {
				    html += '<tr class="PastProject"><td>'
        } else {
            html += '<tr class="ActiveProject"><td>'
        }

				html += d['#org+partner']+'</td><td>';
        html += d['#activity+name']+'<br /><small>'+d['#activity+description']+'</small></td><td>';
        if (d['#activity+alt+sector'].length > 0) {
          // also add the secondary sector to the list of sectors.
          sectorList.push(d['#activity+alt+sector']);
          html += d['#activity+sector']+'<br /><small>and</small><br />'+d['#activity+alt+sector']+'</td><td>';
        } else {
          html += d['#activity+sector']+'</td><td>';
        }
        html += d['#activity+budget']+'</td><td>'+d['#meta+funding']+'</td><td>';
        html += d['#date+start']+'</td><td>'+d['#date+end']+'</td></tr>';
			});

			// Send data to appeals or DREFs html tables
			$('#pnstable').append(html);


      fillPnsOverview(pnsList, '#pnsoverviewtable');
      fillPnsOverview(sectorList, '#sectoroverviewtable');

		}
	})
}

function fillPnsOverview (arr, htmlId) {
  html = '';
  prevValue = '';
  counter = 0;
  arr.sort();
  arr.forEach(function(value) {
      if (prevValue!=value & counter>0) {
        html += '<tr><td>'+prevValue+'</td><td>'+counter+'</td></tr>';
        counter = 0;
      }
      counter++;
      prevValue = value;
  });
  if (counter>0) {
    html += '<tr><td>'+prevValue+'</td><td>'+counter+'</td></tr>';
  }
  $(htmlId).append(html);
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
	html += '<p class="keyfigure text-center">'+ niceFormatNumber(value,false) +'</p>';
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

function generateBranchMap(brMap, brNodes) {
	var baselayer = L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
	var baselayer2 = L.tileLayer('https://data.humdata.org/mapbox-layer-tiles/{z}/{x}/{y}.png', {minZoom:4});
	var bounds;

	map = L.map('map',{
				center: [0,0],
				zoom: 2,
				layers: [baselayer,baselayer2]
			});

	// Add branch areas
	var layer_RedCrossBranches = new L.geoJson(brMap,{
		style:styleMap
	})
	bounds = layer_RedCrossBranches.getBounds();
	map.addLayer(layer_RedCrossBranches);

	var highlightLayer;
	function highlightFeature(e) {
		highlightLayer = e.target;

		if (e.target.feature.geometry.type === 'LineString') {
		  highlightLayer.setStyle({
			color: 'LIGHTGREY',
		  });
		} else {
		  highlightLayer.setStyle({
			fillColor: 'RED',
			fillOpacity: 1
		  });
		}
	}

	function styleMap() {
		return {
			opacity: 1,
			color: 'rgba(0,0,0,1.0)',
			dashArray: '',
			lineCap: 'butt',
			lineJoin: 'miter',
			weight: 1.0,
			fill: true,
			fillOpacity: 1,
			fillColor: 'LIGHTGREY',
		}
	}
	function styleNode() {
		return {
			radius: 4.0,
			opacity: 1,
			color: 'rgba(0,0,0,1.0)',
			dashArray: '',
			lineCap: 'butt',
			lineJoin: 'miter',
			weight: 1,
			fill: true,
			fillOpacity: 1,
			fillColor: 'RED',
		};
	}
	function popupNode(feature, layer) {
		var popupContent = '<table>\
				<tr>\
					<th scope="row">Branch</th>\
					<td>' + (feature.properties['Branch'] !== null ? feature.properties['Branch'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Address</th>\
					<td>' + (feature.properties['Address'] !== null ? feature.properties['Address'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Staff</th>\
					<td>' + (feature.properties['Staff'] !== null ? feature.properties['Staff'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Volunteers</th>\
					<td>' + (feature.properties['Volunteers'] !== null ? feature.properties['Volunteers'] : '') + '</td>\
				</tr>\
			</table>';
		layer.bindPopup(popupContent, {maxHeight: 400, minWidth: 250, maxWidth: 500});

		layer.on({
			mouseout: function(e) {
				for (i in e.target._eventParents) {
					e.target._eventParents[i].resetStyle(e.target);
				}
				this.closePopup();
			},
			mouseover: function(e) {
				highlightFeature;
				this.openPopup();
			},

		});
	}

	var layer_RedCrossNodes = new L.geoJson(brNodes, {
		onEachFeature: popupNode,
		pointToLayer: function (feature, latlng) {
			var context = {
				feature: feature,
				variables: {}
			};
			return L.circleMarker(latlng, styleNode(feature));
		},
	});
	map.addLayer(layer_RedCrossNodes);

	map.fitBounds(bounds);

}
function makeMap(brMap, brNodes) {
	var baselayer = L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
	var baselayer2 = L.tileLayer('https://data.humdata.org/mapbox-layer-tiles/{z}/{x}/{y}.png', {minZoom:4});
	var bounds;

	map = L.map('map',{
				center: [0,0],
				zoom: 2,
				layers: [baselayer,baselayer2]
			});

	function styleMap() {
		return {
			opacity: 1,
			color: 'rgba(0,0,0,1.0)',
			dashArray: '',
			lineCap: 'butt',
			lineJoin: 'miter',
			weight: 1.0,
			fill: true,
			fillOpacity: 0.7,
			fillColor: '#D33F49',
		}
	}

	var layer_RedCrossBranches = new L.geoJson(brMap,{
		style:styleMap
	})
	bounds = layer_RedCrossBranches.getBounds();
	map.addLayer(layer_RedCrossBranches);
	map.fitBounds(bounds);

	var highlightLayer;
	function highlightFeature(e) {
		highlightLayer = e.target;

		if (e.target.feature.geometry.type === 'LineString') {
		  highlightLayer.setStyle({
			color: 'LIGHTGREY',
		  });
		} else {
		  highlightLayer.setStyle({
			fillColor: 'RED',
			fillOpacity: 1
		  });
		}
	}

	function styleNode() {
		return {
			radius: 4.0,
			opacity: 1,
			color: 'rgba(0,0,0,1.0)',
			dashArray: '',
			lineCap: 'butt',
			lineJoin: 'miter',
			weight: 1,
			fill: true,
			fillOpacity: 1,
			fillColor: 'RED',
		};
	}
	function popupNode(feature, layer) {
		var popupContent = '<table>\
				<tr>\
					<th scope="row">Branch</th>\
					<td>' + (feature.properties['Branch'] !== null ? feature.properties['Branch'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Address</th>\
					<td>' + (feature.properties['Address'] !== null ? feature.properties['Address'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Staff</th>\
					<td>' + (feature.properties['Staff'] !== null ? feature.properties['Staff'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Volunteers</th>\
					<td>' + (feature.properties['Volunteers'] !== null ? feature.properties['Volunteers'] : '') + '</td>\
				</tr>\
			</table>';
		layer.bindPopup(popupContent, {maxHeight: 400, minWidth: 250, maxWidth: 500});

		layer.on({
			mouseout: function(e) {
				for (i in e.target._eventParents) {
					e.target._eventParents[i].resetStyle(e.target);
				}
				this.closePopup();
			},
			mouseover: function(e) {
				highlightFeature;
				this.openPopup();
			},

		});
	}

	var layer_RedCrossNodes = new L.geoJson(brNodes, {
		onEachFeature: popupNode,
		pointToLayer: function (feature, latlng) {
			var context = {
				feature: feature,
				variables: {}
			};
			return L.circleMarker(latlng, styleNode(feature));
		},
	});
	map.addLayer(layer_RedCrossNodes);


}

// Identify for which country / National Society
var hash = decodeURIComponent(window.location.hash).substring(1);
var patt = new RegExp("^[a-zA-Z]{3}$");
if ( patt.test(hash) ) {
	hash = hash.toUpperCase();
} else {
	hash = "KEN";
}


// get the branch map data
var branchmap = 'https://ifrcgo.org/africa/maps/' + hash + '_map.geojson';
var branchnodes = 'https://ifrcgo.org/africa/maps/' + hash + '_nodes.geojson';

var brMapCall = $.ajax({
    type: 'GET',
    url: branchmap,
    dataType: 'json',
	success:function(response){
		booBranchMap = true;
	}
});

var brNodesCall = $.ajax({
    type: 'GET',
    url: branchnodes,
    dataType: 'json',
	success:function(response){
		booBranchNodes = true;
	}
});

$.when(brMapCall, brNodesCall).always(function(mapArgs, nodesArgs){
	makeMap(mapArgs,nodesArgs)
});


//Load Governance data
var hxlGovernanceURL = 'https://proxy.hxlstandard.org/data.json?filter01=merge&merge-url01=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1aYeTU8SaEt8ryxiVEoKqE5jsiLsSnPoDICRoCpwom3A%2Fedit%23gid%3D261283785&merge-keys01=%23country%2Bcode&merge-tags01=%23capacity%2Btotal%2C%23capacity%2Bhq%2C%23capacity%2Bbranch%2C%23capacity%2Bndrt%2C%23capacity%2Brdrt%2C%23capacity%2Bwashkit2%2C%23capacity%2Bwashkit5%2C%23capacity%2Bwashkit10&filter02=select&select-query02-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1cL39UdUqbyF4llbtTUHes8N9jpjOzgC-rpoq0oIc6jk%2Fedit%23gid%3D0';
hxlGovernanceURL = hxlGovernanceURL.replace('COUNTRYCODE',hash);
console.log(hxlGovernanceURL);
createGovernanceTable(hxlGovernanceURL);

// Load the PNS data
var hxlPNSCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23meta%2Bcheck%3DY&filter02=sort&sort-tags02=%23date%2Bend&sort-reverse02=on&filter03=select&select-query03-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1pkoD2RJmUoZSuNCXYF49eG3tTdYkHiTrSamQ4LuxgOQ%2Fedit%23gid%3D363150129';
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
