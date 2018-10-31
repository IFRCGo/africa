"use strict";

let data, currentData;

let headings = {
	'Date': 'start',
	'Date activité': 'Intro/date',
	'Health Area': 'Intro/health_area',
	'Health Zone': 'Intro/health_zone', 
	'Activité': 'Intro/activite',
	'Messages Disseminés': 'Intro/messages_dissemines',
	'Sensibilisation Homme': 'sensibilisation/homme', 
	'Sensibilisation Femme': 'sensibilisation/femme', 
	'Sensibilisation Garcon': 'sensibilisation/garcon', 
	'Sensibilisation Fille': 'sensibilisation/fille',
	'Sensibilisation Menages Touchés': 'sensibilisation/menages_touches', 
	'Sensibilisation Personnes': 'sensibilisation/personnes',
	'Sensibilisation Personnes Ok': 'sensibilisation/personnes_ok', 
	'Volontaire Homme': 'volontaire/volontaire_homme',
	'Volontaire Femme': 'volontaire/volontaire_femme',
	'Volontaire Tout': 'volontaire/volontaire_tout',
	'Volontaire Ok': 'volontaire/volontaire_ok'
}



function formatDate(date) {
	//console.log(date, format);
	let months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];
	let date_parsed = new Date(parseInt(date.substr(0,4)), parseInt(date.substr(5,7)), parseInt(date.substr(8,10)));
	let newdate;

	newdate = date_parsed.getDate() + '-' + months[date_parsed.getMonth()-1] + '-' + date_parsed.getFullYear();

	return newdate;
}

function processCEAData(ceaData) {

	let temp_date;
	
	for (let i=0; i<=ceaData.length-1; i++) {
		if (ceaData[i].hasOwnProperty('Intro/date')) {
			temp_date = ceaData[i]['Intro/date'];
			ceaData[i]['date'] = new Date(parseInt(temp_date.substr(0,4)), parseInt(temp_date.substr(5,7))-1, parseInt(temp_date.substr(8,10)));
		} else {
			console.log('No Intro/date field')
		}
	}
	data = reverseSortByKey(ceaData, 'date'); //example useage
	return data;
};

function createCeaTable(ceaData) {
	var html = "";
	var ceaHtml = "";

 	html += '<tr bgcolor="#cfdff9">';
 	for (var head in headings) {
		html += '<th>' + head + '</th>';
	};
	html += '</tr>'

	$('#tableCEA').append(html);

	ceaData.forEach(function(d,i){
		ceaHtml = createCeaRow(d);
		$('#tableCEA').append(ceaHtml);
	})

}


function createCeaRow(row) {
	//console.log('createCeaRow: ', row)
	var html = "";

	html += '<tr>';
 	for (var head in headings) {
 		if (headings[head]=='start') {
 			html += '<td>' + getDateFromDatetime(row['start'].substring(0,10)) + '</td>';
				
 		} else {
 			html += '<td>' + checkField(row[headings[head]]) + '</td>';
 		}
		
	};
	html += '</tr>'

	return html;
}


function getDateFromDatetime(datetime){
	//console.log('datetime input: ', datetime)
	let newdate;
	//let months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"];

	if(datetime.indexOf('+')>0){
		datetime = datetime.substring(0,datetime.indexOf('+')-4);
	} else {
		let parts = datetime.split('-');
		//let loc = parts.pop();
		datetime = parts.join('-');
	}

	let newDate = new Date(datetime);
	function getDayNum(num) {
		if (num<10) {
			return '0'+num;
		} else {
			return num;
		}
	}

	let month_num = parseInt(newDate.getMonth())+1;
	let date_num = getDayNum(newDate.getDate())
	newdate = newDate.getFullYear() + '-' + month_num + '-' + date_num;
	
	return newdate;
}


function checkField(field) {
	if (field == null) {
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
//data = reverseSortByKey(data, 'date_field'); //example useage



function withinWeek(d1, d2) {
  //console.log(d1, d2, typeof(d1), typeof(d2))
  let one_week=7*1000*60*60*24; //1 week in milliseconds
  let withinWeek = false;

  d1 = new Date(d1);
  
  let difference_ms = d2.getTime() - d1.getTime();  //calculate the difference in milliseconds

  if (difference_ms <= one_week) withinWeek=true; 
  return withinWeek;
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
		case 'selected': 		filename = 'CEA_data_all__' + now_fname; break;
		case 'all_week': 		filename = 'CEA_data_week__' + now_fname; break;
		default: filename = 'CEA_data_' + now_fname + '.xls'; 
	}
	if (fileType=='csv') {
		filename = filename + '.csv';
    } else if (fileType=='xlsx') {
    	filename = filename + '.xlsx';
    }
	
	for (var head in headings) {
		row.push(head);
	}
	rows.push(row);

	if (option == 'selected') {

    	for (var i = 0; i <= currentData.length-1; i++) {
    		//console.log(i, currentData[i])
 	
    		row = []

    		for (var head in headings) {
    			if (currentData[i].hasOwnProperty(headings[head])) {
    				if (headings[head]=='start') {
    					row.push(getDateFromDatetime(currentData[i][headings[head]].substring(0,10)))
    				} else {
    					row.push(currentData[i][headings[head]]);
    				}
					
				} else {
					row.push(' ')
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


    } else {

    	for (var i = 0; i <= data.length-1; i++) {
    		//console.log(i, data[i])

    		if ((option == 'all_week') && (withinWeek(data[i]['Intro/date'],now))) {

				row = []

	    		for (var head in headings) {
	    			if (currentData[i].hasOwnProperty(headings[head])) {
						if (headings[head]=='start') {
	    					row.push(getDateFromDatetime(currentData[i][headings[head]].substring(0,10)))
	    				} else {
	    					row.push(currentData[i][headings[head]]);
	    				}
					} else {
						row.push(' ')
					}
				}

		        has_rows = true;
		        if (fileType=='csv') {
					rows.push(row.join(","));
			    } else if (fileType=='xlsx') {
			    	rows.push(row);
			    }

			}

    	}

    	if (!(has_rows)) {
    		if (option=='all_today') {
				rows.push(['Aucune donnée disponible pour aujourd\'hui'])
			} else if (option=='all_yesterday') {
				rows.push(['Aucune donnée disponible pour hier'])
			}
		}

    }

    if (fileType=='csv') {
		download_csv(rows.join("\n"), filename);
    } else if (fileType=='xlsx') {
    	//console.log(rows,filename)
    	download_xlsx(rows, filename);
    	console.log('Downloaded: ', filename);
    }
	

}



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


// Get CEA data
$(document).ready(function () {
    var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/264009?format=jsonp',
    	dataType: 'jsonp',
    });

    $.when(d1).then(function (a1) {
        console.log('Ajax call succeedeed');
        console.log(a1);
        data = processCEAData(a1);
        currentData = data;
        createCeaTable(data);
    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        if (x1.readyState != 4) {
            x1.abort();
        }
        alert("Data request failed");
        console.log('Ajax request failed');
    });
});
