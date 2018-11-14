"use strict";

//**************************************************************************************************//
// BRC Maps Team - SIMS DRC Ebola response
// Oct-Nov 2018
//
// Task list:
// - make background color of cells depend on percentages?
//**************************************************************************************************//

//let all_data;
//let all_fields = ['Aire de Santé','Histoire','Index de mot cle', 'Mot cle 1','NOMBRE DE FOIS','Numero','Semaine','Source','Type','Zone de Sante','date','mot cle 1'];

let unique_keywords = []; 
//let keyword_matches = {"Ebola pas réel": "Ebola n'est pas réel"}
let unique_zones = [];
let unique_weeks = [];
let unique_rumours = [];
let rumour_distances;  //array of [keyword1, keyword2, num_matches]
let num_links;
let all_keyword_counts = {};
let filt_keyword_counts = {};
let type_constraint = false;
//let type_value = 'Rumeur/croyance/observation';  //only required if type_constraint=true



//Parse CSV file - creates array of objects
//Split text at each new line, split each line at comma
function readRumourDataFromCSV(csv) {

    try {   
        var data = {}		
        var records = []	
        var lines = csv.split(/\r\n|\r|\n/)   //splits csv data at each new line
        var columns = lines[0].split(',')      //creates columns by splitting first line of csv

        //console.log(lines)		//array of all lines - each line is string in "" and cells with , also enclosed in ""
        //console.log(columns)    //column headings    

        for (var l=1; l<=lines.length-1; l++) {           
            //var cellval = lines[l].split(',');  
            //var cellval = lines[l].match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g);
            var cellval = lines[l].match(/"(.*?)"(.*?),|(.*?),|(.*?)$/g); 
            for (var cell in cellval) {
            	if (cellval[cell].substr(-1) == ',') {  //if last char is a ',' then remove it
            		cellval[cell] = cellval[cell].substr(0, cellval[cell].length-1);   
            	}
            }
            
            //build object based on column headers
            for (var cell in columns) {
                data[columns[cell]] = cellval[cell]    
                //console.log(cell,data[columns[cell]])
            }

            //include record in data if correct type 
			if ((type_constraint==false) || ((type_constraint==true) && (record['type']==type_value))) {

				if (record['mot_cle'] != ""){	 //include record in data if keyword (i.e. mot_cle) not empty
		     
		        	records.push(data);
	            	
	            	//Check case:
		        	let capKeys = unique_keywords.map(k => k.toUpperCase());
		        	if (capKeys.indexOf(data['mot_cle'].toUpperCase()) == -1) {   //if keyword not already in (capitalized) unique_keywords list 
		        		unique_keywords.push(data['mot_cle']);
		        	}

					data = {};

				};

	        };
   
        }
        //console.log(records)
        return records
    } catch(err){
    	console.log('Error processing data: ', err)
        return err
    }
}


function readRumourDataFromGS(gsData) {
	console.log('googlesheet data: ', gsData);
	var req_data = [];
	var record = {};	
	var all_zones = [];
	var all_weeks = [];

    gsData.forEach(function (a) {
    	record = {};
        record['hist'] = a.gsx$histoire.$t;
        record['mot_cle'] = a.gsx$motclé.$t;
        record['aire'] = a.gsx$airedesanté.$t;
		record['zone'] = a.gsx$zonedesante.$t;
		record['date'] = a.gsx$date.$t;
		record['type'] = a.gsx$type.$t;
		record['week'] = a.gsx$week.$t;

		//include record in data if correct type 
		if ((type_constraint==false) || ((type_constraint==true) && (record['type']==type_value))) {

			if (record['mot_cle'] != ""){	 //include record in data if keyword (i.e. mot_cle) not empty
	        	/*if (record['mot_cle'] in keyword_matches) {
	        		//console.log("Found match: ", record['mot_cle'])
	        		record['mot_cle'] = keyword_matches[record['mot_cle']];
	        	}*/
	        	req_data.push(record);
	        	//Check case:
	        	let capKeys = unique_keywords.map(k => k.toUpperCase());
	        	if (capKeys.indexOf(record['mot_cle'].toUpperCase()) == -1) {   //if keyword not already in (capitalized) unique_keywords list 
	        		unique_keywords.push(record['mot_cle']);
	        	};
	        	all_zones.push(record['zone']);
	        	all_weeks.push(record['week']);
	        };

	    };

    });


    unique_zones = all_zones.filter(onlyUnique).filter(z => z!='');
    unique_weeks = all_weeks.filter(onlyUnique); //.map(w => parseInt(w));

    console.log('Unique keywords: ', unique_keywords);
	//console.log('Data required by program: ', req_data);
	console.log('Unique zones: ', unique_zones);
	console.log('Unique weeks: ', unique_weeks);
	return req_data;
    
}


function onlyUnique(value, index, self) { 
    return self.indexOf(value) === index;
}


// input date could be in multiple date formats: e.g. 2018-10-30, 19/10/2018
// output in date format
function setDateFormat(date_in) {  
	//console.log(date_in);

	if (date_in.indexOf('-')!=-1) {  //e.g. 2018-30-10
		var date_out = new Date(parseInt(date_in.split('-')[0]), parseInt(date_in.split('-')[2])-1, parseInt(date_in.split('-')[1]));	
	/*
	} else if (date_in.indexOf('/')!=-1) { //European format e.g. 19/10/2018
		var date_out = new Date(parseInt(date_in.split('/')[2]), parseInt(date_in.split('/')[1])-1, parseInt(date_in.split('/')[0]));	
	*/
	} else if (date_in.indexOf('/')!=-1) { //US format e.g. 10/19/2018
		var date_out = new Date(parseInt(date_in.split('/')[2]), parseInt(date_in.split('/')[0])-1, parseInt(date_in.split('/')[1]));	
	} else {
		console.log('DATE NOT FOUND: ', date_in);
		var date_out = 'DATE NOT FOUND'
	};

	//CONSOLE LOG DATE ERRORS
	if (((date_out.getMonth() <= 6) && (date_out.getFullYear()==2018)) || (date_out.getFullYear() < 2018)) {  //flag any date up to end of July 2018
		console.log('DATE ERROR? - too early: ', date_in, date_out)
	} else if (date_out > new Date()) {
		console.log('DATE ERROR? - in the future: ', date_in, date_out)
	}
	//console.log('setDateFormat: ', date_in, date_out);

	return date_out;
}


function displayDate(date_in) {
	let months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];	
	try {
		var date_out = date_in.getDate() + '-' + months[date_in.getMonth()] + '-' + date_in.getFullYear();
	} catch {
		var date_out = '';
	}
	
	//console.log('displayDate: ', date_out);
	return date_out;
}


function processRumourData(data) {
	console.log('Process rumour data: ', data.length, ' records')
	let all_dates = [];
	let temp; 
	let rumour_match;
	let count_mult_keywords=0;
	var temp_date;

	for (var word in unique_keywords) {
		all_keyword_counts[unique_keywords[word]] = 0
	};
	//console.log(all_keyword_counts);
	
	//match rumours and create new dataset of unique rumours with multiple keywords
	for (var i=0; i<=data.length-1; i++) {
		
		rumour_match = false;

		//ensure all dates consistent format
		temp_date = setDateFormat(data[i]['date']);
		data[i]['date'] = temp_date;

		for (var j=0; j<=unique_rumours.length-1; j++) {  //loop through list of unique rumours

			if (isFieldsMatch(data[i],unique_rumours[j])) {     //if matching rumour already exists...

				if (unique_rumours[j]['keywords'].length==1) {	//if this rumour now has a 2nd match, count it (for output only)
					count_mult_keywords++;
				}	
				
				//console.log(unique_rumours[j], data[i]['mot_cle'])
				if (unique_rumours[j]['keywords'].indexOf(data[i]['mot_cle']) == -1) {  //...and doesn't already contain keyword
					unique_rumours[j]['keywords'].push(data[i]['mot_cle']);  //then add keyword to it

					if ((unique_keywords.indexOf(data[i]['mot_cle'])) == -1) {
						console.log('! KEYWORD NOT IN LIST: ', data[i]['mot_cle']);
					} else {
						//console.log('xxx',i,j)
						all_keyword_counts[data[i]['mot_cle']]++;
					}
					//console.log('Matched, new keyword ', i,j)
				} else {								  //if it already contains keyword...
					//console.log('Matched, keyword already exists: ', data[i])	  //...its a true duplicate so flag this
				}
				rumour_match = true;
				break;
			}
		};

		if (!(rumour_match)) {  //if no matching rumour was found, create a new unique one
			temp = {};
			temp['date'] = data[i]['date'];
			temp['zone'] = data[i]['zone'];
			temp['aire'] = data[i]['aire'];
			temp['hist'] = data[i]['hist'];
			temp['week'] = data[i]['week'];
			temp['keywords'] = [];
			temp['keywords'].push(data[i]['mot_cle']);
			if ((unique_keywords.indexOf(data[i]['mot_cle'])) == -1) {
				console.log('! KEYWORD NOT IN LIST: ', data[i]['mot_cle']);
			} else {
				//console.log('yyy',i,j)
				all_keyword_counts[data[i]['mot_cle']]++;
			};

					
			unique_rumours.push(temp);
			//console.log(unique_rumours)
		};
		
	}
	//exportData(unique_rumours);
	console.log('Unique rumours: ', unique_rumours.length, unique_rumours);
	//console.log('Number of rumours with multiple keywords: ', count_mult_keywords);
	//console.log('Keyword counts: ', all_keyword_counts);


	//get date extent  
	for (let i=0; i<=unique_rumours.length-1; i++) {
		//if (all_dates.indexOf(unique_rumours[i]['date'])==-1) {
			all_dates.push(unique_rumours[i]['date'])
		//}
	}

	function getDateExtents(all_dates) {
		var min_dt = all_dates[0],
		max_dt = all_dates[all_dates.length-1],
		min_dtObj = new Date(all_dates[0]),
		max_dtObj = new Date(all_dates[all_dates.length-1]);
		
		all_dates.forEach(function(dt, index) {
		    if (new Date(dt) < min_dtObj) {
		        min_dt = dt;
		        min_dtObj = new Date(dt);
		    }
		});
		all_dates.forEach(function(dt, index) {
		    if (new Date(dt) > max_dtObj) {
		        max_dt = dt;
		        max_dtObj = new Date(dt);
		    }
		});
		return [min_dt, max_dt];
	}
	var [min_date, max_date] = getDateExtents(all_dates);
	console.log('Date Extents: ', displayDate(min_date),'-', displayDate(max_date));


	//write title with dates
	if (displayDate(max_date)=='') {
		$('#title').html('Ituri et Nord Kivu - Riposte MVE - Corrélation des mots clé de rumeurs');
	} else {
		$('#title').html('Ituri et Nord Kivu - Riposte MVE - Corrélation des mots clé de rumeurs (données au '+ displayDate(max_date)+')');
	}
	

	
	createDropDownFilters();
	//exportData(rumour_distances);
	updateRumourMatrix();

}

function updateRumourMatrix() {
	//console.log('Unique_rumours: ', unique_rumours);
	console.log('***********************************************');
	console.log('SELECT ZONE, SELECT WEEK: ', $('#dropdown_zone').val(), $('#dropdown_week').val());
	
	var filtered_data = unique_rumours.filter(d =>	((($('#dropdown_zone').val()=='all') || ($('#dropdown_zone').val()==d['zone'])) && (($('#dropdown_week').val()=='all') || ($('#dropdown_week').val()==d['week']))) );
	
	//CHECK FILTERS:
	/*for (var i=0; i<=unique_rumours.length-1; i++) {
		if ((($('#dropdown_zone').val()=='all') || ($('#dropdown_zone').val()==unique_rumours[i]['zone'])) && (($('#dropdown_week').val()=='all') || ($('#dropdown_week').val()==unique_rumours[i]['week']))) {
			console.log($('#dropdown_zone').val(), unique_rumours[i]['zone'], $('#dropdown_week').val(), unique_rumours[i]['week'])
		}
	}*/

	console.log('Filtered data: ', filtered_data)
	createRumourLinksAndKeywordCounts(filtered_data);
	writeRumourLinksTable(filtered_data);
	//console.log('Rumour distances: ', rumour_distances);
}


function createRumourLinksAndKeywordCounts(filtered_data) {
	let count0=0, count1=0, count2=0, countGtE3=0;
	num_links = 0;
	filt_keyword_counts = {};
	rumour_distances = [];


	for (var i=0; i<=filtered_data.length-1; i++) {  //loop through list of unique rumours
		if (filtered_data[i].keywords.length == 0) {  //no keywords, do nothing
			count0++;
		} else if (filtered_data[i].keywords.length == 1) {
			count1++;
			countKeyword(filtered_data[i].keywords[0], filt_keyword_counts);
			insertDistanceLink(filtered_data[i].keywords[0], filtered_data[i].keywords[0]);
		} else if (filtered_data[i].keywords.length == 2) {
			count2++;
			countKeyword(filtered_data[i].keywords[0], filt_keyword_counts);
			if (filtered_data[i].keywords[0] != filtered_data[i].keywords[1]) {
				countKeyword(filtered_data[i].keywords[1], filt_keyword_counts);
			}
			insertDistanceLink(filtered_data[i].keywords[0], filtered_data[i].keywords[1]);
		} else if (filtered_data[i].keywords.length >= 3) {
			for (var j=0; j<=filtered_data[i].keywords.length-1; j++) {
				countKeyword(filtered_data[i].keywords[j], filt_keyword_counts);
				for (var k=j+1; k<=filtered_data[i].keywords.length-1; k++) {
					countKeyword(filtered_data[i].keywords[k], filt_keyword_counts);
					insertDistanceLink(filtered_data[i].keywords[j], filtered_data[i].keywords[k]);
				}
			}
			/* //e.g. where there are 3 keywords, should loop through:
			insertDistanceLink(filtered_data[i].keywords[0], filtered_data[i].keywords[1]);
			insertDistanceLink(filtered_data[i].keywords[0], filtered_data[i].keywords[2]);
			insertDistanceLink(filtered_data[i].keywords[1], filtered_data[i].keywords[2]);*/
			countGtE3++;
		} 

	}

	//CHECK KEYWORD & LINK COUNTS
	/*console.log('Counts of num keywords:');
	console.log('    0: ', count0);
	console.log('    1: ', count1);
	console.log('    2: ', count2);
	console.log('  >=3: ', countGtE3);

	console.log('Total links inserted: ', num_links)
	console.log('Keyword counts: ', filt_keyword_counts)*/

}


function insertDistanceLink(keyword1, keyword2) {
	let link_exists = false;

	num_links++;

	for (var i=0; i<=rumour_distances.length-1; i++) {
		if (((rumour_distances[i][0]==keyword1) && (rumour_distances[i][1]==keyword2)) || ((rumour_distances[i][0]==keyword2) && (rumour_distances[i][1]==keyword1))) {
			rumour_distances[i][2]++;
			link_exists = true;
			break;
		}
	}

	if (!(link_exists)) {
		let temp = [keyword1, keyword2, 1];
		rumour_distances.push(temp);
	}

}


function countKeyword(keyword, all_keywords) {
	if (all_keywords.hasOwnProperty(keyword)) {
		all_keywords[keyword]++;
	} else {
		all_keywords[keyword] = 1;
	}
	return all_keywords;
}



function createDropDownFilters() {
	
	var x = document.getElementById("dropdown_zone");
	var option = document.createElement("option");
	option.value = 'all';
	option.text = 'Toutes les zones';
	x.add(option);
	for (var i=0; i<=unique_zones.length-1; i++) {
		var option = document.createElement("option");
		option.value = unique_zones[i];
		option.text = unique_zones[i];
		x.add(option);
	}

	var x = document.getElementById("dropdown_week");
	var option = document.createElement("option");
	option.value = 'all';
	option.text = 'Toutes les semaines';
	x.add(option);
	for (var i=0; i<=unique_weeks.length-1; i++) {
		var option = document.createElement("option");
		option.value = unique_weeks[i];
		option.text = unique_weeks[i];
		x.add(option);
	}
		
}

function selectZone() {
	//console.log('selectZone, selectWeek: ', $('#dropdown_zone').val(), $('#dropdown_week').val());
	updateRumourMatrix();
}

function selectWeek() {
	//console.log('selectZone, selectWeek: ', $('#dropdown_zone').val(), $('#dropdown_week').val());
	updateRumourMatrix();
}

function writeRumourLinksTable() {
	//console.log(rumour_distances)
	var html = "", summaryHtml = "";;
	let rumLinkRow = "";
	$('#tableRumLink').html('');
	let found_dist;


	function sortArray(a,b) {
	    return b[1] - a[1];
	}


	let rankings = Object.entries(filt_keyword_counts);
	rankings.sort(sortArray);
	//console.log('Rankings: ', rankings);

	//write table headings
	html += '<tr bgcolor="#cfdff9">';
	html += '<th>' + '' + '</th>'; 
	
	const keywords_desc = rankings.map(r => r[0]);
	const keywords_asc = keywords_desc.map(keywords_desc.pop, [...keywords_desc]);
	//console.log('Descending keywords: ', keywords_desc);
	//console.log('Ascending keywords: ', keywords_asc);

	//for (var keyword in unique_keywords) {
	for (var i in rankings) {
		//console.log(i, rankings[i][0])
		html += '<th>' + rankings[i][0] + '</th>'; 
	}
	if ((unique_zones.length==0) && (unique_weeks==0)) {
		html += '</tr><tr><td class="total">Pas de données disponibles</td>';
	} else if (rankings.length==0) {
		html += '</tr><tr><td class="total">Aucune occurrence de mot clé en ' + $('#dropdown_zone').val() + ' pendant la semaine ' + $('#dropdown_week').val() + '</td>';
	} else {
		html += '</tr><tr><td class="total">Total nombre d\'occurences</td>';
	}
	
	for (var i in rankings) {
		//console.log(i, rankings[i][0])
		html += '<td class="center total">' + rankings[i][1] + '</td>'; 
	}
	html += '</tr>';
	$('#tableRumLink').append(html);


	//write table rows
	for (var i1=0; i1<=keywords_asc.length-1; i1++) {
		//console.log(i1, keywords_asc[i1], keywords_desc[i1])
		rumLinkRow = '<tr>';
		rumLinkRow += '<td class="heading">' + keywords_asc[i1] + '</td>';

		for (var i2=0; i2<=keywords_asc.length-1; i2++) {
			found_dist = false;

			for (var j=0; j<=rumour_distances.length-1; j++) {
				//console.log(rumour_distances[j], unique_keywords[i1], unique_keywords[i2]);
					
				if (((rumour_distances[j][0]==keywords_asc[i1]) && (rumour_distances[j][1]==keywords_desc[i2])) || ((rumour_distances[j][0]==keywords_desc[i2]) && (rumour_distances[j][1]==keywords_asc[i1]))) {
					//console.log(rumour_distances[j], rev_unique_keywords[i1], unique_keywords[i2])

					function getBgColor(val) {   
						switch(true) {
						    case val==0: 
						        return 'white';
						        break;
						    case val<=10:
						        return '#fee5d9';
						        break;
						    case val<=20:
						    	return '#fcae91';
						    	break;
						     case val<=30:
						    	return '#fb6a4a';
						    	break;
						    case val>30:
						    	return '#de2d26';
						    	break;
						    default:
						        return 'white';
						}
					}

					if (keywords_desc[i1]==keywords_asc[i2]) {
						rumLinkRow += '<td class="center diagonal highlight">' + rumour_distances[j][2] + '</td>';
					} else {
						rumLinkRow += '<td class="center highlight" style="background:' + getBgColor(rumour_distances[j][2]) + '">' + rumour_distances[j][2] + '</td>';
					};
					found_dist = true;
					break;
				}
			}

			if (!(found_dist)) {
				if (keywords_desc[i1]==keywords_asc[i2]) {
					rumLinkRow += '<td class="center diagonal">' + 0 + '</td>';
				} else {
					rumLinkRow += '<td class="center">' + 0 + '</td>';
				};
			}
			if (keywords_desc[i1]==keywords_asc[i2]) {
				break;
			};
		};

		rumLinkRow += '</tr>';
		$('#tableRumLink').append(rumLinkRow);
	}


	/*summaryHtml += '<tr bgcolor="#cfdff9"><th>Classement</th><th>Mot clé</th><th>Nombre total d\'occurrences</th></tr>';
	let position = 0;
	for (let i=0; i<=rankings.length-1; i++) {
		position++;
		summaryHtml += '<tr><td class="center">' + position + '</td><td>' + rankings[i][0]  + '</td><td class="center">' + rankings[i][1] + '</td></tr>';
	};

	$('#tableRumLinkSummary').append(summaryHtml);*/

}

function sameDay(d1, d2) {
  //console.log(d1, d2, typeof(d1), typeof(d2))
  d1 = new Date(d1);
  return d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate();
}

function isFieldsMatch (rec1, rec2) {

	var compare = function (item1, item2) {
		if (item1 !== item2) return false;
	};

	var field_list = ['aire','zone','hist','date'];
	//var field_list = ['aire','zone','hist'];
	for (var i=0; i<=field_list.length-1; i++) {
		if ((rec1.hasOwnProperty(field_list[i])) && (rec2.hasOwnProperty(field_list[i]))) {
			if (field_list[i]=='date') {
				if (!(sameDay(rec1[field_list[i]], rec2[field_list[i]]))) {
					return false;
				}
			} else if (compare(rec1[field_list[i]], rec2[field_list[i]]) === false) {
				return false;
			}
		}
	}

	return true;
}


function exportData(data) {
	//console.log(data) 
	var filename;
	var rows = [];
	var row = [];
	let keywords_string = "";


	filename = 'rumours_processed.xlsx'

	rows.push(['Date', 'Zone de Sante', 'Aire de Sante', 'Histoire', 'Mots de cle']);
	for (let i=0; i<=data.length-1; i++) {
		keywords_string = data[i].keywords.join(', ');
		rows.push([data[i].date, data[i].zone, data[i].aire, data[i].hist, keywords_string]); 
    }

	download_xlsx(rows, filename);

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

var ExcelToJSON = function() {

  this.parseExcel = function(file) {
    var reader = new FileReader();

    reader.onload = function(e) {
      var data = e.target.result();
      var workbook = XLSX.read(data, {
        type: 'binary'
      });

      workbook.SheetNames.forEach(function(sheetName) {
        // Here is your object
        var XL_row_object = XLSX.utils.sheet_to_row_object_array(workbook.Sheets[sheetName]);
        var json_object = JSON.stringify(XL_row_object);
        console.log(json_object);

      })

    };

    reader.onerror = function(ex) {
      console.log(ex);
    };

    reader.readAsBinaryString(file);
  };
};



$(document).ready(function () {

    let data;

	//Get rumours data from CSV
    /*var d1 = $.ajax({
        type: 'GET',
		url: './js/test_data.csv',
    	dataType: 'text'
    });
	$.when(d1).then(function (a1) {
        console.log('Ajax calls succeedeed');
        //console.log(a1);
        let data = readRumourDataFromCSV(a1);
        console.log('Data: ', data);
        processRumourData(data);
        //exportData(data);

    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;

        if (x1.readyState != 4) {
            x1.abort();
        };
        alert("Data request failed");
        console.log('Ajax request failed');
    });*/

   

    //Get rumours data from googlesheet
    var url = 'https://spreadsheets.google.com/feeds/list/12z67qIUnTdVd3hgVwJB0HfDnNTFWjdEJkqaJq4M8AQg/3/public/values?alt=json';
    //note that /3/ after the worksheetID is for 3rd page in workbook ('CEA-Rumeurs')
    $.getJSON(url, function(gsdata) {
    	console.log('Original googlesheet data: ', gsdata);
    	data = readRumourDataFromGS(gsdata.feed.entry);
    	//console.log('data: ', data) 	
        processRumourData(data);
    });


});
