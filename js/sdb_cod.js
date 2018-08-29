"use strict";
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
	if (curDate.getMonth() < 9) {
		todayDate = curDate.getFullYear() + '-0' + (curDate.getMonth() + 1) + '-' + curDate.getDate();
	} else {
		todayDate = curDate.getFullYear() + '-' + (curDate.getMonth() + 1) + '-' + curDate.getDate();
	}

	var yesDate = new Date();
	yesDate.setDate(yesDate.getDate() - 1);
	var yesterdayDate = "";
	if (yesDate.getMonth() < 9) {
		yesterdayDate = yesDate.getFullYear() + '-0' + (yesDate.getMonth() + 1) + '-' + yesDate.getDate();
	} else {
		yesterdayDate = yesDate.getFullYear() + '-' + (yesDate.getMonth() + 1) + '-' + yesDate.getDate();
	}
	
    data.forEach(function(d,i){
		var eventDate = d.activity_date;
console.log(d);
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

function createAlertTable(data) {
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
	if (curDate.getMonth() < 9) {
		todayDate = curDate.getFullYear() + '-0' + (curDate.getMonth() + 1) + '-' + curDate.getDate();
	} else {
		todayDate = curDate.getFullYear() + '-' + (curDate.getMonth() + 1) + '-' + curDate.getDate();
	}

	var yesDate = new Date();
	yesDate.setDate(yesDate.getDate() - 1);
	var yesterdayDate = "";
	if (yesDate.getMonth() < 9) {
		yesterdayDate = yesDate.getFullYear() + '-0' + (yesDate.getMonth() + 1) + '-' + yesDate.getDate();
	} else {
		yesterdayDate = yesDate.getFullYear() + '-' + (yesDate.getMonth() + 1) + '-' + yesDate.getDate();
	}
 
   data.forEach(function(d,i){
		var eventDate = d.time_received.substring(0,10);

	
		// Today's Activities
		if(eventDate === todayDate) {

			todayAlerts += createAlertRow(d,todayAlertNr);

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

			yesterdayAlerts += createAlertRow(d,yesterdayAlertsNr);

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

function createAlertRow(row,nr) {
	var html = "";

	console.log (row);
	if (row.type === 'disinfection') { 
		html += '<tr><td><strong>' + nr + ': Disinfection</strong></td></tr>';
		html += '<tr><td><strong>' + row['group_location/houses_disinfected'] + ' houses to be disinfected</strong> in ';
		html += row['group_location/collection_zone'] + ' - ' + checkField(row['group_location/collection_area']);
		html += ' - ' + checkField(row['group_location/location_name']) + '</td></tr>';
		html += '<tr><td><strong>Planned Activity</strong>: ' + rV(checkField(row['group_response/action_taken']));
		if (checkField(row['group_response/reason_later']) !== '') {
			html += ' (' + row['group_response/reason_later'] + ')';
		}
		if (checkField(row['group_response/reason_not']) !== '') {
			html += ' (' + row['group_response/reason_not'] + ')';
		}
		html += '<tr><td><strong>Comments</strong><br />' + checkField(row.comments) +  '</td></tr>';
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
		html += '<tr><td><hr /></td></tr>';	
	}
	return html;
}

function checkField(field) {
	if (field === undefined) {
		return "";
	} else {
		return field;
	}
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

// Get Alert data
$.ajax({
    type: 'GET',
	url: 'https://kc.humanitarianresponse.info/api/v1/data/264381?format=jsonp',
    dataType: 'jsonp',
	jsonpCallback: "createAlertTable"
});
// Get activity data
$.ajax({
    type: 'GET',
	url: 'https://kc.humanitarianresponse.info/api/v1/data/265029?format=jsonp',
    dataType: 'jsonp',
	jsonpCallback: "createActivityTable"
});

