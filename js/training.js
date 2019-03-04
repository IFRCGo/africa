"use strict";
// Generate tables for trainings
function createTrainingsTable(data){
    // Initialize html tables
	var pastEvents = " ";
	var newEvents = " ";
	
	var lang = "EN";
	var curDate = new Date();
	var pastMonth = -1;
	var pastYear = -1;
	var curMonth = -1;
	
	data.sort(function(a, b){
		var dateA = new Date(a.Start_date);
		var dateB = new Date(b.Start_date);
		return dateA - dateB;
	});
	
    // Run through data and prep for tables
    data.forEach(function(d,i){
		// Only process trainings
		if (d.Type_of_event === "training") {
			var eventDate = new Date(d.Start_date);

			if(eventDate < curDate) {

				// Historic Event
				if (eventDate.getMonth()!=pastMonth) {
					// New month, add the month to the output

					//TODO PUT THIS IN THE RIGHT ORDER!!!
					if ( pastEvents.length > 5) {
						pastEvents = createMonthBar(pastMonth, pastYear, lang) + pastEvents;
					}
					pastMonth = eventDate.getMonth();
					pastYear = eventDate.getFullYear();
				}
				pastEvents = createEventRow(d, lang) + pastEvents;
			} else {

				// New Event
				if (eventDate.getMonth()!=curMonth || newEvents === "") {
					// New month, add the month to the output
					newEvents += createMonthBar(eventDate.getMonth(), eventDate.getFullYear(), lang) ;
					curMonth = eventDate.getMonth();
				}
				newEvents += createEventRow(d, lang);
			}
		}
    });
	if (pastEvents.length > 5) {
		pastEvents = createMonthBar(pastMonth, pastYear, lang) + pastEvents;
	}
    // Send data to appeals or DREFs html tables
    $('#eventstable').append(newEvents);
    $('#pasteventstable').append(pastEvents);
    
}

function createMonthBar(month, year, language) {
	var monthsEng = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
	var monthsFrn = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
	if (language === 'FR') {
		return '<tr class="event_month"><td colspan="6"><h2>' + monthsFrn[month] + ' ' + year + '</h2></td></tr><tr class="event_header"><td><i>Evénement</i></td><td><i>Date</i></td><td><i>pays</i></td><td><i>Participants</i></td><td><i>Organisateur</i></td><td>Bailleur</td></tr>';
	} else {
		return '<tr class="event_month"><td colspan="6"><h2>' + monthsEng[month] + ' ' + year + '</h2></td></tr><tr class="event_header"><td><i>Event</i></td><td><i>date</i></td><td><i>Location</i></td><td><i>Participants</i></td><td><i>Organizer</i></td><td>Funded</td></tr>';
	}
}

function createEventRow(d, lang) {
	var html = '';
	html += '<tr class="event_item"><td>' + d.Name_event + '</td><td>' + d.Start_date;
	if (d.Start_date != d.End_date) {
		html += ' - ' + d.End_date;
	}
	html += '</td><td>' + getCountry(d.Country,lang) + '</td>';
	html += '<td>' + getParticipants(d.ns_participating,lang) + '</td><td>' + d.Organizer + '</td>';
	html += '<td>' + d.Funding + '</td></tr>';
	return html;
}

function getCountry(iso3,lang) {
	var countries = [
		['AGO','Angola','Angola'],
		['BEN','Benin','Bénin'],
		['BWA','Botswana','Botswana'],
		['BFA','Burkina Faso','Burkina Faso'],
		['BDI','Burundi','Burundi'],
		['CMR','Cameroon','Cameroun'],
		['CPV','Cape Verde','Cap-vert'],
		['CAF','Central African Republic','République centrafricaine'],
		['TCD','Chad','Tchad'],
		['COM','Comoros','Comores'],
		['COD','Democratic Republic of the Congo','République démocratique du congo'],
		['COG','Republic of Congo','République du congo'],
		['CIV','Cote d\'Ivoire','Cote d\'Ivoire'],
		['DJI','Djibouti','Djibouti'],
		['GNQ','Equatorial Guinea','Guinée équatoriale'],
		['ERI','Eritrea','Érythrée'],
		['SWZ','Eswatini (the Kingdom of)','Eswatini (royaume de)'],
		['ETH','Ethiopia','Éthiopie'],
		['GAB','Gabon','Gabon'],
		['GMB','Gambia','Gambie'],
		['GHA','Ghana','Ghana'],
		['GIN','Guinea','Guinée'],
		['GNB','Guinea-Bissau','Guinée-bissau'],
		['KEN','Kenya','Kenya'],
		['LSO','Lesotho','Lesotho'],
		['LBR','Liberia','Liberia'],
		['MDG','Madagascar','Madagascar'],
		['MWI','Malawi','Malawi'],
		['MLI','Mali','Mali'],
		['MUS','Mauritius','Maurice'],
		['MRT','Mauritania','Mauritanie'],
		['MOZ','Mozambique','Mozambique'],
		['NAM','Namibia','Namibie'],
		['NER','Niger','Niger'],
		['NGA','Nigeria','Nigeria'],
		['RWA','Rwanda','Rwanda'],
		['STP','Sao Tome and Principe','Sao Tomé-et-Principe'],
		['SEN','Senegal','Sénégal'],
		['SYC','Seychelles','Seychelles'],
		['SLE','Sierra Leone','Sierra Leone'],
		['SOM','Somalia','Somalie'],
		['ZAF','South Africa','Afrique du sud'],
		['SSD','South Sudan','Soudan du sud'],
		['SDN','Sudan','Soudan'],
		['TZA','Tanzania','Tanzanie'],
		['TGO','Togo','Togo'],
		['UGA','Uganda','Ouganda'],
		['ZMB','Zambia','Zambie'],
		['ZWE','Zimbabwe','Zimbabwe'],
		['OTHER','outside the Africa Region','en dehors de la Région Afrique']
	];
	var country = '';
	if (lang == 'FR') {
		countries.forEach(function(d,i){
			if (d[0] == iso3) {
				country = d[2];
			}			
		});
	} else {
		countries.forEach(function(d,i){
			if (d[0] == iso3) {
				country = d[1];
			}			
		});
	}
	return country;
}

function getParticipants(ns,lang) {
	var natSocieties = [
		['AGO','Angola Red Cross','Croix-Rouge angolaise'],
		['BEN','Red Cross of Benin','Croix-Rouge béninoise'],
		['BWA','Botswana Red Cross Society','Croix-Rouge du Botswana'],
		['BFA','Burkinabe Red Cross Society','Croix-Rouge burkinabè'],
		['BDI','Burundi Red Cross','Croix-Rouge du Burundi'],
		['CMR','Cameroon Red Cross Society','Croix-Rouge camerounaise'],
		['CPV','Red Cross of Cape Verde','Croix-Rouge du Cap-Vert'],
		['CAF','Central African Red Cross Society','Société de la Croix-Rouge centrafricaine'],
		['TCD','Red Cross of Chad','Croix-Rouge du Tchad'],
		['COM','The Comoros Red Crescent','Croissant-Rouge comorien'],
		['COD','Red Cross of the Democratic Republic of the Congo','Croix-Rouge de la République démocratique du Congo'],
		['COG','Congolese Red Cross','Croix-Rouge congolaise'],
		['CIV','Red Cross Society of Côte d\'Ivoire','Croix-Rouge de la Côte d\'Ivoire'],
		['DJI','Red Crescent Society of Djibouti','Société du Croissant-Rouge de Djibouti'],
		['GNQ','Red Cross of Equatorial Guinea','Croix-Rouge de Guinée Équatoriale'],
		['ERI','Red Cross Society of Eritrea','Croix-Rouge érythréenne'],
		['SWZ','Baphalali Eswatini Red Cross Society','Croix-Rouge du Eswatini'],
		['ETH','Ethiopian Red Cross Society','Croix-Rouge éthiopienne'],
		['GAB','Gabonese Red Cross Society','Croix-Rouge gabonaise'],
		['GMB','Gambia Red Cross Society','Croix-Rouge de la Gambie'],
		['GHA','Ghana Red Cross Society','Croix-Rouge du Ghana'],
		['GIN','Red Cross Society of Guinea','Croix-Rouge guinéenne'],
		['GNB','Red Cross Society of Guinea-Bissau','Croix-Rouge de la Guinée-Bissau'],
		['KEN','Kenya Red Cross Society','Croix-Rouge du Kenya'],
		['LSO','Lesotho Red Cross Society','Croix-Rouge du Lesotho'],
		['LBR','Liberian Red Cross Society','Croix-Rouge du Libéria'],
		['MDG','Madagasy Red Cross Society','Croix-Rouge Malagasy'],
		['MWI','Malawi Red Cross Society','Croix-Rouge du Malawi'],
		['MLI','Mali Red Cross','Croix-Rouge malienne'],
		['MUS','Mauritius Red Cross Society','Croix-Rouge de Maurice'],
		['MRT','Mauritanian Red Crescent','Croissant-Rouge mauritanien'],
		['MOZ','Mozambique Red Cross Society','Croix-Rouge du Mozambique'],
		['NAM','Namibia Red Cross','Croix-Rouge de Namibie'],
		['NER','Red Cross Society of Niger','Croix-Rouge nigérienne'],
		['NGA','Nigerian Red Cross Society','Croix-Rouge du Nigéria'],
		['RWA','Rwandan Red Cross','Croix-Rouge rwandaise'],
		['STP','Sao Tome and Principe Red Cross','Croix-Rouge de Sao Tomé-et-Principe'],
		['SEN','Senegalese Red Cross Society','Croix-Rouge sénégalaise'],
		['SYC','Seychelles Red Cross Society','Croix-Rouge des Seychelles'],
		['SLE','Sierra Leone Red Cross Society','Croix-Rouge de Sierra Leone'],
		['SOM','Somali Red Crescent Society','Croissant-Rouge de Somalie'],
		['ZAF','South African Red Cross Society','Croix-Rouge sud-africaine'],
		['SSD','South Sudan Red Cross','Croissant-Rouge sud-soudanais'],
		['SDN','The Sudanese Red Crescent','Croissant-Rouge soudanais'],
		['TZA','Tanzania Red Cross National Society','Croix-Rouge nationale de Tanzanie'],
		['TGO','Togolese Red Cross','Croix-Rouge togolaise'],
		['UGA','Uganda Red Cross Society','Croix-Rouge de l\'Ouganda'],
		['ZMB','Zambia Red Cross Society','Croix-Rouge de Zambie'],
		['ZWE','Zimbabwe Red Cross Society','Croix-Rouge du Zimbabwe']
	];
	var participants = '';
	if (ns === undefined) {
		participants = '-';
	} else {
		if (lang == 'FR') {
			natSocieties.forEach(function(d,i){
				if (ns.indexOf(d[0])>=0) {
					participants += d[2] + '<br />';
				}			
			});
		} else {
			natSocieties.forEach(function(d,i){
				if (ns.indexOf(d[0])>=0) {
					participants += d[1] + '<br />';
				}			
			});
		}
	}
	return participants; 
}
// Get trainings data
$.ajax({
    type: 'GET',
	url: 'https://kc.humanitarianresponse.info/api/v1/data/203425?format=jsonp',
    dataType: 'jsonp',
	jsonpCallback: "createTrainingsTable"
});

