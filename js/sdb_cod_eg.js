"use strict";


var mainHeadings = [
	{
		'fieldname': 'start',
	 	'title': 'Alert Start'
	 },{
		'fieldname': 'end',
		'title': 'Alert End'
	},{
		'fieldname': 'newalert',
		'title': 'Alert Details'
	},{
		'fieldname': 'response',
		'title': 'Response'
	},{
		'fieldname': 'deceased',
		'title': 'Deceased'
	},{
		'fieldname': 'location',
		'title': 'Location'
	},{
		'fieldname': 'team',
		'title': 'Team Details'
	},{
		'fieldname': 'teamburial',
		'title': 'Team Burial Details'
	},{
		'fieldname': 'other',
		'title': 'Other'
	}
];

var subHeadings = {
	'newalert' : {
		'newalert_team' : 'Team',
		'newalert_type' : 'Type',
		'newalert_sdbtype' : 'Burial Activity',
		'newalert_datealert' : 'Date of Alert',
		'newalert_timeprealert' : 'Time of Pre-Alert',
		'newalert_timeallinfo' : 'Time All Info',
	},
	'response' : {
		'response_actiontaken' : 'Action Taken',
		'response_reason_none' : 'Reason No Response'
	},
	'deceased' : {
		'deceased_name' : 'Name',
		'deceased_gender' : 'Gender',
		'deceased_age' : 'Age',
		'deceased_agegroup' : 'Age Group'
	},
	'location': {
		'loc_collectionsite': 'Collection Site',
		'loc_etcname': 'ETC/Hospital',
		'loc_collectionzone': 'Health Zone',
		'loc_collectionarea': 'Health Area',
		'loc_collectionareaother': 'Collection Area (other)',
		'loc_village': 'Village/Health Centre',
		'loc_typedisinfection': 'Place of disinfection',
		'loc_numplacesdisinfected': 'Number of places disinfected'
	},
	'team': {
		'team_activitydate': 'Activity Date',
		'team_timedeparture': 'Time of Departure',
		'team_timearrival': 'Time of Arrival',
		'team_swabtaken': 'Swab Taken',
		'team_disinfected': 'Disinfected',
	},
	'teamburial': {
		'teamburial_status': 'Status',
		'teamburial_reason': 'Reason',
		'teamburial_whynotsuccess': 'Why not successful',
		'teamburial_incidentwhen': 'When refusal/incident happended',
		'teamburial_circumstancesfail': 'Circumstances of failure',
		'teamburial_comments': 'Comments',
	},
	'other': {
		'comments': 'Other Comments'
	}
}

function processData(sdbData) {
	var processedData = [];
	var temp;
	var datetime;
	//console.log(sdbData)
	sdbData.forEach(function(d,i){
		//console.log(d,i)
		temp = {};
		temp['start'] = checkField(d['start']);		//datetime
		temp['end'] = checkField(d['end']);			//datetime
		temp['newalert_team'] = checkField(d['team']);
		temp['newalert_type'] = checkField(d['type']);
		temp['newalert_sdbtype'] = checkField(d['burial_activity']);
		temp['newalert_datealert'] = getFirstValidField(['alert_new/datetime/date_alert','datetime/date_alert'], d);
		temp['newalert_timeprealert'] = getFirstValidField(['alert_new/datetime/time_pre_alert','datetime/time_pre_alert'], d).substr(0,8);
		temp['newalert_timeallinfo'] = getFirstValidField(['alert_new/datetime/time_all_info','datetime/time_all_info'], d).substr(0,8);	
		temp['response_actiontaken'] = getFirstValidField(['alert_new/group_response/action_taken','group_response/action_taken'], d);
		temp['response_reason_none'] = checkField(d['group_response/reason_later_cat']);
		temp['deceased_name'] = checkField(d['group_deceased/name_of_deceased']);		
		temp['deceased_gender'] = checkField(d['group_deceased/gender_of_deceased']);
		temp['deceased_age'] = checkField(d['group_deceased/age_of_deceased']);
		temp['deceased_agegroup'] = getGroupAge(temp['deceased_age']);

		temp['loc_collectionsite'] = checkField(d['group_location/collection_site']);
		temp['loc_etcname'] = checkField(d['group_location/etc_name']);
		temp['loc_collectionzone'] = checkField(d['group_location/collection_zone']);
		temp['loc_collectionarea'] = checkField(d['group_location/collection_area']);
		temp['loc_collectionareaother'] = checkField(d['group_location/collection_area_other']);
		temp['loc_village'] = checkField(d['group_location/location_village']);
		temp['loc_typedisinfection'] = checkField(d['group_location/type_disinfection']);
		temp['loc_numplacesdisinfected'] = checkField(d['group_location/houses_disinfected']);

		var team_specs = getTeamSpecs(d);
		temp['team_activitydate'] = team_specs[0];
		temp['team_timedeparture'] = team_specs[1];
		temp['team_timearrival'] = team_specs[2];
		temp['team_swabtaken'] = team_specs[3];
		temp['team_disinfected'] = team_specs[4];

		temp['teamburial_status'] = checkField(d['team_went/burial/status']);
		temp['teamburial_reason'] = checkField(d['team_went/burial/reason']);
		temp['teamburial_whynotsuccess'] = checkField(d['team_went/burial/why_not_success']);
		temp['teamburial_incidentwhen'] = checkField(d['team_went/burial/when_refusal']);
		temp['teamburial_circumstancesfail'] = getCircumstancesOfFailure(d);
		temp['teamburial_comments'] = checkField(d['team_went/comments']);

		temp['comments'] = checkField(d['comments']);

		//console.log('temp: ', temp);
		processedData.push(temp);
	})
	console.log('processedData: ', processedData);
	return processedData;
}

function createSummarySDBTable(sdbData) {
	var html = "";
	var sdbHtml = "";

	html += '<tr bgcolor="#cfdff9">';

	for (var i=0; i <= mainHeadings.length-1; i++) {
		html += '<th>' + mainHeadings[i].title + '</th>'; 
	}
	html += '</tr>';

	$('#tableSDB').append(html);

	sdbData.forEach(function(d,i){
		sdbHtml = createSummarySDBRow(d, i);
		$('#tableSDB').append(sdbHtml);
	})

}

function createSummarySDBRow(row, count) {
	//console.log('createSummarySDBRow: ', count, row)
	var html = "";
	if (count%2==0) {
		var bgcolor = '#add8e6';  //lightblue
	} else {
		var bgcolor = '#ffffff';
	}

	var startDateTime = getDateTimeFromDatetime(checkField(row['start']));
	var endDateTime = getDateTimeFromDatetime(checkField(row['end']));	
	
	html += '<tr bgcolor="' + bgcolor + '">';
	html += '<td>' + startDateTime[0] + '<br>' + startDateTime[1] + '</td>'; 
	html += '<td>' + endDateTime[0] + '<br>' + endDateTime[1] + '</td>'; 

	for (var i=2; i <= mainHeadings.length-1; i++) {
		html += '<td>' + getSubHeadingHtml(row, mainHeadings[i].fieldname) + '</td>'; 
	};
	
	html += '</tr>';

	return html;
}

function getSubHeadingHtml(row, subhead) {
	var html = '';
	for (var d in subHeadings[subhead]) {
		html += '<i>' + subHeadings[subhead][d] + ': </i><b>' + row[d] + '</b><br>';
	}
	return html;
}

function getTeamSpecs(row) {
	var specs = [' - ',' - ',' - ',' - ',' - ']
	for (var r in row) {
		if (r.substr(0,29)=='team_went/burial/begin_group_') {
			if (r.substr(r.length - 13)=='activity_date') {
				specs[0] = row[r];
			} else if (r.substr(r.length - 17)=='time_of_departure') {
				specs[1] = row[r].substr(0,8);
			} else if (r.substr(r.length - 15)=='time_of_arrival') {
				specs[2] = row[r].substr(0,8);
			} else if (r.substr(r.length - 10)=='swap_taken') {
				specs[3] = row[r];
			} else if (r.substr(r.length - 11)=='disinfected') {
				specs[4] = row[r];
			};
			//console.log(r.substr(0,29))
		}
	}
	return specs;
}


function getCircumstancesOfFailure(row) {
	var circs = [];
	for (var r in row) {
		if (r.substr(0,36)=='team_went/burial/circumstances_fail/') {
			console.log(row[r])
			circs.push(row[r])
		}
	}
	return circs;

}




function createHorizontalSDBTable(sdbData) {
	var html = "";
	var sdbHtml = "";

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

	$('#tableSDB').append(html);

	sdbData.forEach(function(d,i){
		sdbHtml = createHorizontalSDBRow(d);
		$('#tableSDB').append(sdbHtml);
	})

}

function createHorizontalSDBRow(row) {
	//console.log('createHorizontalSDBRow: ', row)
	var html = "";

	html += '<tr>';
	html += '<td>' + getFirstValidField(['alert_new/datetime/date_alert','datetime/date_alert'], row) + '</td>'; //Alert received
	html += '<td>' + getFirstValidField(['alert_new/datetime/time_pre_alert','datetime/time_pre_alert'], row).substring(0,8) + '</td>'; //Time of alert
	html += '<td>' + checkField(row['group_location/collection_zone']) + '</td>'; //Zone Santé
	html += '<td>' + checkField(row['group_location/collection_area']) + '</td>'; //Aire de Santé
	html += '<td>' + checkField(row['group_location/location_village']) + '</td>'; 	//Localité'
	html += '<td>' + checkField(row['group_location/collection_site'])  + '</td>'; //Site de Collection
	html += '<td>' + '' + '</td>'; //Nom
	html += '<td>' + '' + '</td>'; //Résidence
	html += '<td>' + checkField(row['alert_new/group_response/action_taken']) + '</td>'; //Résultat
	html += '<td>' + checkField(row['group_response/action_taken']) + '</td>'; //Status
	html += '<td>' + '' + '</td>'; //Début de la reponse
	html += '<td>' + '' + '</td>'; //Heure de la reponse
	html += '<td>' + '' + '</td>'; //Prélevement post-mortem?
	html += '<td>' + '' + '</td>'; //Desinfection du lieu
	html += '<td>' + checkField(row['group_deceased/gender_of_deceased']) + '</td>'; //Sexe du défunct
	html += '<td>' + getSexCalcul(checkField(row['group_deceased/gender_of_deceased'])) + '</td>'; //Sexe calcul
	html += '<td>' + checkField(row['group_deceased/age_of_deceased']) + '</td>'; //Age du défunct (ans)
	html += '<td>' + '' + '</td>'; //Age du défunct (mois)
	html += '<td>' + getGroupAge(checkField(row['group_deceased/age_of_deceased']))  + '</td>'; //Groupe d\'âge
	html += '<td>' + checkField(row['end']) + '</td>'; //Fin de reponse
	html += '<td>' + '' + '</td>'; //Commentaire
	html += '<td>' + '' + '</td>'; //Raison
	html += '</tr>';

	return html;
}


function checkField(field) {
	if (field == null) {
		return " - ";
	} else {
		return field;
	}
}


function getFirstValidField(fields, row) {
	//console.log(fields, row)
	var i = 0;
	while (i<=fields.length-1) {
		//console.log('field: ', fields[i], row[fields[i]]);
		if (row[fields[i]]!=null) {
			return row[fields[i]];
		};
		i++
	};
	return ' - ';	
}


function getSexCalcul(sex) {
	switch (sex) {
		case 'female': var val = 1; break;
		case 'male': var val = -1; break;
		default: var val = 0;
	}
	return val;
}

function getGroupAge(age) {
	var ageGroup = '';
	switch (true) {
		case age < 5: ageGroup = '00-04y'; break;
		case age < 15: ageGroup = '05-14y'; break;
		case age < 25: ageGroup = '15-24y'; break;
		case age < 35: ageGroup = '25-34y'; break;
		case age < 45: ageGroup = '35-44y'; break;
		case age < 60: ageGroup = '45-59y'; break;
		case age < 110: ageGroup = '60y+'; break;
		default: ageGroup = 'inconnu';
	}
	return ageGroup;
}

function getToday() {
	var todayDate = new Date();
	var today = todayDate.getFullYear() + '-' + twoNum(todayDate.getMonth() + 1) + '-' + twoNum(todayDate.getDate());
	return today;
};

function getYesterday() {
	var yesterdayDate = new Date();
	yesterdayDate.setDate(yesterdayDate.getDate() - 1);
	var yesterday = yesterdayDate.getFullYear() + '-' + twoNum(yesterdayDate.getMonth() + 1) + '-' + twoNum(yesterdayDate.getDate());
	return yesterday;
};


function getDayBefore(currentDay) {  //function accepts string in format YYYY-MM-DD and returns string of previous day in same format

	var currentDate = new Date(parseInt(currentDay.substring(0,4)), parseInt(currentDay.substring(5,7))-1,parseInt(currentDay.substring(8,10)));

	var dateBefore = new Date();
	dateBefore.setDate(currentDate.getDate() - 1);
	var dayBefore = "";
	dayBefore = dateBefore.getFullYear() + '-' + twoNum(dateBefore.getMonth() + 1) + '-' + twoNum(dateBefore.getDate());

	return dayBefore;
};

function getDateTimeFromDatetime(datetime){
	//console.log(datetime)

	var months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];
	
	function checkTime(i) {
	  if (i < 10) {
	    i = "0" + i;
	  }
	  return i;
	}

	//Parsing time (the time below is assumed to be GMT+2) from string
	//Removing timezone stamp at end of string - need to check this with SIMS
	if(datetime.indexOf('+')>0){
		datetime = datetime.substring(0,datetime.indexOf('+')-4);
	} else {
		let parts = datetime.split('-');
		let loc = parts.pop();
		datetime = parts.join('-');
	}

	let newDate = new Date(datetime);
//	let time = newDate.getTime();
	let h = newDate.getHours();
	let m = newDate.getMinutes();
	let s = newDate.getSeconds();
	// add a zero in front of numbers<10
	m = checkTime(m);
	s = checkTime(s);
	let time = h + ":" + m + ":" + s;
	let date = newDate.getDate() + '-' + months[newDate.getMonth()] + '-' + newDate.getFullYear();
	//console.log(date,time)
	return [date, time];
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


// Get SDB/EDS data from KoBo
$(document).ready(function () {
	var d0 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/273933?format=jsonp',
    	dataType: 'jsonp',
    });

    $.when(d0).then(function (a0) {
        console.log('Ajax call succeedeed');
        console.log(a0);
        //createHorizontalSDBTable(a0.reverse());
        var data = processData(a0.reverse());
        createSummarySDBTable(data);
    }, function (jqXHR, textStatus, errorThrown) {
        var x0 = d0;
        if (x0.readyState != 4) {
            x0.abort();
        }
        alert("Data request failed");
        console.log('Ajax request failed');
    });

});
