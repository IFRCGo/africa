"use strict";


function createCeaTable(ceaData) {
	var html = "";
	var ceaHtml = "";

 	html += '<tr bgcolor="#cfdff9">';
 	html += '<th>' + 'Date' + '</th>'; 
	html += '<th>' + 'Date activité' + '</th>'; 
	html += '<th>' + 'Health Area' + '</th>'; 
	html += '<th>' + 'Health Zone' + '</th>'; 
	html += '<th>' + 'Activité' + '</th>'; 
	html += '<th>' + 'Messages Disseminés' + '</th>'; 	
	html += '<th>' + 'Sensibilisation Homme' + '</th>'; 
	html += '<th>' + 'Sensibilisation Femme' + '</th>'; 
	html += '<th>' + 'Sensibilisation Garcon' + '</th>'; 
	html += '<th>' + 'Sensibilisation Fille' + '</th>'; 
	html += '<th>' + 'Sensibilisation Menages Touchés' + '</th>'; 
	html += '<th>' + 'Sensibilisation Personnes' + '</th>'; 	
	html += '<th>' + 'Sensibilisation Personnes Ok' + '</th>'; 
	html += '<th>' + 'Volontaire Homme' + '</th>'; 
	html += '<th>' + 'Volontaire Femme' + '</th>'; 
	html += '<th>' + 'Volontaire Tout' + '</th>'; 
	html += '<th>' + 'Volontaire Ok' + '</th>'; 
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
	html += '<td>' + checkField(row['start']).substring(0,10) + '</td>'; //Date
	html += '<td>' + checkField(row['Intro/date']) + '</td>'; //Date activité
	html += '<td>' + checkField(row['Intro/health_area']) + '</td>'; //Health Area
	html += '<td>' + checkField(row['Intro/health_zone']) + '</td>'; //Health Zone
	html += '<td>' + checkField(row['Intro/activite']) + '</td>'; //Activité
	html += '<td>' + checkField(row['Intro/messages_dissemines']) + '</td>'; //Messages Disseminés	
	html += '<td>' + checkField(row['sensibilisation/homme'])  + '</td>'; //Sensibilisation Homme	
	html += '<td>' + checkField(row['sensibilisation/femme'])  + '</td>'; //Sensibilisation Femme
	html += '<td>' + checkField(row['sensibilisation/garcon']) + '</td>'; //Sensibilisation Garcon	
	html += '<td>' + checkField(row['sensibilisation/fille']) + '</td>'; //Sensibilisation Fille
	html += '<td>' + checkField(row['sensibilisation/menages_touches']) + '</td>'; //Sensibilisation Menages Touchés
	html += '<td>' + checkField(row['sensibilisation/personnes']) + '</td>'; //Sensibilisation Personnes
	html += '<td>' + checkField(row['sensibilisation/personnes_ok']) + '</td>'; //Sensibilisation Personnes
	html += '<td>' + checkField(row['volontaire/volontaire_homme']) + '</td>'; //Volontaire Homme
	html += '<td>' + checkField(row['volontaire/volontaire_femme']) + '</td>'; //Volontaire Femme
	html += '<td>' + checkField(row['volontaire/volontaire_tout']) + '</td>'; //Volontaire Tout
	html += '<td>' + checkField(row['volontaire/volontaire_ok']) + '</td>'; //Volontaire Ok

	html += '</tr>';

	return html;
}




function calculateTimeFromDatetime(date){
	function checkTime(i) {
	  if (i < 10) {
	    i = "0" + i;
	  }
	  return i;
	}

	//Parsing time (the time below is assumed to be GMT+2) from string
	//Removing timezone stamp at end of string - need to check this with SIMS
	if(date.indexOf('+')>0){
		date = date.substring(0,date.indexOf('+')-4);
	} else {
	let parts = date.split('-');
	let loc = parts.pop();
	date = parts.join('-');
	}


	let newDate = new Date(date);
//	let time = newDate.getTime();
	let h = newDate.getHours();
	let m = newDate.getMinutes();
	let s = newDate.getSeconds();
	// add a zero in front of numbers<10
	m = checkTime(m);
	s = checkTime(s);
	let html = h + ":" + m + ":" + s;
	return html;
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



// Get Alert & Activity data - simultaneous AJAX requests
$(document).ready(function () {
    var d1 = $.ajax({
        type: 'GET',
		url: 'https://kc.humanitarianresponse.info/api/v1/data/264009?format=jsonp',
    	dataType: 'jsonp',
    });

    $.when(d1).then(function (a1) {
        console.log('Ajax call succeedeed');
        console.log(a1);
        createCeaTable(a1.reverse());
    }, function (jqXHR, textStatus, errorThrown) {
        var x1 = d1;
        if (x1.readyState != 4) {
            x1.abort();
        }
        alert("Data request failed");
        console.log('Ajax request failed');
    });
});
