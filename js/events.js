// Flatten hxl proxy data into JSON
function hxlProxyToJSON(input,headers){
    var output = [];
    var keys=[]
    input.forEach(function(e,i){
        if(i==0){
            e.forEach(function(e2,i2){
                var parts = e2.split('+');
                var key = parts[0]
                if(parts.length>1){
                    var atts = parts.splice(1,parts.length);
                    atts.sort();
                    atts.forEach(function(att){
                        key +='+'+att
                    });
                }
                keys.push(key);
            });
        } else {
            var row = {};
            e.forEach(function(e2,i2){
                row[keys[i2]] = e2;
            });
            output.push(row);
        }
    });
    return output;
}

// Generate tables for appeals and DREFs
function creatEventsTable(data){
    // Initialize html tables
    var html = "";
	var pastEvents = " ";
	var newEvents = " ";
	
	var lang = "EN";
	var curDate = new Date();
	var pastMonth = -1;
	var pastYear = -1;
	var curMonth = -1;
	
	data.sort(function(a, b){return a.Start_date - b.Start_date});

    // Run through data and prep for tables
    data.forEach(function(d,i){
		var eventDate = new Date(d['Start_date']);
		var eventEnd = new Date(d['End_date']);
		console.log(eventDate == eventEnd);

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
		return '<tr class="event_month"><td colspan="6"><h2>' + monthsFrn[month] + ' ' + year + '</h2></td></tr><tr class="event_header"><td></td><td><i>Evénement</i></td><td><i>Date</i></td><td><i>pays</i></td><td><i>Participants</i></td><td><i>Organisateur</i></td></tr>';
	} else {
		return '<tr class="event_month"><td colspan="6"><h2>' + monthsEng[month] + ' ' + year + '</h2></td></tr><tr class="event_header"><td></td><td><i>Event</i></td><td><i>date</i></td><td><i>Location</i></td><td><i>Participants</i></td><td><i>Organizer</i></td></tr>';
	}
}

function createEventRow(d, lang) {
	var html = '';
	html += '<tr class="event_item"><td class="table_icon"><img src="./img/events_' + d['Type_of_event'] + '.svg" alt="' + d['Type_of_event'] + '" title="' + d['Type_of_event'] + '" /></td>';
	html += '<td>' + d['Name_event'] + '</td><td>' + d['Start_date'];
	if (d['Start_date'] != d['End_date']) {
		html += ' - ' + d['End_date'];
	}
	html += '</td><td>' + getCountry(d['Country'],lang) + '</td>';
	html += '<td>' + getParticipants(d['ns_participating'],lang) + '</td><td>' + d['Organizer'] + '</td></tr>';
	return html;
}

function getCountry(iso3,lang) {
	var countries = [
		['AGO','Angola'],
		['BEN','Benin'],
		['BWA','Botswana'],
		['BFA','Burkina Faso'],
		['BDI','Burundi'],
		['CMR','Cameroon'],
		['CPV','Cape Verde'],
		['CAF','Central African Republic'],
		['TCD','Chad'],
		['COM','Comoros'],
		['COD','Democratic Republic of the Congo'],
		['COG','Republic of Congo'],
		['CIV','Cote d\'Ivoire'],
		['DJI','Djibouti'],
		['GNQ','Equatorial Guinea'],
		['ERI','Eritrea'],
		['ETH','Ethiopia'],
		['GAB','Gabon'],
		['GMB','Gambia'],
		['GHA','Ghana'],
		['GIN','Guinea'],
		['GNB','Guinea-Bissau'],
		['KEN','Kenya'],
		['LSO','Lesotho'],
		['LBR','Liberia'],
		['MDG','Madagascar'],
		['MWI','Malawi'],
		['MLI','Mali'],
		['MUS','Mauritius'],
		['MRT','Mauritania'],
		['MOZ','Mozambique'],
		['NAM','Namibia'],
		['NER','Niger'],
		['NGA','Nigeria'],
		['RWA','Rwanda'],
		['STP','Sao Tome and Principe'],
		['SEN','Senegal'],
		['SYC','Seychelles'],
		['SLE','Sierra Leone'],
		['SOM','Somalia'],
		['ZAF','South Africa'],
		['SSD','South Sudan'],
		['SDN','Sudan'],
		['SWZ','Swaziland'],
		['TZA','Tanzania'],
		['TGO','Togo'],
		['UGA','Uganda'],
		['ZMB','Zambia'],
		['ZWE','Zimbabwe'],
		['OTHER','outside in Africa Region']
	];
	var country = '';
	countries.forEach(function(d,i){
		if (d[0] == iso3) {
			country = d[1];
		}			
	});
	return country;
}

function getParticipants(ns,lang) {
	var natSocieties = [
		['AGO','Angola Red Cross'],
		['BEN','Red Cross of Benin'],
		['BWA','Botswana Red Cross Society'],
		['BFA','Burkinabe Red Cross Society'],
		['BDI','Burundi Red Cross'],
		['CMR','Cameroon Red Cross Society'],
		['CPV','Red Cross of Cape Verde'],
		['CAF','Central African Red Cross Society'],
		['TCD','Red Cross of Chad'],
		['COM','The Comoros Red Crescent'],
		['COD','Red Cross of the Democratic Republic of the Congo'],
		['COG','Congolese Red Cross'],
		['CIV','Red Cross Society of Côte d\'Ivoire'],
		['DJI','Red Crescent Society of Djibouti'],
		['GNQ','Red Cross of Equatorial Guinea'],
		['ERI','Red Cross Society of Eritrea'],
		['ETH','Ethiopian Red Cross Society'],
		['GAB','Gabonese Red Cross Society'],
		['GMB','Gambia Red Cross Society'],
		['GHA','Ghana Red Cross Society'],
		['GIN','Red Cross Society of Guinea'],
		['GNB','Red Cross Society of Guinea-Bissau'],
		['KEN','Kenya Red Cross Society'],
		['LSO','Lesotho Red Cross Society'],
		['LBR','Liberian Red Cross Society'],
		['MDG','Madagasy Red Cross Society'],
		['MWI','Malawi Red Cross Society'],
		['MLI','Mali Red Cross'],
		['MUS','Mauritius Red Cross Society'],
		['MRT','Mauritanian Red Crescent'],
		['MOZ','Mozambique Red Cross Society'],
		['NAM','Namibia Red Cross'],
		['NER','Red Cross Society of Niger'],
		['NGA','Nigerian Red Cross Society'],
		['RWA','Rwandan Red Cross'],
		['STP','Sao Tome and Principe Red Cross'],
		['SEN','Senegalese Red Cross Society'],
		['SYC','Seychelles Red Cross Society'],
		['SLE','Sierra Leone Red Cross Society'],
		['SOM','Somali Red Crescent Society'],
		['ZAF','South African Red Cross Society'],
		['SSD','South Sudan Red Cross'],
		['SDN','The Sudanese Red Crescent'],
		['SWZ','Baphalali Swaziland Red Cross Society'],
		['TZA','Tanzania Red Cross National Society'],
		['TGO','Togolese Red Cross'],
		['UGA','Uganda Red Cross Society'],
		['ZMB','Zambia Red Cross Society'],
		['ZWE','Zimbabwe Red Cross Society']
	];
	var participants = '';
	if (ns === undefined) {
		participants = '-';
	} else {
		natSocieties.forEach(function(d,i){
			if (ns.indexOf(d[0])>=0) {
				participants += d[1] + '<br />';
			}			
		});
	}
	return participants; 
}
// Get appeals and DREFs data
$.ajax({
    type: 'GET',
	url: 'https://kc.humanitarianresponse.info/api/v1/data/203425?format=jsonp',
    dataType: 'jsonp',
	jsonpCallback: "creatEventsTable"
});

