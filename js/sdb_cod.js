"use strict";

//**************************************************************************************************//
// BRC Maps Team - SIMS DRC Ebola response
// Sept  2018
//
// NOTES:
// 1. In cfg_subHeadings.csv:
//    - order counts - i.e. calculate fields must come after the fields that they are based on
//		 - perhaps all calculate fields should be at the bottom of the file?
// 	  - for team specs - replace team characters with 'xxxxxxxx' in config file - this can then match
//		 any teams defined
//
// STILL NEED TO ACCOUNT FOR FIELDS: 
//    - burial_reason - limited choice?
//    - burial_when_refusal - limited choice? 
//	  - group response action_taken - limited choice? 
//    - group response reason_later_cat - limited choice? 
// STILL NEED TO CALCULATE FIELDS: 
//    - epiweek number (excel col BX)
//    - status (excel col BZ, based on resultat)
//    - sex (excel col CC)
//    - response time (excel col CJ)
// *** Order by Alert Start
//
//**************************************************************************************************//


var mainHeadings, subHeadings;

//Parses CSV files - creates array of objects
//Splits text at each new line, splits each line at commas
function processHeadings(heads) {
	//console.log(heads);

    try {   
        var data = {}		
        var records = []	
        var lines =heads.split(/\r\n|\r|\n/)   //splits csv data at each new line
        var columns = lines[0].split(',')      //creates columns by splitting first line of csv
            
        for (var l=1; l<=lines.length-1; l++) {           
            var words = lines[l].split(',');  
            //build object based on column headers
            for (var cell in columns) {
                data[columns[cell]] = words[cell];          
            }
            records.push(data);
            data = {};
        }
        //console.log('records: ', records)
        return records
    } catch(err){
    	console.log('Error processing headings: ', err)
        return err
    }
}


function getKoboFieldnames() {
	var fieldname_list = [];
	for (var i=0; i<=subHeadings.length-1; i++) {
		fieldname_list.push(subHeadings[i].kobo_fieldname);
	};
	return fieldname_list;
}; 

//function to reverse sort array of objects by a given key
function reverseSortByKey(array, key) {
    return array.sort(function(a, b) {
        var x = a[key]; 
        var y = b[key];
        //return ((x < y) ? -1 : ((x > y) ? 1 : 0));   //sort
        return ((x > y) ? -1 : ((x < y) ? 1 : 0));   //reverse sort
    });
}


function processKoboSDBdata(sdbData) {
	console.log('original data: ', sdbData)
	var processedData = [];
	var temp;
	var datetime;
	var circumstancesOfFailure, circ;
	
	var kobo_fieldnames = getKoboFieldnames();
	//console.log('Kobo fieldnames: ', kobo_fieldnames);

	//create new dataset from sdbData using kobo_fieldnames as keys
	sdbData.forEach(function(record,i){
		//console.log(record,i)
		temp = {};
		circumstancesOfFailure = [];

		//for each subHeading (corresponds to each row defined in csfg_subHeadings.csv - i.e. all kobo fieldnames and calculated fields)
		for (var h in subHeadings) {
			//console.log(h, subHeadings[h])
			//console.log(subHeadings[h].mainheading_prefix)
			if (subHeadings[h].mainheading_prefix!='') {  //temporary hackfix - because github keeps adding blank row to end of csv
		
				//1. CREATE A KEY (new_keyname) IN NEW DATA RECORD (temp) WHETHER OR NOT THERE IS DATA - accounts for if there are multiple possible fields or no fields
				var new_keyname = ''; // = subHeadings[h].kobo_fieldname;
				var kobo_fieldused = '';
				var first_valid_field = [];
				
				//if there are 2 possible fields defined (i.e. kobo_fieldname has multiple inputs joined by '&') AND data_check value is 'selectFirstValid'
				if ((subHeadings[h].kobo_fieldname.indexOf('&') != -1)  && (subHeadings[h].data_check.indexOf('selectFirstValid') != -1)) {
					//then new_keyname is assigned to first in list of possible fieldnames (even if data comes from a diff new_keyname, as need to keep fieldnames consistent)
					new_keyname = subHeadings[h].kobo_fieldname //.split('&')[0];
					//value is the first valid (i.e. not null) FIELD irrespective of new_keyname given
					first_valid_field = getFirstValidField(subHeadings[h].kobo_fieldname, record);  
					//console.log('first_valid_field: ', first_valid_field);
					if (!(first_valid_field.length == 0)) {
						temp[new_keyname] = first_valid_field[0];
						//record[new_keyname] = ''
						record[new_keyname] = first_valid_field[0];  //add key to original dataset also with correct new_keyname
						kobo_fieldused = first_valid_field[1];
					} else {
						//console.log('CHECK THIS ONE')
						kobo_fieldused = 'NA';
						temp[new_keyname] = '';
					}	

				//if there are no fields defined AND value is defined for 'calculate'
				} else if ((subHeadings[h].kobo_fieldname == '') && (subHeadings[h].calculate != null)) {
					kobo_fieldused = 'NA';
					new_keyname = subHeadings[h].calculate;
					if (new_keyname == 'age_group') {
						//console.log('Calculating age group...')
						temp[new_keyname] = getAgeGroup(temp['group_deceased/age_of_deceased']);
					}

				} else if (subHeadings[h].kobo_fieldname.indexOf('xxxxxxxx') != -1) {
					kobo_fieldused = 'NA';
					new_keyname = subHeadings[h].kobo_fieldname;
					temp[new_keyname] = getTeamSpecs(new_keyname, record);

				} else if (subHeadings[h].kobo_fieldname.substr(0,36)=='team_went/burial/circumstances_fail/') {  
					//console.log(subHeadings[h].kobo_fieldname);
					kobo_fieldused = 'NA';
					new_keyname = subHeadings[h].kobo_fieldname;
					temp[new_keyname] = getCircumstancesOfFailure(new_keyname, record);
					/*if (circ != null) {
						temp[new_keyname].push(circ);
					};*/
					

				//otherwise there is 1 corresponding field
				} else {
					try {
						kobo_fieldused = subHeadings[h].kobo_fieldname;
						//new_keyname = subHeadings[h].kobo_fieldname;
						new_keyname = kobo_fieldused;
						temp[new_keyname] = record[new_keyname];     		//copy original key and value over to temp object
						//console.log(new_keyname, temp[new_keyname], typeof(temp[new_keyname]));
					} catch(err) {
				    	console.log('Error processing SDB data: ', err)
				        return err
				    }
				}
				temp[new_keyname] = checkField(temp[new_keyname]);
				//console.log('new_keyname ', new_keyname, ': ', temp[new_keyname]);



				//2. DEAL WITH DATA CHECKS

				//console.log(subHeadings[h].data_check, subHeadings[h].data_check.indexOf('time'), '-------', subHeadings[h])
				//if field defined as 'time' (but not datetime) then take first 8 characters (i.e. HH:MM:SS)
				if ((subHeadings[h].data_check.indexOf('time') != -1) && (subHeadings[h].data_check.indexOf('datetime') == -1)) {
					//console.log(subHeadings[h].kobo_fieldname, new_keyname,kobo_fieldused, record[kobo_fieldused]);
					//console.log(subHeadings[h],new_keyname, kobo_fieldused)
					if (kobo_fieldused == 'NA') {
						if (subHeadings[h].kobo_fieldname.indexOf('xxxxxxxx')) {
							temp[new_keyname] = temp[new_keyname].substr(0,8);
							//console.log(new_keyname, temp[new_keyname], typeof(temp[new_keyname]))
						} else {
							temp[new_keyname] = 'CHECK';
						}

					} else if (kobo_fieldused == '') {
						temp[new_keyname] = 'CHECK BLANK FIELD';
					} else {
						//console.log(new_keyname, kobo_fieldused, record[kobo_fieldused])
						temp[new_keyname] = record[kobo_fieldused].substr(0,8);
						
					}
					
				//if field defined as 'datetime'	
				} else if (subHeadings[h].data_check.indexOf('datetime') != -1) {
					
					temp[new_keyname] = getDateTimeFromDatetime(temp[kobo_fieldused]);
					//console.log(new_keyname, kobo_fieldused, temp[new_keyname], typeof(temp[new_keyname]))

				} 
			}

		}
		//console.log('temp: ', temp);
		processedData.push(temp);
	});

	//order data by date (once date is parsed)
	processedData = reverseSortByKey(processedData, 'start');

	console.log('processedData: ', processedData);
	return processedData;
}

function createSummarySDBTable(sdbData) {
	var html = "";
	var sdbHtml = "";

	//write table headings
	html += '<tr bgcolor="#cfdff9">';
	for (var i=0; i <= mainHeadings.length-1; i++) {
		html += '<th>' + mainHeadings[i].dashboard_mainheading_title + '</th>'; 
	}
	html += '</tr>';
	$('#tableSDB').append(html);

	//write table rows
	sdbData.forEach(function(d,i){
		sdbHtml = createSummarySDBRow(d, i);
		$('#tableSDB').append(sdbHtml);
	})

}

function createSummarySDBRow(row, count) {
	//console.log('createSummarySDBRow: ', count, row)
	var html = "";
	var bgcolor;

	count%2==0? bgcolor = '#add8e6' : bgcolor = '#ffffff';  //alternate row colors
	
	html += '<tr bgcolor="' + bgcolor + '">';
	for (var i=0; i <= mainHeadings.length-1; i++) {
		html += '<td>' + getSubHeadingHtml(mainHeadings[i].mainheading_prefix, row) + '</td>'; 
	};	
	html += '</tr>';

	return html;
}


function getSubHeadingHtml(mainhead, record) {
	//console.log('RECORD: ', mainhead, record)
	var html = '';

	//loop through all subheadings
	for (var i=0; i <= subHeadings.length-1; i++) {
		//console.log(i, subHeadings[i])
		
		//if the subheading belongs to the current mainheading
		if (subHeadings[i].mainheading_prefix == mainhead) {
			
			//loop through the all fields in the record
			for (var r in record) {
				//console.log('r: ', r)
				if (subHeadings[i].kobo_fieldname == r) {
					//console.log(typeof(record[r]), record[r])
					if (subHeadings[i]['dashboard_subheading_title'] == 'Circumstances of failure') {
						//console.log(typeof(record[r]), record[r]);
						if ((record[r].yes.length==0) && (record[r].no.length==0) && (record[r].unknown.length==0) && (record[r].error.length==0)) {
							html += '<i>' + subHeadings[i]['dashboard_subheading_title'] + ': </i><b> - </b><br>';
						} else {
							html += '<i>' + subHeadings[i]['dashboard_subheading_title'] + ': </i><br>';
							if (record[r].yes.length!=0) {
								html += '&nbsp&nbspYES: </span><b>' + record[r].yes + '</b><br>';
							};
							if (record[r].no.length!=0) {
								html += '&nbsp&nbspNO: <b>' + record[r].no + '</b><br>';
							};
							if (record[r].unknown.length!=0) {
								html += '&nbsp&nbspUNKNOWN: <b>' + record[r].unknown + '</b><br>';
							};
							if (record[r].error.length!=0) {
								html += '&nbsp&nbspERROR: <b>' + record[r].error + '</b><br>';
							};
						}
					} else if (subHeadings[i]['dashboard_subheading_title'] != '') {
						html += '<i>' + subHeadings[i]['dashboard_subheading_title'] + ': </i><b>' + record[r] + '</b><br>';
					} else if (record[r] instanceof Date) {
						html += '<b>' + formatDate(record[r])[0] + '<br>' + formatDate(record[r])[1] + '</b><br>';
					} else {
						html += '<b>' + record[r] + '</b><br>';
					}			
				} else if (subHeadings[i].calculate == r) {
					if (subHeadings[i]['dashboard_subheading_title'] != '') {
						html += '<i>' + subHeadings[i]['dashboard_subheading_title'] + ': </i><b>' + record[r] + '</b><br>';
					} else {
						html += '<b>' + record[r] + '</b><br>';
					}
				}
			}
		}

	}

	return html;
}

function formatDate(date) {
	//console.log(date);
	var months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];

	function checkTime(i) {
	  if (i < 10) {
	    i = "0" + i;
	  }
	  return i;
	}

	//let time = date.getTime();
	let h = date.getHours();
	let m = date.getMinutes();
	let s = date.getSeconds();
	//add a zero in front of numbers<10
	m = checkTime(m);
	s = checkTime(s);
	let time = h + ":" + m + ":" + s;
	let newdate = date.getDate() + '-' + months[date.getMonth()] + '-' + date.getFullYear();
	
	return [newdate, time];
}


function getTeamSpecs(key, row) {
	//console.log(key, row);
	for (var r in row) {
		if (key.substr(0,29)==r.substr(0,29)) {			//i.e. both =='team_went/burial/begin_group_'
			//console.log('r: ', r.substr(r.length - 17), '   key: ', key.substr(key.length - 17))
			if ((r.substr(r.length - 13)=='activity_date') && (key.substr(key.length - 13)=='activity_date')) {
				//console.log('return ', row[r])
				return row[r];
			} else if ((r.substr(r.length - 17)=='time_of_departure') && (key.substr(key.length - 17)=='time_of_departure')) {
				//console.log('return ', row[r])
				return row[r].substr(0,8);
			} else if ((r.substr(r.length - 15)=='time_of_arrival') && (key.substr(key.length - 15)=='time_of_arrival')) {
				//console.log('return ', row[r])
				return row[r].substr(0,8);
			} else if ((r.substr(r.length - 10)=='swap_taken') && (key.substr(key.length - 10)=='swap_taken')) {
				//console.log('return ', row[r])
				return row[r];
			} else if ((r.substr(r.length - 11)=='disinfected') && (key.substr(key.length - 11)=='disinfected')) {
				//console.log('return ', row[r])
				return row[r];
			};
		}
	}
	return ' - '; //specs;
}


function getCircumstancesOfFailure(key, row) {
	var circs = {
					'support_teams_present_yn': 'Support teams present',
					'explanation_sdb_yn': 'Explanation of SDB process',
					'protocol_reasons_sdb_yn': 'Understood protocol and reasons for SDB',
					'agree_bury_deceased_yn': 'Agreed to bury deceased',
					'nominated_witness_yn': 'Nominated witness',
					'deceased_objects_yn': 'Deceased objects in coffin',
					'agree_bury_location_yn': 'Agreed bury location',
					'agree_burial_route_yn': 'Agreed burial route',
					'agree_sdb_team_safe_yn': 'Agreed SDB team safe',
					'agree_last_words_yn': 'Agreed last words',
				};
	var circ_results = {'yes': [], 'no': [], 'unknown':[], 'error': []};
	for (var r in row) {
		if (r.substr(0,36)=='team_went/burial/circumstances_fail/') {
			//console.log('getCircumstancesOfFailure: ', key, row)
			//console.log(r.substr(r.length - 24), key.substr(key.length - 24))
			
			for (var c in circs) {
				//console.log('c: ', c, circs[c])
				if ((r.substr(r.length - c.length)==c)) {
					switch (row[r]){
						case 'yes': circ_results.yes.push(circs[c]); break;
						case 'no': circ_results.no.push(circs[c]); break;
						case 'unknown': circ_results.unknown.push(circs[c]); break;
						default: circ_results.error.push(circs[c])
					}
				}

			}
			//console.log(row[r])
		}
	}
	//console.log(circ_results)
	return circ_results;

}



function checkField(field) {
	if ((field == null) || (field == '')) {
		return " - ";
	} else {
		return field;
	}
}


function getFirstValidField(fields, row) {
	//console.log(fields, row);
	var fields_list = fields.split('&');
	//console.log(fields_list)
	
	var i = 0;
	while (i<=fields_list.length-1) {
		//console.log('field: ', fields_list[i], row[fields_list[i]]);
		if (row[fields_list[i]]!=null) {
			return [row[fields_list[i]],fields_list[i]];
		};
		i++
	};
	return [];	
}


function getSexCalcul(sex) {
	switch (sex) {
		case 'female': var val = 1; break;
		case 'male': var val = -1; break;
		default: var val = 0;
	}
	return val;
}

function getAgeGroup(age) {
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

function getDateTimeFromDatetime(datetime){
	//console.log('datetime input: ', datetime)

	/*var months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];
	
	function checkTime(i) {
	  if (i < 10) {
	    i = "0" + i;
	  }
	  return i;
	}*/

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
	
	return newDate;
}

/*function createHorizontalSDBTable(sdbData) {
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

}*/
/*
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
}*/





/*function rV(v) {
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
}*/


// Get SDB/EDS data from KoBo, get headings data from CSV
$(document).ready(function () {
	var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/273933?format=jsonp',
    	dataType: 'jsonp',
    });

    var d2 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_mainHeadings.csv',
    	dataType: 'text'
    });

    var d3 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_subHeadings.csv',
    	dataType: 'text'
    });

    $.when(d1, d2, d3).then(function (a1,a2,a3) {
        console.log('Ajax calls succeedeed');
        //console.log(a1[0],a2);
        //createHorizontalSDBTable(a0.reverse());
        
        mainHeadings = processHeadings(a2[0]);
        console.log('main headings: ', mainHeadings);
        subHeadings = processHeadings(a3[0]);
        console.log('sub headings: ', subHeadings);
        var data = processKoboSDBdata(a1[0].reverse());
        createSummarySDBTable(data);

    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        var x2 = d2;
        var x3 = d3;
        if (x1.readyState != 4) {
            x1.abort();
        };
        if (x2.readyState != 4) {
            x2.abort();
        };
        if (x3.readyState != 4) {
            x3.abort();
        };
        alert("Data request failed");
        console.log('Ajax request failed');
    });

});
