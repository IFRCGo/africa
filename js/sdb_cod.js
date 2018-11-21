"use strict";

//**************************************************************************************************//
// BRC Maps Team - SIMS DRC Ebola response
// Sept-Nov 2018
//
// NOTES:
// 1. In cfg_excelHeadings.csv:
//    - order counts - i.e. calculate fields must come after the fields that they are based on
//		 - perhaps all calculate fields should be at the bottom of the file?
//    - for team specs - replace team characters with 'xxxxxxxx' in config file - this can then match
//		 any teams defined
//
//**************************************************************************************************//


let excelHeadings, data, currentData;
//let koboFields;

let blank = ' ';

let mainHeadings = {
	    'submission': 'Kobo Submission',
		'start': 'Alert Start',
		'end': 'Alert End',
		'newalert': 'Alert Details',
		'response': 'Response',
		'deceased': 'Deceased',
		'location': 'Location',
		'team': 'Team Details',
		'teamburial': 'Team Burial Details',
		'other': 'Other',
};

let spellChanges = {
	'etc': 'CTE',
}


let unique_zones_sante = [];

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

/*function getKoboFields(records) { 		//reads all fieldnames from kobo data
	var fieldname_list = [];
	for (var i=0; i<=records.length-1; i++) {
		//console.log(records[i]);
		for (var field in records[i]) {
			if (fieldname_list.indexOf(field)==-1) {
				fieldname_list.push(field);
			}
			
		}
	};
	//console.log('kobo fields: ', fieldname_list);
	return fieldname_list;
};*/ 

/**/

//function to reverse sort array of objects by a given key
function reverseSortByKey(array, key) {
	//console.log(array, key)
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
	var all_zones = [];

	
	//var kobo_fieldnames = getKoboFieldnames();
	//console.log('Kobo fieldnames: ', kobo_fieldnames);

	//create new dataset from sdbData using kobo_fieldnames as keys
	sdbData.forEach(function(record,i){
		//console.log(record,i)
		temp = {};
		//circumstancesOfFailure = [];


		//FIRST ADD KOBO FIELDS NEEDED FOR PROCESSING ONLY, NOT FOR OUTPUT
		temp['date_submitted'] = new Date(record['_submission_time'])
		//console.log(record['_submission_time'], temp['date_submitted'])
		temp['team_went/burial/status'] = record['team_went/burial/status'];

		//CALCUALTE alert_received FIELD - USED BY DATE FILTERING CHART
		let temp_alert_received = getFirstValidField('alert_new/datetime/date_alert&&datetime/date_alert&&start', record);
		//console.log(temp_alert_received)
		if (temp_alert_received.length > 0) {
			/*if (temp_alert_received[1]=='start') {  //date type
				temp['alert_received'] = new Date(parseInt(temp_alert_received[0].substr(0,4)), parseInt(temp_alert_received[0].substr(5,7))-1, parseInt(temp_alert_received[0].substr(8,10)));
				
				console.log(temp_alert_received, temp['alert_received'])
				console.log(temp['alert_new/datetime/date_alert&&datetime/date_alert&&start'])
				//temp['alert_new/datetime/date_alert&&datetime/date_alert&&start'] = temp['alert_received'];

			} else {*/		//string type
				temp['alert_received'] = new Date(parseInt(temp_alert_received[0].substr(0,4)), parseInt(temp_alert_received[0].substr(5,7))-1, parseInt(temp_alert_received[0].substr(8,10)));		
			//}
		} else {
			//console.log('blank alert_received: ', temp['alert_received'], record)
			temp['alert_received'] = '';
		};
		//console.log(temp['alert_received']);

		//for each excelHeading (corresponds to each row defined in cfg_excelHeadings.csv - i.e. all kobo fieldnames and calculated fields)
		for (var h in excelHeadings) {
			//console.log(h, excelHeadings[h])
			if (excelHeadings[h].excel_heading!='') {  //temporary hackfix - because github keeps adding blank row to end of csv
		
				//1. CREATE A KEY (new_keyname) IN NEW DATA RECORD (temp) WHETHER OR NOT THERE IS DATA 
				var new_keyname = ''; 
				var kobo_fieldused = '';
				
				//if multiple fields defined (i.e. kobo_fieldname has multiple inputs joined by '&&') AND should select first defined only (i.e. processing_options contains 'selectFirstValid')
				if ((excelHeadings[h].kobo_fieldname.indexOf('&&') != -1)  && (excelHeadings[h].processing_options.indexOf('selectFirstValid') != -1)) {
					var first_valid_field = [];
					//then new_keyname is assigned to first in list of possible fieldnames (even if data comes from a diff new_keyname, as need to keep fieldnames consistent)
					new_keyname = excelHeadings[h].kobo_fieldname //.split('&&')[0];
					first_valid_field = getFirstValidField(excelHeadings[h].kobo_fieldname, record);  //returns [value, keyname]
					//console.log('first_valid_field: ', first_valid_field, excelHeadings[h].kobo_fieldname);
					
					if (first_valid_field.length == 0) {	    //if all fields were null
						//console.log('CHECK THIS ONE')
						kobo_fieldused = 'NA';
						temp[new_keyname] = '';
					} else {									//if a populated field was found
						temp[new_keyname] = first_valid_field[0];
						//record[new_keyname] = first_valid_field[0];  //add key to original dataset also with correct new_keyname
						kobo_fieldused = first_valid_field[1];
					}	

				//if multiple fields defined (i.e. kobo_fieldname has multiple inputs joined by '&&') and want to include them all
				} else if ((excelHeadings[h].kobo_fieldname.indexOf('&&') != -1) && (excelHeadings[h].processing_options.indexOf('selectAllValid') != -1)) {
					var all_valid_fields = [];
					new_keyname = excelHeadings[h].kobo_fieldname //.split('&&')[0];
					kobo_fieldused = excelHeadings[h].kobo_fieldname
					all_valid_fields = getAllValidFields(excelHeadings[h].kobo_fieldname, record);  //returns string of concatenated values
					temp[new_keyname] = all_valid_fields;
					//record[new_keyname] = all_valid_fields;


				//if there are no fields defined AND processing_options contains 'calc-'
				} else if ((excelHeadings[h].kobo_fieldname == '') && (excelHeadings[h].processing_options.indexOf('calc-') != -1)) {
					kobo_fieldused = 'NA';
					new_keyname = excelHeadings[h].processing_options;
					switch (new_keyname.substr(5)) {	
						case 'age_group': temp[new_keyname] = getAgeGroup(temp['group_deceased/age_of_deceased']); break;
						case 'sex': temp[new_keyname] = getSexCalcul(temp['group_deceased/gender_of_deceased']); break;
						case 'response_time': temp[new_keyname] = getResponseTime(temp['alert_new/datetime/date_alert&&datetime/date_alert&&start'], temp['alert_new/datetime/time_pre_alert&&datetime/time_pre_alert'],temp['team_went/burial/begin_group_xxxxxxxx/activity_date'],temp['team_went/burial/begin_group_xxxxxxxx/time_of_departure']);
							if (temp[new_keyname]==blank) temp[new_keyname]='Not available'; break;
						case 'epiweek_num': temp[new_keyname] = getEpiweekNum(temp['alert_new/datetime/date_alert&&datetime/date_alert&&start']); break;
						case 'result_type': var result = getResultType(temp);
											//console.log(new_keyname, result)
												temp[new_keyname] = result; break;
						case 'status_type': temp[new_keyname] = getStatusType(temp['calc-result_type']); break;
						default: temp[new_keyname] = '';
					}

				//if fieldname contains 'xxxxxxxx' to represent team code
				} else if (excelHeadings[h].kobo_fieldname.indexOf('xxxxxxxx') != -1) {
					kobo_fieldused = 'NA';
					new_keyname = excelHeadings[h].kobo_fieldname;
					temp[new_keyname] = getTeamSpecs(new_keyname, record);
					//if (temp[new_keyname]==blank) console.log(new_keyname, record)

				//if fieldname corresponds to circumstances of failure 
				} else if (excelHeadings[h].processing_options == 'yn') {  
					//kobo_fieldused = 'NA';
					new_keyname = excelHeadings[h].kobo_fieldname;
					//temp[new_keyname] = getCircumstancesOfFailure(new_keyname, record);
					temp[new_keyname] = record[new_keyname];

				//if there are multiple choice options
				} else if (excelHeadings[h].processing_options.substr(0,15) == 'multiple_choice') {	
					//console.log(excelHeadings[h].processing_options)
					if (excelHeadings[h].processing_options.substr(-5) == 'title') {
						kobo_fieldused = excelHeadings[h].kobo_fieldname;
						new_keyname = kobo_fieldused;
						temp[new_keyname] = record[new_keyname];
					} else if (excelHeadings[h].processing_options.substr(-6) == 'option') {
						kobo_fieldused = excelHeadings[h].kobo_fieldname.split('&&');
						new_keyname = excelHeadings[h].kobo_fieldname;
						if (record.hasOwnProperty(kobo_fieldused[0])) {
							//console.log(excelHeadings[h].kobo_fieldname, kobo_fieldused, record[kobo_fieldused[0]]);
							if ((record[kobo_fieldused[0]].indexOf(kobo_fieldused[1]) == -1) || (kobo_fieldused[1]=='')) {
								temp[new_keyname] = '0'; //'0' or 'no'?
							} else {	
								temp[new_keyname] = '1'; //'1' or 'yes'?
								//console.log(excelHeadings[h].kobo_fieldname, kobo_fieldused, record[kobo_fieldused[0]],temp[new_keyname])
							}
						} else {
							temp[new_keyname] = blank;
						}					

					}
					

				//otherwise there is 1 corresponding field
				} else {
					try {
						kobo_fieldused = excelHeadings[h].kobo_fieldname;
						new_keyname = kobo_fieldused;
						temp[new_keyname] = record[new_keyname];     		//copy original key and value over to temp object
						if (new_keyname=='team') {
							temp[new_keyname] = formatTeamNames(record[new_keyname]);   
						}
						//console.log(new_keyname, temp[new_keyname], typeof(temp[new_keyname]));
					} catch(err) {
				    	console.log('Error processing SDB data: ', err)
				        return err
				    }
				}

				//replace spellings with spellChanges
				if (spellChanges.hasOwnProperty(temp[new_keyname])) {
					temp[new_keyname] = spellChanges[temp[new_keyname]];
				}

				//check all fields for null values
				temp[new_keyname] = checkField(temp[new_keyname]);



				//2. DEAL WITH DATA CHECKS

				//if field defined as 'time' (but not 'datetime' and not 'calc-') then take first 8 characters (i.e. HH:MM:SS)
				if ((excelHeadings[h].processing_options.indexOf('time') != -1) && (excelHeadings[h].processing_options.indexOf('datetime') == -1)  && (excelHeadings[h].processing_options.indexOf('calc-') == -1)) {
					//console.log(excelHeadings[h].kobo_fieldname, new_keyname,kobo_fieldused, record[kobo_fieldused]);

					if (kobo_fieldused == 'NA') {
						if (excelHeadings[h].kobo_fieldname.indexOf('xxxxxxxx')) {
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
				} else if (excelHeadings[h].processing_options.indexOf('datetime') != -1) {					
					temp[new_keyname] = getDateTimeFromDatetime(temp[kobo_fieldused]);
					//console.log(new_keyname, kobo_fieldused, temp[new_keyname], typeof(temp[new_keyname]))

				} 
				

			}

		}
		all_zones.push(record['group_location/collection_zone']);
		//console.log('temp: ', temp);
		processedData.push(temp);
	});

	unique_zones_sante = all_zones.filter(onlyUnique).filter(z => ((z!='')&&(z!=undefined)) );
	console.log('Unique zones sante: ', unique_zones_sante);

	//order data by date (once date is parsed)
	//processedData = reverseSortByKey(processedData, 'alert_new/datetime/date_alert&&datetime/date_alert&&start');
	processedData = reverseSortByKey(processedData, 'date_submitted');
	//processedData = reverseSortByKey(processedData, 'alert_received');

	console.log('processedData: ', processedData);
	return processedData;
}


function onlyUnique(value, index, self) { 
    return self.indexOf(value) === index;
}


function formatTeamNames(str) {   //replace underscores with space, then capitalise each word
   str = str.replace(/\_/g,' ');
   return str.replace(/\w\S*/g, function(txt){return txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase();});
};


function createSummarySDBTable(sdbData) {
	//console.log("currentData: ", sdbData)
	var html = "";
	var sdbHtml = "";
	$('#tableSDB').html('');
	//write table headings
	html += '<thead bgcolor="#cfdff9">';
	for (var mainHead in mainHeadings) {
		html += '<th>' + mainHeadings[mainHead] + '</th>'; 
	}
	html += '</thead>';
	$('#tableSDB').append(html);

	//sdbData = reverseSortByKey(sdbData, 'alert_new/datetime/date_alert&&datetime/date_alert&&start');
	sdbData = reverseSortByKey(sdbData, 'date_submitted');
	//sdbData = reverseSortByKey(sdbData, 'alert_received');

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
	for (var mainHead in mainHeadings) {
		html += '<td>' + getSubHeadingHtml(mainHead, row) + '</td>'; 
	}
	html += '</tr>';

	return html;
}


function getSubHeadingHtml(mainhead, record) {
	//console.log('RECORD: ', mainhead, record)
	var html = '';

	//loop through all excelheadings
	for (var i=0; i <= excelHeadings.length-1; i++) {
		//console.log(i, excelHeadings[i])

		if (excelHeadings[i].dashboard_category==mainhead) {  //if the excel heading is in the correct category, output it here

			if (excelHeadings[i]['kobo_fieldname'] == '_submission_time') {
				var submit_date_out;
				if (record[excelHeadings[i]['kobo_fieldname']] == blank) {
					html += '<b>Not available</b><br>';	
					console.log('Alert! Submission date not available', record[excelHeadings[i]['kobo_fieldname']])
				} else {
					submit_date_out = formatDateTime(new Date(record[excelHeadings[i]['kobo_fieldname']]),'screen');
					html += '<b>' + submit_date_out[0] + ' ' + submit_date_out[1] + '</b><br>';	
				}	

			} else if (excelHeadings[i]['kobo_fieldname'] == 'team_went/burial/begin_group_xxxxxxxx/activity_date') {
				//console.log('return ', record[r])
				var date_output, if_new_line;
				record[excelHeadings[i].kobo_fieldname] == blank? date_output = 'Not available' : date_output = formatDate(record[excelHeadings[i].kobo_fieldname],'screen');
				excelHeadings[i].dashboard_category == 'start'? if_new_line = '<br>' : if_new_line = '';
				html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i>' + if_new_line + '<b>' + date_output + '</b><br>';		


			} else if (excelHeadings[i].processing_options.substr(0,15) == 'multiple_choice') {
				if (record[excelHeadings[i].kobo_fieldname] != blank) {
					//console.log('Mulitple choice: ', excelHeadings[i].excel_heading, record[excelHeadings[i].kobo_fieldname]);
					if (excelHeadings[i].processing_options.substr(-5) == 'title') {
						html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br>';
					} else if (excelHeadings[i].processing_options.substr(-6) == 'option') {
						if (record[excelHeadings[i].kobo_fieldname] == 1) {
							html += '&nbsp&nbsp<i><b>' + excelHeadings[i]['excel_heading'] + '</b></i><br>';
						}	
					}
				}
				
			} else if (excelHeadings[i].processing_options.substr(0,2) == 'yn') {
				//console.log('Yes No: ', excelHeadings[i].excel_heading);
				if (excelHeadings[i].processing_options.substr(-5) == 'title') {
					//if not all sub-questions are empty then output title
					var yn_all_empty = true;
					for (var k=0; k<=excelHeadings.length-1; k++) {
						if (excelHeadings[k].excel_heading!='') {  //because github adds blank row to end of csv
							if (excelHeadings[k].processing_options.substr(0,4) == excelHeadings[i].processing_options.substr(0,4)) {
								if (record[excelHeadings[k].kobo_fieldname] != blank) {
									yn_all_empty = false;
								}
							}
						}
					}
					if (!(yn_all_empty)) {html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br>'};
					//html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br>';
				} else {
					if (record[excelHeadings[i].kobo_fieldname] == 'yes') {
						html += '&nbsp&nbsp<i>' + excelHeadings[i]['excel_heading'] + '</i> - Yes<br>';
					} else if (record[excelHeadings[i].kobo_fieldname] == 'no') {
						html += '&nbsp&nbsp<i>' + excelHeadings[i]['excel_heading'] + '</i> - No<br>';
					} else if (record[excelHeadings[i].kobo_fieldname] == 'unknown') {
						html += '&nbsp&nbsp<i>' + excelHeadings[i]['excel_heading'] + '</i> - Unknown<br>';
					};
				}



			} else if (excelHeadings[i].kobo_fieldname == '') {
				if (excelHeadings[i].processing_options.substr(0,5)=='calc-') {
					//console.log(excelHeadings[i].processing_options, record[excelHeadings[i].processing_options])
					html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><b>' + record[excelHeadings[i].processing_options] + '</b><br>';
				} else {
					//console.log('No data processed for: ', excelHeadings[i].excel_heading);
				}

			} else if (record.hasOwnProperty(excelHeadings[i].kobo_fieldname)) {
				//console.log('YES has key ', excelHeadings[i].kobo_fieldname, ': ', record[excelHeadings[i].kobo_fieldname])
				//if ((record[excelHeadings[i].kobo_fieldname] == blank) || (record[excelHeadings[i].kobo_fieldname] == '-')) {
				
				if (record[excelHeadings[i].kobo_fieldname] == blank) {
					//console.log('Not displayed to screen: ', excelHeadings[i].kobo_fieldname, excelHeadings[i].processing_options);
				} else if (excelHeadings[i].kobo_fieldname=='alert_new/datetime/date_alert&&datetime/date_alert&&start') {
					//console.log(excelHeadings[i].kobo_fieldname, record[excelHeadings[i].kobo_fieldname], record['alert_received'])
					html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br><b>' + formatDateTime(record['alert_received'],"screen")[0] + '</b><br>';
				
				} else if (record[excelHeadings[i].kobo_fieldname] instanceof Date) {
					//console.log(excelHeadings[i].kobo_fieldname)
					html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br><b>' + formatDateTime(record[excelHeadings[i].kobo_fieldname],"screen")[0] + '<br>' + formatDateTime(record[excelHeadings[i].kobo_fieldname],"screen")[1] + '</b><br>';

				} else {
					//console.log(excelHeadings[i].kobo_fieldname)
					html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><b>' + record[excelHeadings[i].kobo_fieldname] + '</b><br>';
				}
				
			} else {
				//console.log('Not in table to screen: ', excelHeadings[i].kobo_fieldname)
			}


		}

	}

	return html;
}

function formatDateTime(date, format) {
	let months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];
	let newdate;

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
	
	if (format=='csv') {
		newdate = date.getDate() + '/' + (date.getMonth()+1) + '/' + date.getFullYear();
	} else if (format=='screen') {
		newdate = date.getDate() + '-' + months[date.getMonth()] + '-' + date.getFullYear();
	};

	return [newdate, time];
}

function formatDate(date, format) {
	//console.log(date, format);
	let months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];
	let date_parsed = new Date(parseInt(date.substr(0,4)), parseInt(date.substr(5,7))-1, parseInt(date.substr(8,10)));
	let newdate;

	if (format=='csv') {
		newdate = date_parsed.getDate() + '/' + date_parsed.getMonth() + '/' + date_parsed.getFullYear();
		//console.log(date, newdate)
	} else if (format=='screen') {
		newdate = date_parsed.getDate() + '-' + months[date_parsed.getMonth()] + '-' + date_parsed.getFullYear();
		//console.log(date, newdate)
	};

	return newdate;
}


function getTeamSpecs(key, record) {
	//console.log(key, record);
	for (var r in record) {
		if ((key.substr(0,29)=='team_went/burial/begin_group_') && (r.substr(0,29)=='team_went/burial/begin_group_')) {
			if ((r.substr(r.length - 13)=='activity_date') && (key.substr(key.length - 13)=='activity_date')) {
				//console.log('return ', record[r])
				return record[r];
			} else if ((r.substr(r.length - 17)=='time_of_departure') && (key.substr(key.length - 17)=='time_of_departure')) {
				//console.log('return ', record[r])
				return record[r].substr(0,8);
			} else if ((r.substr(r.length - 15)=='time_of_arrival') && (key.substr(key.length - 15)=='time_of_arrival')) {
				//console.log('return ', record[r])
				return record[r].substr(0,8);
			} else if ((r.substr(r.length - 10)=='swap_taken') && (key.substr(key.length - 10)=='swap_taken')) {
				//console.log('return ', record[r])
				return record[r];
			} else if ((r.substr(r.length - 11)=='disinfected') && (key.substr(key.length - 11)=='disinfected')) {
				//console.log('return ', record[r])
				return record[r];
			};
		}
	}
	//console.log('get TeamSpecs blank ', key, record)
	return blank; //specs;
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
	var output = field;
	if ((field == null) || (field == '')) {
		output = blank;
	} else if (typeof field == 'string') {
		/*var num_linebreaks = (field.match(/\n/g)||[]).length;
		if (num_linebreaks>0) {
			console.log(num_linebreaks, field);
			output = field.replace(/[\n]+/g, '. ');
			console.log(output)
		};*/
		output = field.replace(/[\n]+/g, '. ');  //remove carriage returns from string
		if (field.indexOf(',')!=-1) {
			//console.log(field);
			output = '"'+field+'"';
		} 

	} 
	return output;
}


//inputs list of optional fields to select from and row of data
//outputs [value, key] relating to the first valid field from the list of optional fields
function getFirstValidField(fields, row) {
	//console.log('in getFirstValidField: ', fields, row);
	var fields_list = fields.split('&&');
	//console.log(fields_list)
	
	var i = 0;
	while (i<=fields_list.length-1) {
		//console.log('field: ', fields_list[i], row[fields_list[i]]);
		if (row[fields_list[i]]!=null) {
			return [row[fields_list[i]],fields_list[i]];
		};
		i++
	};
	//console.log(fields,row, row[fields_list[0]], row[fields_list[1]])
	return [];	
}

//inputs list of all fields to select from and row of data
//outputs string with all valid fields concatenated
function getAllValidFields(fields, row) {
	//console.log(fields, row);
	var fields_list = fields.split('&&');
	var all_valid = '';
	//console.log(fields_list)
	
	var i = 0;
	while (i<=fields_list.length-1) {
		if (row[fields_list[i]]!=null) {
			all_valid += row[fields_list[i]];
		};
		i++
	};
	
	//check valididty of multiple fields:
	//if (row[fields_list[0]]!=null) {console.log('field 0: ', row[fields_list[0]])}
	//if (row[fields_list[1]]!=null) {console.log('field 1: ', row[fields_list[1]])}
	//if ((row[fields_list[0]]!=null) || (row[fields_list[1]]!=null)) {console.log('Multiple valid fields: ', all_valid)}
	
	if (all_valid.length==0) {all_valid = blank};
	return all_valid;
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
	switch(true) {
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

Date.prototype.isValid = function () {
    // An invalid date object returns NaN for getTime(), and NaN is the only object not strictly equal to itself
    return this.getTime() === this.getTime();
}; 

function msToTime(duration) {
    var milliseconds = parseInt((duration%1000)/100)
        , seconds = parseInt((duration/1000)%60)
        , minutes = parseInt((duration/(1000*60))%60)
        , hours = parseInt((duration/(1000*60*60))%24);

    hours = (hours < 10) ? "0" + hours : hours;
    minutes = (minutes < 10) ? "0" + minutes : minutes;
    seconds = (seconds < 10) ? "0" + seconds : seconds;

    return hours + ":" + minutes + ":" + seconds;
}

function getResponseTime(beg_date, beg_time, end_date, end_time) {
	var beg = new Date(beg_date+'T'+beg_time);
	var end = new Date(end_date+'T'+end_time);
	//console.log(beg, end, beg.isValid(), end.isValid());

	if (beg.isValid() && end.isValid()) {
		var milliseconds = end - beg;
		if (milliseconds >= 0) {
			var rtime = msToTime(milliseconds);
		} else {
			var rtime = blank
		}
	} else {
		var rtime = blank
	}	
	//console.log(rtime);
	return rtime;
}


function getDateTimeFromDatetime(datetime){
	//console.log('datetime input: ', datetime)

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
	//console.log('CHECK getDateTimeFromDatetime: ', datetime, ' => ', newDate);
	return newDate;
}


Date.prototype.addDays = function(days) {
    var date = new Date(this.valueOf());
    date.setDate(date.getDate() + days);
    return date;
}

function getEpiweekNum(datestring) {
	var date = new Date(datestring);
	var week_beg = new Date(2018,7,5);  //Sun 5th Aug 2018
	var weeknum = 0;

	//if input date is valid
	if (date.isValid()) {
		//while date is on or later than the beginning of the week
		while (week_beg <= date) {
			weeknum ++;		//increment week counter
			if (date < week_beg.addDays(7)) {   //if date is within the next week
				//console.log('return epiweek ', weeknum, date)
				return weeknum;
			}
			week_beg.setDate(week_beg.getDate()+7);
		}

	}
	
	return blank;
}

function getResultType(rec) {
	//console.log(rec)
	var result = 'X';

	if (rec['type'] == 'disinfection') {
		result = 'Désinfection seulement';

	} else if (!(rec.hasOwnProperty('team_went/burial/status'))) {
		result = 'No status field';
		console.log('No status field');
	} else {

		if (['secured_buried', 'secured_negative_sample', 'Succes'].indexOf(rec['team_went/burial/status']) != -1 ){
				result = 'Succes';

		} else if ((rec['team_went/burial/status'] == 'Incomplet') || (rec['team_went/burial/status'] == 'pending')){
			result = 'Incomplet';

		} else if ((rec['team_went/burial/status'] == 'other') || (rec['team_went/burial/status'] == 'autre')) {
			if (!(rec.hasOwnProperty('team_went/burial/reason'))) {
				result = 'Other - no reason field';   //happens frequently
				//console.log('Other - no reason field');
			} else if ((rec['team_went/burial/reason'] == '') || (rec['team_went/burial/reason'] == blank)) {
				result = 'Other - reason field blank'; 
				//console.log('Other - reason field blank');
			} else if (rec['team_went/burial/reason'] != '') {
				//console.log(rec['team_went/burial/status'], rec['team_went/burial/reason'])
				result = 'Échec';
			} else {
				console.log('Shouldn\'t be an output here');
			}
			
		} else if ((rec['team_went/burial/status'] == '') || (rec['team_went/burial/status'] == blank)) {
			console.log('!!! BLANK');
			if (rec['alert_new/group_response/action_taken&&group_response/action_taken']== 'sent_civil_protection') {
				result = 'Alerte envoyée à la protection civile';
			} else if (rec['alert_new/group_response/action_taken&&group_response/action_taken']== 'not_responded') {
				result = 'Échec';
			} else {
				result = 'X'
			}

		} else {
			result = 'Status field undefined';
			//console.log('Status field undefined: ', rec['team_went/burial/status']);
		}
	} 

	//Note: Cannot program the final logic dependant on the input of '1 day' because this has been manually input by someone

	//LOGIC by Alex:
	/* First, use field 'type' to filter out any disinfections as these don't go into the database
	Primary kobo field used is 'status'
		- 'secured_buried' = Succes
		- 'secured_negative_sample' = Succes
		- 'other' = probably Échec, but check the reason just to be sure
	Check 'reason' if populated (FYI this is a select multiple question, not free text)
	If 'status' is blank I will check 'action_taken'
		- 'sent_civil_protection' = Alerte envoyée à la protection civile
		- 'not_responded' = Échec
	Finally, to check whether the burial activity (successfully or not) happened on the same day as the alert or not I use the calculated field in column CK 'Time between pre alert and leaving', looking only at those records that record '1 day' i will change
		- 'Succes' = 'Alert d'hier complete'
		- 'Échec' = 'Attendant pas complete'*/

	//console.log('result: ', result)
	return result;
}


function getStatusType(result) {
	//console.log(result);
	var status = '';

	switch (result) {
		case 'Succes': status = 'Successful'; break;
		case 'Échec': status = 'Unsuccessful'; break;
		case 'En attente': status = 'Pending'; break;
		case 'Alerte d\'hier complétée': status = 'Successful'; break;
		case 'Attendant pas complété': status = 'Unsuccessful'; break;
		case 'Pas de réponse': status = 'Not Responded'; break;
		case 'Alerte envoyée à la protection civile': status = 'Alert Sent to Protection Civile'; break;
		default: status = 'Result type not recognised';
	}
	return status;
}


function sameDay(d1, d2) {
  //console.log(d1, d2, typeof(d1), typeof(d2))
  d1 = new Date(d1);
  return d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate();
}

var yesterday = function(date1) {
   var dt = new Date(date1);
   return new Date((dt.setDate(dt.getDate()-1)));
};


function exportData(fileType,option) {
	//console.log(fileType, option)  //option = 'selected', 'all_today', 'all_yesterday'
	var now = new Date();
	var now_fname = now.getFullYear().toString()+(now.getMonth()+1).toString()+now.getDate().toString()+'_'+now.getHours().toString()+now.getMinutes().toString()+now.getSeconds().toString();
	var filename;
	var rows = [];
	var row = [];
	var has_rows = false;
	
	//console.log(headings);

	switch(option) {
		/*case 'selected': 		filename = 'SDB_data_all__' + now_fname; break;
		case 'all_today': 		filename = 'SDB_data_today__' + now_fname; break;
		case 'all_yesterday': 	filename = 'SDB_data_yesterday__' + now_fname; break;
		default: filename = 'SDB_data_' + now_fname + '.xls'; */
		case 'dshbrd_view': 		filename = 'SDB_donnees_dshbrd__' + now_fname; break;
		case 'tbl_view': 		filename = 'SDB_donnees_tbl__' + now_fname; break;
		default: filename = 'SDB_donnees_' + now_fname + '.xls'; 
	}
	if (fileType=='csv') {
		filename = filename + '.csv';
    } else if (fileType=='xlsx') {
    	filename = filename + '.xlsx';
    }
	
	

	if (option == 'dshbrd_view') {

		const headings = excelHeadings.map(x => x['excel_heading']);
		rows.push(headings)

		//console.log('currentData: ', currentData)
		//currentData = reverseSortByKey(currentData, 'alert_new/datetime/date_alert&&datetime/date_alert&&start');
		currentData = reverseSortByKey(currentData, 'date_submitted');
		//currentData = reverseSortByKey(currentData, 'alert_received');

    	for (var i = 0; i <= currentData.length-1; i++) {
    		//console.log(i, currentData[i])
 	
    		row = []
			var endtime = formatDateTime(currentData[i]['end'],'csv')[0];
			var starttime = formatDateTime(currentData[i]['alert_received'],'csv')[0];
				
	        for (var j = 0; j < excelHeadings.length; j++) {
	        	
	        	if (excelHeadings[j].excel_heading!='') {  //temporary hackfix - because github keeps adding blank row to end of csv
			
		        	if (excelHeadings[j].processing_options.substr(0,5)=='calc-') {
		        		//console.log(excelHeadings[j].processing_options, data[i][excelHeadings[j].processing_options]);
		        		row.push(currentData[i][excelHeadings[j].processing_options]);
		        	} else if (excelHeadings[j].excel_heading=='Fin de reponse') {
		        		row.push(endtime);
		        	} else if (excelHeadings[j].excel_heading=='Alert received') {
		        		row.push(starttime);
		        	} else {
		        		row.push(currentData[i][excelHeadings[j].kobo_fieldname])
		        	}
		        }
	            
	        }
	        has_rows = true;
	        if (fileType=='csv') {
				rows.push(row.join(","));
		    } else if (fileType=='xlsx') {
		    	rows.push(row);
		    }

	    }

	    if (!(has_rows)) {
			rows.push(['Aucune donnée n\'a été sélectionnée'])
		}


    } else if (option == 'tbl_view') {

    	//tableToExcel('#tableSDB', 'testexport')
    	//downloadTbl();

    	//console.log('currentData: ', currentData)
		//currentData = reverseSortByKey(currentData, 'alert_new/datetime/date_alert&&datetime/date_alert&&start');
		currentData = reverseSortByKey(currentData, 'date_submitted');
		//currentData = reverseSortByKey(currentData, 'alert_received');


		for (var mainHead in mainHeadings) {
			row.push(mainHeadings[mainHead]); 
		}
		rows.push(row);

    	for (var i = 0; i <= currentData.length-1; i++) {
    		//console.log(i, currentData[i])
 	
    		row = []
			var endtime = formatDateTime(currentData[i]['end'],'csv')[0];
			var starttime = formatDateTime(currentData[i]['alert_received'],'csv')[0];
			
			for (var mainHead in mainHeadings) {
				var html_row = getSubHeadingHtml(mainHead, currentData[i]);
				var row_str = html_row.replace(/<[^>]*>/g, "");
				//row_str = 'xxx\r' + row_str;
				row.push(row_str);
			}
			rows.push(row)

	        /*for (var j = 0; j < excelHeadings.length; j++) {
	        	
	        	if (excelHeadings[j].excel_heading!='') {  //temporary hackfix - because github keeps adding blank row to end of csv
			
		        	if (excelHeadings[j].processing_options.substr(0,5)=='calc-') {
		        		//console.log(excelHeadings[j].processing_options, data[i][excelHeadings[j].processing_options]);
		        		row.push(currentData[i][excelHeadings[j].processing_options]);
		        	} else if (excelHeadings[j].excel_heading=='Fin de reponse') {
		        		row.push(endtime);
		        	} else {
		        		row.push(currentData[i][excelHeadings[j].kobo_fieldname])
		        	}
		        }
	            
	        }*/
	        //row.push('XXX')
	        has_rows = true;
	        if (fileType=='csv') {
				rows.push(row.join(","));
		    } else if (fileType=='xlsx') {
		    	rows.push(row);
		    }

	    }

	   /* if (!(has_rows)) {
			rows.push(['Aucune donnée n\'a été sélectionnée'])
		}*/

    }


    /*else {

    	data = reverseSortByKey(data, 'alert_new/datetime/date_alert&&datetime/date_alert&&start');

    	for (var i = 0; i <= data.length-1; i++) {
    		//console.log(i, data[i])

    		if (((option == 'all_today') && (sameDay(data[i]['team_went/burial/begin_group_xxxxxxxx/activity_date'],now))) || ((option == 'all_yesterday') && (sameDay(data[i]['team_went/burial/begin_group_xxxxxxxx/activity_date'], yesterday(now))))) {

				row = []
				var endtime = formatDateTime(data[i]['end'],'csv')[0];
				
		        for (var j = 0; j < excelHeadings.length; j++) {
		        	
		        	if (excelHeadings[j].excel_heading!='') {  //temporary hackfix - because github keeps adding blank row to end of csv
				
			        	if (excelHeadings[j].processing_options.substr(0,5)=='calc-') {
			        		//console.log(excelHeadings[j].processing_options, data[i][excelHeadings[j].processing_options]);
			        		row.push(data[i][excelHeadings[j].processing_options]);
			        	} else if (excelHeadings[j].excel_heading=='Fin de reponse') {
			        		row.push(endtime);
			        	} else {
			        		row.push(data[i][excelHeadings[j].kobo_fieldname])
			        	}
			        }
		            
		        }
		        has_rows = true;
		        if (fileType=='csv') {
					rows.push(row.join(","));
			    } else if (fileType=='xlsx') {
			    	rows.push(row);
			    }

			}

    	}*/

    	//if (!(has_rows)) {
    		/*if (option=='all_today') {
				rows.push(['Aucune donnée disponible pour aujourd\'hui'])
			} else if (option=='all_yesterday') {
				rows.push(['Aucune donnée disponible pour hier'])
			}*/
			//rows.push(['Aucune donnée disponible'])
		//}

    //}

    if (fileType=='csv') {
		download_csv(rows.join("\n"), filename);
    } else if (fileType=='xlsx') {
    	//console.log(rows,filename)
    	download_xlsx(rows, filename);
    	console.log('Downloaded: ', filename);
    }
	

}

/*var tableToExcel = (function () {
        var uri = 'data:application/vnd.ms-excel;base64,',
            template = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40"><head><!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet><x:Name>{worksheet}</x:Name><x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions></x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]--></head><body><table>{table}</table></body></html>',
            base64 = function (s) {
                return window.btoa(unescape(encodeURIComponent(s)))
            }, format = function (s, c) {
                return s.replace(/{(\w+)}/g, function (m, p) {
                    return c[p];
                })
            }
        
        return function (table, name, filename) {
        	console.log(table, name, filename)
            if (!table.nodeType) table = document.getElementById(table)
            var ctx = {
                worksheet: name || 'Worksheet',
                table: table.innerHTML
            }

            document.getElementById("dlink").href = uri + base64(format(template, ctx));
            document.getElementById("dlink").download = filename;
            document.getElementById("dlink").traget = "_blank";
            document.getElementById("dlink").click();

        }
    })();

function downloadTbl(){
    $(document).find('tfoot').remove();
    //var name = document.getElementById("name").innerHTML;
    var name = 'heidi'
    tableToExcel('tableSDB', 'Sheet 1', name+'.xls')
    //setTimeout("window.location.reload()",0.0000001);

}*/


function download_csv(csv, filename) {
    var csvFile;
    var downloadLink;

    csvFile = new Blob(["\uFEFF", csv], {type: "text/csv;charset=utf-8"});
    //csvFile = new Blob(["\uFEFF", csv], {type: "application/vnd.ms-excel;charset=utf-8"});
    downloadLink = document.createElement("a");   //download link
    downloadLink.download = filename;
    downloadLink.href = window.URL.createObjectURL(csvFile);  //create link to the file
    downloadLink.style.display = "none";  //make sure link isn't displayed
    document.body.appendChild(downloadLink);   //add link to DOM
    downloadLink.click();
}



function download_xlsx(rows, filename) {
	var sheetName = 'Data';

    var wb = XLSX.utils.book_new();
    wb.SheetNames.push(sheetName);
    var ws = XLSX.utils.aoa_to_sheet(rows);
    wb.Sheets[sheetName] = ws;
    var wbout = XLSX.write(wb, {bookType:'xlsx',  type: 'binary'});
    function s2ab(s) {
        var buf = new ArrayBuffer(s.length);
        var view = new Uint8Array(buf);
        for (var i=0; i<s.length; i++) view[i] = s.charCodeAt(i) & 0xFF;
        return buf;        
    }
        
    saveAs(new Blob([s2ab(wbout)],{type:"application/octet-stream"}), filename);
       
}

function deepCopyDate(date_in) {
	return new Date(date_in.getFullYear(), date_in.getMonth(), date_in.getDate());
}


function createCharts(data) {
	var cf = crossfilter(data);
	var teamChart = dc.rowChart("#dc-team-chart");
	var teamDim = cf.dimension(function (d) { return d['team'] });
	var teamGroup = teamDim.group();
	var zoneChart = dc.rowChart("#dc-zone-chart");
	var zoneDim = cf.dimension(function (d) {
		if (['', ' '].includes(d['group_location/collection_zone'])) {
			return 'Zone pas défini';
		} else {
			return d['group_location/collection_zone']
		}; 
	});
	//var zoneDim = cf.dimension(function (d) {if (d['group_location/collection_zone']!=' ') {return d['group_location/collection_zone']} });
	var zoneGroup = zoneDim.group();
	var dateChart = dc.compositeChart("#dc-date-chart");
	var dateDim = cf.dimension(function (d) {if (d['alert_received']!='') {/*console.log(d['alert_received']);*/ return d['alert_received'] }});
	var dateGroup = dateDim.group();
	var dateExtent = d3.extent(data.map(x=>x['alert_received']));
	var resultChart = dc.pieChart("#dc-result-chart");
	var resultDim = cf.dimension(function (d) { return d['calc-result_type'] });
	var resultGroup = resultDim.group();
	
	var dateExtent = d3.extent(data.reduce(function(result, d) {
	    if (d['alert_received'] != "") {
	      result.push(d['alert_received']);
	    }
	    return result;
	}, []));
	//console.log('dateExtent: ', dateExtent);

	var dateExtentPlus = []; 
	dateExtentPlus[0] = deepCopyDate(dateExtent[0])
	dateExtentPlus[1] = deepCopyDate(dateExtent[1])
	//dateExtentPlus[0].setHours(dateExtentPlus[0].getHours());
	dateExtentPlus[1].setHours(dateExtentPlus[1].getHours()+23);
	//console.log('dateExtent: ', dateExtent);
	//console.log('dateExtent+: ', dateExtentPlus);
	$('#dates_selected').html('<i>' + formatDateTime(dateExtent[0],'screen')[0] + ' - ' + formatDateTime(dateExtent[1],'screen')[0] + '</i>')


	//ROW CHART - TEAMS
  	teamChart.width(150)
	    .height(200)
	    .margins({top: 0, left: 2, right: 2, bottom: 40})
	    .dimension(teamDim)
	    .group(teamGroup)
	    .colors(['steelblue'])
	    //.colors(d3.scaleOrdinal(d3.schemeCategory10))
	    .label(function (d){
	    	//console.log(d);
	        return d.key;
	    })
	    .title(function(d){return d.key + ': '+ d.value;})
	    .ordering(function(d) { return - d.value })
	    .elasticX(true)
	    .xAxis().ticks(4);

	//ROW CHART - TEAMS
  	zoneChart.width(150)
	    .height(200)
	    .margins({top: 0, left: 2, right: 0, bottom: 40})
	    .dimension(zoneDim)
	    .group(zoneGroup)
	    .colors(['#a0c960'])
	    //.colors(d3.scaleOrdinal(d3.schemeCategory10))
	    .label(function (d){
	    	//console.log(d);
	        return d.key;
	    })
	    .title(function(d){return d.key + ': '+ d.value;})
	    .ordering(function(d) { return - d.value })
	    .elasticX(true)
	    .xAxis().ticks(4);

	//TIME SERIES CHART - with handles
	dateChart
		.width(360)
	    .height(200)
	    .margins({top: 10, left: 30, right: 8, bottom: 30})
	    .x(d3.scaleTime().domain(dateExtentPlus))
	    .yAxisLabel("Nombre de Réponses")
	    .dimension(dateDim)
	    .group(dateGroup)
	    .compose([
	        dc.barChart(dateChart)
	            .dimension(dateDim)
	            .group(dateGroup)
	            .valueAccessor(function (d) {return d.value; })
	            .ordinalColors(['#c58cc5'])
	    ]);

	//PIE CHART - RESULTS
	resultChart
	    .width(180)
	    .height(200)
	    .cx(80)
	    .cy(60)
	    .radius(60)
	    .innerRadius(14)
	    .ordinalColors(['#66c2a5','#fc8d62','#8da0cb','#e78ac3','#a6d854','#ffd92f','#e5c494','#b3b3b3'])
	    .dimension(resultDim)
	    .group(resultGroup) 
	    .renderLabel(false)
	    /*.label(function (d) {  
	        var perc = Math.round((d.value/currentData.length)*100);
	        console.log(d.value, currentData.length, perc + '%');
	        return perc + '%';
	    })*/
	    //.legend(dc.legend().x(130).y(45).itemHeight(13).gap(2))
	    .legend(dc.legend().x(30).y(126).itemHeight(13).gap(2))
		.on('renderlet', function(chart) { 
			chart.selectAll('g.pie-slice') 
				.on('mouseover', function(d) { 
					chart.select('.pie-tooltip').text(dc.utils.printSingleValue(Math.round((d.endAngle - d.startAngle) / (2*Math.PI) * 100)) + '%'); //d.data.value); 
				}) 
				.on('mouseout', function(d) { 
					chart.select('.pie-tooltip').text(''); 
				}); 
		});


	dc.renderAll();

    teamChart.svg()
        .append("text")
        //.attr("class", "x-axis-label")
        .attr("text-anchor", "middle")
        .attr("font-size", "12px")
        .attr("x", 70)
        .attr("y", 196)
        .text('Nombre de Réponses');


    teamChart.on("filtered", function (chart) {
         currentData = teamDim.top(Infinity)
         createSummarySDBTable(currentData);
    })

    zoneChart.svg()
        .append("text")
        //.attr("class", "x-axis-label")
        .attr("text-anchor", "middle")
        .attr("font-size", "12px")
        .attr("x", 70)
        .attr("y", 196)
        .text('Nombre de Réponses');


    dateChart.on("filtered", function (chart) {
    	var filters = chart.filters();
	    if (filters.length) {
	        var range = filters[0];
	        //console.log('filtered date range:', range[0], range[1]);
	        let minDate = deepCopyDate(range[0]);
	        if (!(sameDay(range[0],dateExtent[0]))) {  
	        	//minDate.setHours(minDate.getHours()+24);
	        	minDate.setDate(minDate.getDate()+1);
	        };
	        if (sameDay(minDate, range[1])) {
	        	$('#dates_selected').html('<i>' + formatDateTime(minDate,'screen')[0] + '</i>');
	        } else {
	        	$('#dates_selected').html('<i>' + formatDateTime(minDate,'screen')[0] + ' - ' + formatDateTime(range[1],'screen')[0] + '</i>');
	        }	        
	    } else {
	    	$('#dates_selected').html('<i>' + formatDateTime(dateExtent[0],'screen')[0] + ' - ' + formatDateTime(dateExtent[1],'screen')[0] + '</i>')
	        //console.log('No filters (',dateExtent[0],dateExtent[1],')');
	    };
    	currentData = dateDim.top(Infinity);
        createSummarySDBTable(currentData);
    })


    resultChart.on("filtered", function (chart) {
    	currentData = resultDim.top(Infinity)
        createSummarySDBTable(currentData);
    })
	

}




// Get SDB/EDS data from KoBo, get headings data from CSV
$(document).ready(function () {
	var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/273933?format=jsonp',
    	dataType: 'jsonp',
    });

    var d2 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_excelHeadings.csv',
    	dataType: 'text'
    });

    $.when(d1, d2).then(function (a1,a2) {
        console.log('Ajax calls succeedeed');
        //console.log(a1[0],a2);
        excelHeadings = processHeadings(a2[0]);
        //console.log('excel headings: ', excelHeadings);
        //koboFields = getKoboFields(a1[0]);
        data = processKoboSDBdata(a1[0]);
        currentData = data;
        createCharts(data);
        createSummarySDBTable(data);

    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        var x2 = d2;

        if (x1.readyState != 4) {
            x1.abort();
        };
        if (x2.readyState != 4) {
            x2.abort();
        };
        alert("Data request failed");
        console.log('Ajax request failed');
    });

});
