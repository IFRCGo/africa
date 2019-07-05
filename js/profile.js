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

		html += '<tr><td>'+d['name']+'</td><td>' + d['dtype']['name'];
		html += '</td><td>'+getAppealType(d['atype']);
		html += '</td><td>'+d['start_date'].substr(0,10)+'</td><td>'+d['end_date'].substr(0,10);
		html += '</td><td>'+niceFormatNumber(d['num_beneficiaries'],true)+'</td><td>'+niceFormatNumber(d['amount_requested'],true);
		html += '</td><td>'+d['code']+'</td></tr>';
	
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

			// Run through data and prep for tables
			data.forEach(function(d,i){
				// only show governance data when this is available (read: sg field is filled)
				if (d['#org+sg'].length>0) {
					htmlGov += '<tr><th>President</th><td>'+d['#org+president']+'</td></tr>';
					htmlGov += '<tr><th>Last and next election</th><td>'+d['#date+election+last']+' / '+d['#date+election+next']+'</td></tr>';
					htmlGov += '<tr><th>Governing Board members</th><td>'+d['#org+board']+'</td></tr>';
					htmlGov += '<tr><th>Stategic Plan period</th><td>'+d['#org+strategicplan']+'</td></tr>';
					htmlGov += '<tr><th>Secretary General</th><td>'+d['#org+sg']+'</td></tr>';
					htmlGov += '<tr><th>Programme Director</th><td>'+d['#org+director+programmes']+'</td></tr>';
					htmlGov += '<tr><th>Youth Policy</th><td>'+d['#date+policy+youth']+'</td></tr>';
					htmlGov += '<tr><th>Volunteer Policy</th><td>'+d['#date+policy+volunteer']+'</td></tr>';
					htmlGov += '<tr><th>Resource Mob. Policy</th><td>'+d['#date+policy+rm']+'</td></tr>';
					htmlGov += '<tr><th>Child Protection Policy</th><td>'+d['#date+cp+policy']+'</td></tr>';
                                        htmlGov += '<tr><th>Gender Policy</th><td>'+d['#date+gender+policy']+'</td></tr>';
                                        htmlGov += '<tr><th>Gender and Diversity Policy</th><td>'+d['#date+diversity+policy']+'</td></tr>';
                                        htmlGov += '<tr><th>PSEA Policy</th><td>'+d['#date+policy+psea']+'</td></tr>';
					htmlGov += '<tr><th>OCAC / BOCA conducted</th><td>OCAC: '+d['#date+ocac']+' - BOCA: '+d['#date+boca']+'</td></tr>';
					htmlGov += '<tr><th>Consolidated audit</th><td>'+d['#date+audit']+'</td></tr>';
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
					<td>' + (feature.properties['branch'] !== null ? feature.properties['branch'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Staff</th>\
					<td>' + (feature.properties['staff'] !== null ? feature.properties['staff'] : '') + '</td>\
				</tr>\
				<tr>\
					<th scope="row">Volunteers</th>\
					<td>' + (feature.properties['volunteers'] !== null ? feature.properties['volunteers'] : '') + '</td>\
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

	var layer_RedCrossNodes = new L.geoCsv(brNodes, {
		firstLineTitles: true, 
		fieldSeparator: ';',
		onEachFeature: popupNode,
		pointToLayer: function (feature, latlng) {
			var context = {
				feature: feature,
				variables: {}
			};
			return L.circleMarker(latlng, styleNode(feature));
		}
	});
	map.addLayer(layer_RedCrossNodes);


}

function getCountryNumber(ns) {
	var natSocieties = [
		['AGO',18],
		['BEN',209],
		['BWA',34],
		['BFA',181],
		['BDI',39],
		['CMR',41],
		['CPV',43],
		['CAF',44],
		['TCD',45],
		['COM',186],
		['COD',187],
		['COG',184],
		['CIV',182],
		['DJI',57],
		['GNQ',63],
		['ERI',188],
		['SWZ',163],
		['ETH',65],
		['GAB',69],
		['GMB',70],
		['GHA',73],
		['GIN',77],
		['GNB',183],
		['KEN',93],
		['LSO',102],
		['LBR',103],
		['MDG',109],
		['MWI',110],
		['MLI',112],
		['MUS',115],
		['MRT',114],
		['MOZ',120],
		['NAM',122],
		['NER',127],
		['NGA',128],
		['RWA',143],
		['STP',185],
		['SEN',150],
		['SYC',151],
		['SLE',152],
		['SOM',157],
		['ZAF',158],
		['SSD',290],
		['SDN',161],
		['TZA',189],
		['TGO',170],
		['UGA',176],
		['ZMB',12],
		['ZWE',13]
	];
	var countryNo = 0;
	if (ns === undefined) {
		countryNo = 0;
	} else {
		natSocieties.forEach(function(d,i){
			if (ns.indexOf(d[0])>=0) {
				countryNo = d[1];
			}			
		});
	}
	return countryNo; 
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


// Identify for which country / National Society
var hash = decodeURIComponent(window.location.hash).substring(1);
var patt = new RegExp("^[a-zA-Z]{3}$");
if ( patt.test(hash) ) {
	hash = hash.toUpperCase();
} else {
	hash = "KEN";
}

// Update the logo of the NS
$('#nslogo').attr("src","./img/logo/"+hash+"_logo.png");

// get the branch map data
var branchmap = 'https://ifrcgo.org/africa/maps/' + hash + '_map.geojson';
var branchnodes = 'https://ifrcgo.org/africa/maps/' + hash + '_nodes.csv';

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
    dataType: 'text',
	success:function(response){
		booBranchNodes = true;
	}
});

$.when(brMapCall, brNodesCall).always(function(mapArgs, nodesArgs){
	makeMap(mapArgs,nodesArgs[0])
});


//Load Governance data
var hxlGovernanceURL = 'https://proxy.hxlstandard.org/data.json?filter01=merge&merge-url01=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1aYeTU8SaEt8ryxiVEoKqE5jsiLsSnPoDICRoCpwom3A%2Fedit%23gid%3D261283785&merge-keys01=%23country%2Bcode&merge-tags01=%23capacity%2Btotal%2C%23capacity%2Bhq%2C%23capacity%2Bbranch%2C%23capacity%2Bndrt%2C%23capacity%2Brdrt%2C%23capacity%2Bwashkit2%2C%23capacity%2Bwashkit5%2C%23capacity%2Bwashkit10&filter02=select&select-query02-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1cL39UdUqbyF4llbtTUHes8N9jpjOzgC-rpoq0oIc6jk%2Fedit%23gid%3D0';
hxlGovernanceURL = hxlGovernanceURL.replace('COUNTRYCODE',hash);
createGovernanceTable(hxlGovernanceURL);

// Load the PNS data
var hxlPNSCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23meta%2Bcheck%3DY&filter02=sort&sort-tags02=%23date%2Bend&sort-reverse02=on&filter03=select&select-query03-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1pkoD2RJmUoZSuNCXYF49eG3tTdYkHiTrSamQ4LuxgOQ%2Fedit%23gid%3D363150129';
hxlPNSCallURL = hxlPNSCallURL.replace('COUNTRYCODE',hash);
createPNSsTable(hxlPNSCallURL);

// Load the Key Figures with FDRS data
var hxlFDRSCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23date%2Breported%3D2017&filter02=select&select-query02-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&header-row=2&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1uuxSSLYBerjlbvM2Xuye5nONrdHKHyJu8NitjPk93eA%2Fedit%23gid%3D206658392';
hxlFDRSCallURL = hxlFDRSCallURL.replace('COUNTRYCODE',hash);
loadFDRS(hxlFDRSCallURL);

// Get the INFORM index numbers
var hxlINFORMCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1qO4nDJqgRyjxi-Uj5uwSJwFEVf7mloTrtFa9pP3qPwY%2Fedit%23gid%3D646091966';
hxlINFORMCallURL = hxlINFORMCallURL.replace('COUNTRYCODE',hash);
loadINFORMindex(hxlINFORMCallURL);

// Identify URL for appeals and DREFs data
var hxlAppealsCallURL = 'https://prddsgocdnapi.azureedge.net/api/v2/appeal/?country=COUNTRYCODE&format=json&ordering=-end_date&limit=500';
hxlAppealsCallURL = hxlAppealsCallURL.replace('COUNTRYCODE',getCountryNumber(hash));

// Get appeals and DREFs data
$.ajax({
    type: 'GET',
    url: hxlAppealsCallURL,
    dataType: 'json',
    success:function(response){
        createAppealsTable(response.results);
    }
});
