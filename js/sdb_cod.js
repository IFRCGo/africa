"use strict";

//**************************************************************************************************//
// BRC Maps Team - SIMS DRC Ebola response
// Sept-Oct 2018
//
// NOTES:
// 1. In cfg_subHeadings.csv:
//    - order counts - i.e. calculate fields must come after the fields that they are based on
//		 - perhaps all calculate fields should be at the bottom of the file?
// 	  - for team specs - replace team characters with 'xxxxxxxx' in config file - this can then match
//		 any teams defined
//
//**************************************************************************************************//


let koboFields, excelHeadings, data;

let blank = ' ';

let mainHeadings = {
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

function getKoboFields(records) { 		//reads all fieldnames from kobo data
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
}; 

/**/

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
	
	//var kobo_fieldnames = getKoboFieldnames();
	//console.log('Kobo fieldnames: ', kobo_fieldnames);

	//create new dataset from sdbData using kobo_fieldnames as keys
	sdbData.forEach(function(record,i){
		//console.log(record,i)
		temp = {};
		//circumstancesOfFailure = [];


		//FIRST ADD KOBO FIELDS NEEDED FOR PROCESSING ONLY, NOT FOR OUTPUT
		temp['team_went/burial/status'] = record['team_went/burial/status'];

		//for each subHeading (corresponds to each row defined in cfg_subHeadings.csv - i.e. all kobo fieldnames and calculated fields)
		for (var h in excelHeadings) {
			//console.log(h, excelHeadings[h])
			//console.log(subHeadings[h].mainheading_prefix)
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
					//console.log('first_valid_field: ', first_valid_field);
					
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
						case 'response_time': temp[new_keyname] = getResponseTime(temp['alert_new/datetime/date_alert&&datetime/date_alert'], temp['alert_new/datetime/time_pre_alert&&datetime/time_pre_alert'],temp['team_went/burial/begin_group_xxxxxxxx/activity_date'],temp['team_went/burial/begin_group_xxxxxxxx/time_of_departure']); break;
						case 'epiweek_num': temp[new_keyname] = getEpiweekNum(temp['alert_new/datetime/date_alert&&datetime/date_alert']); break;
						case 'result_type': var result = getResultType(temp);
												temp[new_keyname] = result; break;
						case 'status_type': temp[new_keyname] = getStatusType(temp['calc-result_type']); break;
						default: temp[new_keyname] = '';
					}

				//if fieldname contains 'xxxxxxxx' to represent team code
				} else if (excelHeadings[h].kobo_fieldname.indexOf('xxxxxxxx') != -1) {
					kobo_fieldused = 'NA';
					new_keyname = excelHeadings[h].kobo_fieldname;
					temp[new_keyname] = getTeamSpecs(new_keyname, record);

				//if fieldname corresponds to circumstances of failure 
				} else if (excelHeadings[h].processing_options == 'yn') {  
					//console.log(subHeadings[h].kobo_fieldname);
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
						//new_keyname = subHeadings[h].kobo_fieldname;
						new_keyname = kobo_fieldused;
						temp[new_keyname] = record[new_keyname];     		//copy original key and value over to temp object
						//console.log(new_keyname, temp[new_keyname], typeof(temp[new_keyname]));
					} catch(err) {
				    	console.log('Error processing SDB data: ', err)
				        return err
				    }
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

		//console.log('temp: ', temp);
		processedData.push(temp);
	});

	//order data by date (once date is parsed)
	processedData = reverseSortByKey(processedData, 'alert_new/datetime/date_alert&&datetime/date_alert');

	console.log('processedData: ', processedData);
	return processedData;
}

function createSummarySDBTable(sdbData) {
	var html = "";
	var sdbHtml = "";

	//write table headings
	html += '<tr bgcolor="#cfdff9">';
	for (var mainHead in mainHeadings) {
		html += '<th>' + mainHeadings[mainHead] + '</th>'; 
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

			if (excelHeadings[i]['kobo_fieldname'] == 'team_went/burial/begin_group_xxxxxxxx/activity_date') {
				//console.log('return ', record[r])
				html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br><b>' + formatDate(record[excelHeadings[i].kobo_fieldname],'screen') + '</b><br>';


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
						if (excelHeadings[k].processing_options.substr(0,4) == excelHeadings[i].processing_options.substr(0,4)) {
							if (record[excelHeadings[k].kobo_fieldname] != blank) {
								yn_all_empty = false;
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
				} else if (record[excelHeadings[i].kobo_fieldname] instanceof Date) {
					//console.log(excelHeadings[i].kobo_fieldname)
					html += '<i>' + excelHeadings[i]['excel_heading'] + ': </i><br><b>' + formatDateTime(record[excelHeadings[i].kobo_fieldname],"screen")[0] + '<br>' + formatDateTime(record[excelHeadings[i].kobo_fieldname],"screen")[1] + '</b><br>';

				} else {
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
	//console.log(date, format);
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
	let date_parsed = new Date(parseInt(date.substr(0,4)), parseInt(date.substr(5,7)), parseInt(date.substr(8,10)));
	let newdate;

	if (format=='csv') {
		newdate = date_parsed.getDate() + '/' + date_parsed.getMonth()-1 + '/' + date_parsed.getFullYear();
		console.log('for csv: ', newdate)
	} else if (format=='screen') {
		newdate = date_parsed.getDate() + '-' + months[date_parsed.getMonth()-1] + '-' + date_parsed.getFullYear();
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

	if (rec['type'] != 'disinfection') {
		//console.log(rec['team_went/burial/status'])
		if ((rec['team_went/burial/status'] == 'secured_buried') || (rec['team_went/burial/status'] == 'secured_negative_sample')) {
			result = 'Succes';
		} else if (rec['team_went/burial/status'] == 'other') {
			if (rec['team_went/burial/reason'] != '') {
				result = 'Échec';
			} 
		} else if ((rec['team_went/burial/status'] == '') || (rec['team_went/burial/status'] == blank)) {
			if (rec['alert_new/group_response/action_taken&&group_response/action_taken']== 'sent_civil_protection') {
				result = 'Alerte envoyée à la protection civile';
			} else if (rec['alert_new/group_response/action_taken&&group_response/action_taken']== 'not_responded') {
				result = 'Échec';
			};
		}
	}
	//Note: Cannot program the final logic dependant on the input of '1 day' because this has been manually input by someone

	//LOGIC by Alex:
	/* First, use field 'type' to filter out any disinfections as these don't go into the database
	primary kobo field used is 'status'
		- 'secured_buried' = Succes
		- 'secured_negative_sample' = Succes
		- 'other' = probably Échec, but i check the reason just to be sure
	check 'reason' if populated (FYI this is a select multiple question, not free text)
	if 'status' is blank I will check 'action_taken'
		- 'sent_civil_protection' = Alerte envoyée à la protection civile
		- 'not_responded' = Échec
	finally, to check whether the burial activity (successfully or not) happened on the same day as the alert or not I use the calculated field in column CK 'Time between pre alert and leaving', looking only at those records that record '1 day' i will change
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



function export_data_to_csv() {
	//console.log(data)
	var now = new Date();
	var now_fname = now.getFullYear().toString()+(now.getMonth()+1).toString()+now.getDate().toString()+'_'+now.getHours().toString()+now.getMinutes().toString()+now.getSeconds().toString();
	var filename = 'SDB_data_' + now_fname + '.csv';
	var csv = [];
	var row = [];
	const headings = excelHeadings.map(x => x['excel_heading']);
	//console.log(headings);

	data = reverseSortByKey(data, 'alert_new/datetime/date_alert&&datetime/date_alert');

	csv.push(headings)
	
    for (var i = 0; i < data.length-1; i++) {
    	//console.log(data[i])
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
        
		csv.push(row.join(","));		
	}

    // Download CSV
    download_csv(csv.join("\n"), filename);
}



function download_csv(csv, filename) {
    var csvFile;
    var downloadLink;

    csvFile = new Blob(["\uFEFF", csv], {type: "text/csv;charset=utf-8"});
    downloadLink = document.createElement("a");   //download link
    downloadLink.download = filename;
    downloadLink.href = window.URL.createObjectURL(csvFile);  //create link to the file
    downloadLink.style.display = "none";  //make sure link isn't displayed
    document.body.appendChild(downloadLink);   //add link to DOM
    downloadLink.click();
}



// Get SDB/EDS data from KoBo, get headings data from CSV
$(document).ready(function () {
	var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/273933?format=jsonp',
    	dataType: 'jsonp',
    });

    /*var d2 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_mainHeadings.csv',
    	dataType: 'text'
    });*/

    /*var d3 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_subHeadings.csv',
    	dataType: 'text'
    });*/

    var d4 = $.ajax({
        type: 'GET',
		url: './sdb_config/cfg_excelHeadings.csv',
    	dataType: 'text'
    });

    $.when(d1, d4).then(function (a1,a4) {
        console.log('Ajax calls succeedeed');
        //console.log(a1[0],a2);
        //createHorizontalSDBTable(a0.reverse());
        
        /*mainHeadings = processHeadings(a2[0]);
        console.log('main headings: ', mainHeadings);*/
        /*subHeadings = processHeadings(a3[0]);
        console.log('sub headings: ', subHeadings);*/
        excelHeadings = processHeadings(a4[0]);
        console.log('excel headings: ', excelHeadings);
        koboFields = getKoboFields(a1[0]);
        data = processKoboSDBdata(a1[0]);
        createSummarySDBTable(data);

    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        //var x2 = d2;
        //var x3 = d3;
        var x4 = d4;
        if (x1.readyState != 4) {
            x1.abort();
        };
        /*if (x2.readyState != 4) {
            x2.abort();
        };*/
        /*if (x3.readyState != 4) {
            x3.abort();
        };*/
        if (x4.readyState != 4) {
            x4.abort();
        };
        alert("Data request failed");
        console.log('Ajax request failed');
    });

});
