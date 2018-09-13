"use strict";

function createAlertActMatchTable(alertData, actData) {
	var html = "";
	var matchedAltActHtml = "";

	var curDate = new Date();
	var todayDate = "";
	todayDate = curDate.getFullYear() + '-' + twoNum(curDate.getMonth() + 1) + '-' + twoNum(curDate.getDate());

	var yesDate = new Date();
	yesDate.setDate(yesDate.getDate() - 1);
	var yesterdayDate = "";
	yesterdayDate = yesDate.getFullYear() + '-' + twoNum(yesDate.getMonth() + 1) + '-' + twoNum(yesDate.getDate());
 
 	html += '<tr bgcolor="#cfdff9">';
	html += '<th>' + 'Alert received' + '</th>'; 
	html += '<th>' + 'Time of alert' + '</th>'; 
	html += '<th>' + 'Zone Santé' + '</th>'; 
	html += '<th>' + 'Aire de Santé' + '</th>'; 
	html += '<th>' + 'Localité' + '</th>'; 	
	html += '<th>' + 'Site de Collection' + '</th>'; 
	html += '<th>' + 'Nom' + '</th>'; 
	html += '<th>' + 'Résidence' + '</th>'; 
	html += '<th>' + 'Résultat' + '</th>'; 
	html += '<th>' + 'Status' + '</th>'; 
	html += '<th>' + 'Début de la reponse' + '</th>'; 	
	html += '<th>' + 'Heure de la reponse' + '</th>'; 
	html += '<th>' + 'Prélevement post-mortem?' + '</th>'; 
	html += '<th>' + 'Desinfection du lieu' + '</th>'; 
	html += '<th>' + 'Sexe du défunct' + '</th>'; 
	html += '<th>' + 'Sexe calcul' + '</th>'; 
	html += '<th>' + 'Age du défunct (ans)' + '</th>'; 
	html += '<th>' + 'Age du défunct (mois)' + '</th>'; 
	html += '<th>' + 'Groupe d\'âge' + '</th>'; 
	html += '<th>' + 'Fin de reponse' + '</th>'; 
	html += '<th>' + 'Commentaire' + '</th>'; 
	html += '<th>' + 'Raison' + '</th>'; 
	html += '<th>' + 'Fiche' + '</th>'; 
	html += '<th>' + 'RegAlert' + '</th>'; 
	html += '<th>' + 'RegAct' + '</th>'; 
	html += '<th>' + 'Confirmed case YN' + '</th>'; 
	html += '</tr>'

	$('#tableAltActMatches').append(html);

	alertData.forEach(function(d,i){
		var eventDate = d.time_received.substring(0,10);

		// Today & Yesterday's Activities
		if ((eventDate === todayDate) || (eventDate === yesterdayDate)) {
			matchedAltActHtml = createAltActRow(d,actData);
		}

		$('#tableAltActMatches').append(matchedAltActHtml);

	})

}

function createActivityTable(data) {

	var todayActs = "";
	var todayActNr = 1;
	var yesterdayActs = "";
	var yesterdayActNr = 1;
	
	var statusSuccessDay = 0;
	var statusUnsuccesDay = 0;
	var statusPendingDay = 0;
	var noDisinfectionDay = 0;
	var statusSuccessYes = 0;
	var statusUnsuccesYes = 0;
	var statusPendingYes = 0;
	var noDisinfectionYes = 0;

	var curDate = new Date();
	var todayDate = "";
	todayDate = curDate.getFullYear() + '-' + twoNum(curDate.getMonth() + 1) + '-' + twoNum(curDate.getDate());

	var yesDate = new Date();
	yesDate.setDate(yesDate.getDate() - 1);
	var yesterdayDate = "";
	yesterdayDate = yesDate.getFullYear() + '-' + twoNum(yesDate.getMonth() + 1) + '-' + twoNum(yesDate.getDate());
	
    data.forEach(function(d,i){
		var eventDate = d.activity_date;

		// Today's Activities
		if(eventDate === todayDate) {

			todayActs += createActivityRow(d,todayActNr);
			
			todayActNr++;
			
			if (d['burial/status'] === 'successful' ) {
				statusSuccessDay++;
			} else if (d['burial/status'] === 'unsuccessful' ) {
				statusUnsuccesDay++;
			} else if (d['burial/status'] === 'pending' ) {
				statusPendingDay++;
			} else if (d.type === 'disinfection') {
				noDisinfectionDay += Number(d['disinfection/houses_disinfected']);
			}

		//Yesterday's Activities
		} else if(eventDate === yesterdayDate) {

			yesterdayActs += createActivityRow(d,yesterdayActNr);

			yesterdayActNr++;

			if (d['burial/status'] === 'successful' ) {
				statusSuccessYes++;
			} else if (d['burial/status'] === 'unsuccessful' ) {
				statusUnsuccesYes++;
			} else if (d['burial/status'] === 'pending' ) {
				statusPendingYes++;
			} else if (d.type === 'disinfection') {
				noDisinfectionYes += Number(d['disinfection/houses_disinfected']);
			}
		}
	   
    });
	// Send data to html tables
	$('#statsActDay').append(createActSum(statusSuccessDay,statusUnsuccesDay,statusPendingDay,noDisinfectionDay));
	$('#statsActYes').append(createActSum(statusSuccessYes,statusUnsuccesYes ,statusPendingYes,noDisinfectionYes));
	$('#tableActDay').append(todayActs);
	$('#tableActYes').append(yesterdayActs);
}

function createActSum(ok, nok, pnd, dis) {
	var html;
	html = 'SDB Successful : ' + ok;
	html += '<br />SDB Pending : ' + pnd;
	html += '<br />SDB Unsuccessful : ' + nok;
	html += '<br /><br />Houses disinfected : ' + dis;
	return html;
}

function createActivityRow(row,nr) {
	var html = "";

	if (row.type === 'disinfection') {
		
		html += '<tr><td><strong>' + nr + ': Disinfection</strong></td></tr>';
		html += '<tr><td><strong>' + row['disinfection/houses_disinfected'] + ' houses disinfected</strong> in ' + row['disinfection/disinfection_zone'] + ' - ' + checkField(row['disinfection/disinfection_area']) + '</td></tr>';
		html += '<tr><td><strong>Comments</strong><br />' + checkField(row.comments) +  '</td></tr>';
		html += '<tr><td><strong><hr /></td></tr>';
		
	} else {
	
		html += '<tr><td><strong>' + nr + ': ' + checkField(row['burial/status']) + '</strong>';
		if (checkField(row['burial/why_not_success']) !== '') {
			html += ' - ' + row['burial/why_not_success'];
		}
		html += '</td></tr>';
		html += '<tr><td><strong>' + rV(checkField(row['burial/burial_activity'])) + '</strong></td></tr>';
		html += '<tr><td><strong>' + rV(checkField(row['burial/collection_site'])) + '</strong>: ';
		html += row['burial/collection_zone'] + ' - ' + checkField(row['burial/collection_area']) ;
		html += ' - ' + checkField(row['burial/collection_place']) + '</td></tr>';
		html += '<tr><td><strong>Person</strong>: ' + checkField(row['burial/gender']) + ' - ' + checkField(row['burial/age']) + 'yrs</td></tr>';
		html += '<tr><td><strong>Activities</strong>: Swap: ' + rV(checkField(row['burial/swap_taken'])) ;
		html += ' - Disinfection: ' + rV(checkField(row['burial/disinfected'])) + '</td></tr>';
		html += '<tr><td><strong>Burial</strong>: ' + checkField(row['burial/burial_zone']) + ' - ' + checkField(row['burial/burial_area']) + ' - ' + checkField(row['burial/burial_place']) + '</td></tr>';
		html += '<tr><td><strong>Comments</strong>: ' + checkField(row.comments) +  '</td></tr>';
		html += '<tr><td><strong><hr /></td></tr>';

	}

	return html;
}

function getMatchedActRow(row) {
	var html = "";

	if (row.type === 'disinfection') {
		
		html += '<strong> Disinfection</strong><br/>';
		html += '<strong>' + row['disinfection/houses_disinfected'] + ' houses disinfected</strong> in ' + row['disinfection/disinfection_zone'] + ' - ' + checkField(row['disinfection/disinfection_area']) + '<br/>';
		html += '<strong>Comments</strong><br />' + checkField(row.comments);
		
	} else {
	
		html += '<strong>' + checkField(row['burial/status']) + '</strong>';
		if (checkField(row['burial/why_not_success']) !== '') {
			html += ' - ' + row['burial/why_not_success'];
		}
		html += '<br/>';
		html += '<strong>' + rV(checkField(row['burial/burial_activity'])) + '</strong><br/>';
		html += '<strong>' + rV(checkField(row['burial/collection_site'])) + '</strong>: ';
		html += row['burial/collection_zone'] + ' - ' + checkField(row['burial/collection_area']) ;
		html += ' - ' + checkField(row['burial/collection_place']) + '<br/>';
		html += '<strong>Person</strong>: ' + checkField(row['burial/gender']) + ' - ' + checkField(row['burial/age']) + 'yrs<br/>';
		html += '<strong>Activities</strong>: Swap: ' + rV(checkField(row['burial/swap_taken'])) ;
		html += ' - Disinfection: ' + rV(checkField(row['burial/disinfected'])) + '<br/';
		html += '<strong>Burial</strong>: ' + checkField(row['burial/burial_zone']) + ' - ' + checkField(row['burial/burial_area']) + ' - ' + checkField(row['burial/burial_place']) + '<br/>';
		html += '<strong>Comments</strong>: ' + checkField(row.comments) +  '<br/>';

	}

	return html;

}


function matchActToAlert(altRow, actData) {
	var matchData = [];
	var alertDate = altRow['time_received'].substring(0,10);  //'time_received' - date/time alert received
	var alertDateMs = Date.parse(alertDate);

	actData.forEach(function(d,i){
		var actDateMs = Date.parse(d['activity_date'])
		if (alertDateMs <= actDateMs) {  //alert date <= activity date (i.e. burial date)
			if ((altRow['group_location/collection_site']===d['burial/collection_site']) && 
				(altRow['group_location/collection_zone']===d['burial/collection_zone']) &&
				(altRow['group_location/collection_area']===d['burial/collection_area'])){
					if ((altRow['group_deceased/gender_of_deceased']===d['burial/gender']) &&
						(altRow['group_deceased/age_of_deceased']===d['burial/age'])) {
							//console.log('matched: ', altRow, d);
							matchData.push(d);
					}
					
			}

		}
		
	});

	return matchData;
}

function createAlertTable(alertData, actData) {
	var todayAlerts = "";
	var todayAlertNr = 1;
	var yesterdayAlerts = "";
	var yesterdayAlertsNr = 1;
	
	var typeEtcDay = 0;
	var typeHopDay = 0;
	var typeComDay = 0;
	var typeMrgDay = 0;
	var typeDisDay = 0;
	var typeEtcYes = 0;
	var typeHopYes = 0;
	var typeComYes = 0;
	var typeMrgYes = 0;
	var typeDisYes = 0;

	var curDate = new Date();
	var todayDate = "";
	todayDate = curDate.getFullYear() + '-' + twoNum(curDate.getMonth() + 1) + '-' + twoNum(curDate.getDate());

	var yesDate = new Date();
	yesDate.setDate(yesDate.getDate() - 1);
	var yesterdayDate = "";
	yesterdayDate = yesDate.getFullYear() + '-' + twoNum(yesDate.getMonth() + 1) + '-' + twoNum(yesDate.getDate());
 
    alertData.forEach(function(d,i){
		var eventDate = d.time_received.substring(0,10);

		// Today's Activities
		if(eventDate === todayDate) {

			todayAlerts += createAlertRow(d,todayAlertNr,actData);

			todayAlertNr++;

			if (d['group_location/collection_site'] === 'etc' ) {
				typeEtcDay++;
			} else if (d['group_location/collection_site'] === 'hospital' ) {
				typeHopDay++;
			} else if (d['group_location/collection_site'] === 'community' ) {
				typeComDay++;
			} else if (d['group_location/collection_site'] === 'morgue' ) {
				typeMrgDay++;
			} else if (d.type === 'disinfection') {
				typeDisDay += Number(d['group_location/houses_disinfected']); 
			}

		} else if(eventDate === yesterdayDate) {

			yesterdayAlerts += createAlertRow(d,yesterdayAlertsNr,actData);

			yesterdayAlertsNr++;

			if (d['group_location/collection_site'] === 'etc' ) {
				typeEtcYes++;
			} else if (d['group_location/collection_site'] === 'hospital' ) {
				typeHopYes++;
			} else if (d['group_location/collection_site'] === 'community' ) {
				typeComYes++;
			} else if (d['group_location/collection_site'] === 'morgue' ) {
				typeMrgYes++;
			} else if (d.type === 'disinfection') {
				typeDisYes += Number(d['group_location/houses_disinfected']);
			}
		}
   } );
	// Send data to html tables
	$('#statsAltDay').append(createAlertSum(typeEtcDay,typeHopDay,typeComDay,typeMrgDay,typeDisDay));
	$('#statsAltYes').append(createAlertSum(typeEtcYes,typeHopYes,typeComYes,typeMrgYes,typeDisYes));
	$('#tableAltDay').append(todayAlerts);
	$('#tableAltYes').append(yesterdayAlerts);
}

function createAlertSum(etc, hos, com, mor, dis) {
	var html;
	html = 'SDB ETC : ' + etc;
	html += '<br />SDB Hospital : ' + hos;
	html += '<br />SDB Morgue : ' + mor;
	html += '<br />SDB Community : ' + com;
	html += '<br /><br />Disinfections : ' + dis;
	return html;
}

function createAlertRow(row,nr, actData) {
	//console.log('createAlertRow: ', row, nr)
	var html = "";

	var actMatches = matchActToAlert(row, actData);
	//console.log(actMatches);

	if (row.type === 'disinfection') { 
		html += '<tr><td><strong>' + nr + ': Disinfection</strong></td></tr>';
		html += '<tr><td><strong>' + row['group_location/houses_disinfected'] + ' houses to be disinfected</strong> in ';
		html += row['group_location/collection_zone'] + ' - ' + checkField(row['group_location/collection_area']);
		html += ' - ' + checkField(row['group_location/location_village']) + '</td></tr>';
		html += '<tr><td><strong>Planned Activity</strong>: ' + rV(checkField(row['group_response/action_taken']));
		if (checkField(row['group_response/reason_later']) !== '') {
			html += ' (' + row['group_response/reason_later'] + ')';
		}
		if (checkField(row['group_response/reason_not']) !== '') {
			html += ' (' + row['group_response/reason_not'] + ')';
		}
		html += '<tr><td><strong>Comments</strong><br />' + checkField(row.comments) +  '</td></tr>';
		if (actMatches.length==0) {
			html += '<tr><td><strong>Activity matches found</strong>: <i>None</i></td></tr>';
		} else {
			html += '<tr><td><strong>Activity matches found</strong>: </td></tr>';
			html += '<table><tr><td>TEXT 1</td></tr>'
		}
		html += '<tr><td><strong><hr /></td></tr>';
	} else  {
		html += '<tr><td><strong>' + nr + ': ' + rV(checkField(row['group_location/collection_site'])) + '</strong><br />';
		html += checkField(row['group_location/collection_zone']) + ' - ' + checkField(row['group_location/collection_area']) ;
		html += ' - ' + checkField(row['group_location/location_village']) + '</td></tr>';
		html += '<tr><td><strong>Person</strong>: ' + rV(checkField(row['group_deceased/gender_of_deceased'])) ;
		html += ' - ' + rV(checkField(row['group_deceased/age_of_deceased'])) + 'yrs</td></tr>';
		html += '<tr><td><strong>Planned Activity</strong>: ' + rV(checkField(row['group_response/action_taken']));
		if (checkField(row['group_response/reason_later']) !== '') {
			html += ' (' + row['group_response/reason_later'] + ')';
		}
		if (checkField(row['group_response/reason_not']) !== '') {
			html += ' (' + row['group_response/reason_not'] + ')';
		}
		html += '</td></tr>';
		html += '<tr><td><strong>Comments</strong>: ' + checkField(row.comments) +  '</td></tr>';
		if (actMatches.length==0) {
			html += '<tr><td><strong>Activity matches found</strong>: <i>None</i></td></tr>';
		} else {
			html += '<tr><td><strong>Activity matches found</strong>: ' + actMatches.length + '</td></tr>';			
			actMatches.forEach(function(d,i) {
				html += '<tr bgcolor="#7dc0e0"><td style="padding:10px 30px"><small><big><i>Activity Match ' + (i+1) + '</i></big>: ';
				html += getMatchedActRow(d);
				html += '</small></td></tr>';

			})
		}
		html += '<tr><td><hr /></td></tr>';	
	}

	return html;
}

function createAltActRow(altRow,actData) {
	var html = "";

	var actMatches = matchActToAlert(altRow, actData);
	console.log(altRow, actMatches);

	html += '<tr>';
	html += '<td>' + altRow['time_received'].substring(0,10) + '</td>'; //Alert received
	html += '<td>' + '' + '</td>'; //Time of alert
	html += '<td>' + altRow['group_location/collection_zone'] + '</td>'; //Zone Santé	
	html += '<td>' + altRow['group_location/collection_area']  + '</td>'; //Aire de Santé	
	html += '<td>' + altRow['group_location/location_village']  + '</td>'; //Localité	
	html += '<td>' + altRow['group_location/collection_site'] + '</td>'; //Site de Collection	
	html += '<td>' + '' + '</td>'; //Nom	
	html += '<td>' + '' + '</td>'; //Résidence	
	html += '<td>' + altRow['group_response/action_taken'] + '</td>'; //Résultat

	

	if (actMatches.length == 0) {
		html += '<td>' + '<i>No activity found</i>' + '</td>'; //Status	
	} else {
		html += '<td>' + actMatches[0]['burial/status'] + '</td>'; //Status	
		html += '<td>' + '' + '</td>'; //Début de la reponse	
		html += '<td>' + '' + '</td>'; //Heure de la reponse	
		html += '<td>' + '' + '</td>'; //Prélevement post-mortem?	
		html += '<td>' + '' + '</td>'; //Desinfection du lieu	
		html += '<td>' + '' + '</td>'; //Sexe du défunct	
		html += '<td>' + '' + '</td>'; //Sexe calcul	
		html += '<td>' + '' + '</td>'; //Age du défunct (ans)	
		html += '<td>' + '' + '</td>'; //Age du défunct (mois)	
		html += '<td>' + '' + '</td>'; //Groupe d'âge	
		html += '<td>' + '' + '</td>'; //Fin de reponse	
		html += '<td>' + '' + '</td>'; //Commentaire	
		html += '<td>' + '' + '</td>'; //Raison	
		html += '<td>' + '' + '</td>'; //Fiche	
		html += '<td>' + '' + '</td>'; //RegAlert	
		html += '<td>' + '' + '</td>'; //RegAct	
		html += '<td>' + '' + '</td>'; //Confirmed case YN
	}

	html += '</tr>';

	return html;
}


function checkField(field) {
	if (field === undefined) {
		return "";
	} else {
		return field;
	}
}

function twoNum (v) {
	var newVal = '';
	if (v<10) {
		newVal = '0' + v.toString();
	} else {
		newVal = '' + v.toString();
	}
	return newVal;
}

function rV(v) {
	var newVal = '';
	switch(v) {
    case 'no':
        newVal = '<span style=\'color=red;font-weight: bold;\'>&#10008;</span>';
        break;
    case 'yes':
        newVal = '<span style=\'color=green;font-weight: bold;\'>&#10004;</span>';
        break;
	case 'responded':
		newVal = 'Responding today';
		break;
	case 'planned':
		newVal = 'Planned to respond tomorrow';
		break;
	case 'not_responded':
		newVal = 'No plans to respond';
		break;
	case 'etc':
		newVal = 'Ebola Treatment Centre (ETC)';
		break;
	case 'new':
		newVal = 'Alert received today';
		break;
	case 'continue':
		newVal = 'SDB started yesterday, continued today';
		break;
	case 'yesterday':
		newVal = 'Alert received yesterday, SDB started today';
		break;
    default:
		newVal = v;
	}
	return newVal;
}


// Get Alert & Activity data - simultaneous AJAX requests
$(document).ready(function () {
    var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/264381?format=jsonp',
    	dataType: 'jsonp',
    });

    var d2 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/265029?format=jsonp',
    	dataType: 'jsonp',
    });

    $.when(d1, d2).then(function (a1, a2) {
        console.log('Ajax calls succeedeed');
        createAlertActMatchTable(a1[0], a2[0]);
        createAlertTable(a1[0], a2[0]);
        createActivityTable(a2[0]);
    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        var x2 = d2;
        if (x1.readyState != 4) {
            x1.abort();
        }
        if (x2.readyState != 4) {
            x2.abort();
        }
        alert("Data request failed");
        console.log('Ajax request failed');
    });
});

