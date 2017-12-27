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

// Number formatting
function niceFormatNumber(num,round){
    if(isNaN(parseFloat(num))){
        return num;
    } else {
        if(!round){
            var format = d3.format("0,000");
            return format(parseFloat(num));
        } else {
            var output = d3.format(".4s")(parseFloat(num));
            if(output.slice(-1)=='k'){
                output = Math.round(output.slice(0, -1) * 1000);
                output = d3.format("0,000")(output);
            } else if(output.slice(-1)=='M'){
                output = d3.format(".1f")(output.slice(0, -1))+' million';
            } else if (output.slice(-1) == 'G') {
                output = output.slice(0, -1) + ' billion';
            } else {
                output = ''+d3.format(".3s")(parseFloat(num));
            }
            return output;
        }
    }
}

// Generate tables for appeals and DREFs
function createAppealsTable(data){
    // Initialize html tables
    var html = "";

    // Run through data and prep for tables
    data.forEach(function(d,i){

        if(d['#severity']==='Emergency'){
            html += '<tr><td>'+d['#crisis+name']+'</td><td>'+d['#crisis+type']+'</td><td>Appeal</td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td><td>'+niceFormatNumber(d['#targeted'])+'</td><td>'+niceFormatNumber(d['#meta+value'])+'</td><td>'+d['#meta+id']+'</td></tr>';
        }
        if(d['#severity']==='Minor Emergency'){
            html += '<tr><td>'+d['#crisis+name']+'</td><td>'+d['#crisis+type']+'</td><td>DREF</td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td><td>'+niceFormatNumber(d['#targeted'])+'</td><td>'+niceFormatNumber(d['#meta+value'])+'</td><td>'+d['#meta+id']+'</td></tr>';
        }
    });
    // Send data to appeals or DREFs html tables
    $('#appealstable').append(html);
    
}

// Fill the Key Figures
function loadFDRS(url){
    var hxlurl = 'https://proxy.hxlstandard.org/data.json?strip-headers=on&url='+url;
    $.ajax({
            type: 'GET',
            url: hxlurl,
            dataType: 'json',
            success: function(result){
                var data = hxlProxyToJSON(result);
                console.log(data);
                var html = '<div class="column small-up-2 medium-up-3 large-up-3"><h1>Areas of Focus: People Reached</h1>';
                data.forEach(function(d){
                    html+='<div class="column"><div class="card padded"><img alt="'+d['#meta+title']+' Area of Focus" title="'+d['#meta+title']+'" class="text-center" width="100" src="img/'+d['#meta+icon']+'.svg"><h5 class="keyfiguretitle text-center">'+d['#meta+title']+'</h5><p class="keyfigure text-center">'+niceFormatNumber(d['#indicator'])+'</p><p class="small text-center">Source: <a href="'+d['#meta+url']+'">'+d['#meta+source']+'</a></p></div></div>';
                });
                html+='</div>'; //closing div

                // Send html to proper id
                $('#aof').html(html);
            }
    });
}

function loadINFORMindex(url) {
	var lvlNatural = [0,1.3,2.8,4.7,6.9];
	var lvlHuman = [0,1,3.1,7,9];
	var lvlHazard = [0,1.5,2.7,4.1,6.1];
	var lvlSocEc = [0,1.8,3.5,5.4,7.1];
	var lvlVulGrp = [0,1.6,2.9,4.4,6.3];
	var lvlVulna = [0,2,3.2,4.8,6.4];
	var lvlInstit = [0,3.3,4.9,6,7.3];
	var lvlInfra = [0,2.1,3.5,5.4,7.4];
	var lvlCoping = [0,3.2,4.7,6,7.4];
	var lvlRisk	= [0,2,3.5,5,6.5];
	var lvlClass = ["Very Low","Low","Medium","High","Very High"];
   $.ajax({
            type: 'GET',
            url: url,
            dataType: 'json',
            success: function(result){
                var data = hxlProxyToJSON(result);
                console.log(data);
                data.forEach(function(d){
					
					$('#hazard').html( fillRiskCard ( 'HAZARD &amp; EXPOSURE' , [ ['Overall',d['#index+hazard'],lvlHazard],  ['Natural',d['#index+natural'],lvlNatural] , ['Human',d['#index+human'],lvlHuman]], 'haz') ); 

					$('#vulnerability').html( fillRiskCard ( 'VULNERABILITY' , [ ['Overall',d['#index+vulnarability'],lvlVulna],  ['Socio-Economic',d['#index+socioeconomic'],lvlSocEc] , ['Vulnerable Groups',d['#index+vulnarablegroups'],lvlVulGrp]], 'vul') ); 
					
					$('#lack_of_coping').html( fillRiskCard ( 'LACK OF COPING CAPACITY' , [ ['Overall',d['#index+lackcopingcapacity'],lvlCoping],  ['Institutional',d['#index+institutional'],lvlInstit] , ['Infrastructure',d['#index+infrastructure'],lvlInfra]], 'cap') ); 

					$('#INFORM_sum').html( fillRiskCard ( 'SUMMARY' , [ ['Inform Risk',d['#index+informrisk'],lvlRisk],  ['Risk Class',d['#index+class'],lvlClass] ], 'sum') ); 
				
                });

                // Send html to proper id
            }
	
    });
}

function fillRiskCard (title, data, csscat) {
	var html = '<h4 class="keyfiguretitle text-center minheight">'+title+'</h4>';
	data.forEach( function (v,i) {
		html += '<h5 class="text-center minheight">'+v[0]+'</h5>';
		html += '<p class="keyfigure text-center INF_'+ csscat 
		if (i>0) { html += '_sub'}
		html += '_level'+determineLevel(v[1], v[2])+'">'+v[1]+'</p>';
	});
	return html;
}

function determineLevel(val, range) {
	var lvl = 1;
 	range.forEach(function(item,index){
		if (val >= item){
			lvl = index+1;
		}
	});		
	return lvl;
}


// Identify for which country / National Society
var hash = decodeURIComponent(window.location.hash).substring(1);
var patt = new RegExp("^[a-zA-Z]{3}$");
if ( patt.test(hash) ) {
	hash = hash.toUpperCase();
} else {
	hash = "KEN";
}

// Load the Key Figures with FDRS data
//loadFDRS(hxlINFORMCallURL);

// Get the INFORM index numbers
var hxlINFORMCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23country%2Bcode%3DCOUNTRYCODE&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1qO4nDJqgRyjxi-Uj5uwSJwFEVf7mloTrtFa9pP3qPwY%2Fedit%23gid%3D646091966';
hxlINFORMCallURL = hxlINFORMCallURL.replace('COUNTRYCODE',hash);
loadINFORMindex(hxlINFORMCallURL);

// Identify URL for appeals and DREFs data
var hxlAppealsCallURL = 'https://proxy.hxlstandard.org/data.json?filter01=merge&merge-url01=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1GugpfyzridvfezFcDsl6dNlpZDqI8TQJw-Jx52obny8%2Fedit%23gid%3D0&merge-keys01=%23country%2Bname&merge-tags01=%23country%2Bcode&filter02=clean&clean-date-format02=%23date&filter03=replace-map&replace-map-url03=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1hTE0U3V8x18homc5KxfA7IIrv1Y9F1oulhJt0Z4z3zo%2Fedit%23gid%3D0&filter04=select&select-query04-01=%23country%2Bcode%3DCOUNTRYCODE&filter05=sort&sort-tags05=%23date%2Bend&sort-reverse05=on&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F19pBx2NpbgcLFeWoJGdCqECT2kw9O9_WmcZ3O41Sj4hU%2Fedit%23gid%3D0&sheet=1';

hxlAppealsCallURL = hxlAppealsCallURL.replace('COUNTRYCODE',hash);


// Get appeals and DREFs data
$.ajax({
    type: 'GET',
    url: hxlAppealsCallURL,
    dataType: 'json',
    success:function(response){
        var data = hxlProxyToJSON(response);
        createAppealsTable(data);
    }
});
