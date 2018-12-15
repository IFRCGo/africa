'use strict';

function hxlProxyToJSON(input,headers){
    var output = [];
    var keys=[];
    input.forEach(function(e,i){
        if(i===0){
            e.forEach(function(e2,i2){
                var parts = e2.split('+');
                var key = parts[0];
                if(parts.length>1){
                    var atts = parts.splice(1,parts.length);
                    atts.sort();
                    atts.forEach(function(att){
                        key +='+'+att;
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


function createActivityTable(data) {
	var table='';
	data.forEach(function(d,i){
		if (i>0) {
			table += '<tr><td>';
			table += d[4];
			table += '<br /><small>'
			table += d[5];
			table += '</small></td><td>';
			table += d[6];
			table += '</td><td>From: ';
			table += d[8];
			table += '<br />Until: ';
			if (d[9].trim().length>0) {
				table += d[9];
			} else {
				table += 'unknown';
			}
			table += '</td><td>';
			table += d[10];
			table += '<br />';
			table += d[11];
			table += '</td><td>';
			table += d[14];
			if (d[12].trim().length>0) {
				table += '<br /><span style="font-style: italic;">('
				table += niceFormatNumber(d[12],false);
				table += ' CHF)</span>';
			}
			table += '</td><td>';
			table += d[13];
			table += '</td></tr>';
		}
	});
	
	if (table.length === 0) {
		table = 'No Data';
	}		
	
	$('#activitiestable').append(table);
}

function createDelegateTable(data) {
	var table='';
	data.forEach(function(d,i){
		if (i>0) {
			table += '<tr><td>';
			table += d[7];
			table += '</td><td>';
			table += d[5];
			table += '</td><td>';
			table += d[6];
			table += '</td><td>';
			table += d[9];
			table += '<br />';
			table += d[10];
			table += '</td><td>From: ';
			table += d[11];
			table += '<br />Until: ';
			if (d[12].trim().length>0) {
				table += d[12];
			} else {
				table += 'unknown';
			}
			table += '</td></tr>';
		}
	});
	
	if (table.length === 0) {
		table = 'No Data';
	}		

	$('#delegatestable').append(table);
}

function getPNSname(hash) {
	var pnsName = '';
	switch(hash) {
		case 'USA':
			pnsName = 'American+Red+Cross';
			break;
		case 'AUT':
			pnsName = 'Austrian+Red+Cross';
			break;
		case 'BGN':
			pnsName = 'Belgian+Red+Cross+-+Flanders';
			break;
		case 'BGF':
			pnsName = 'Belgian+Red+Cross+-+French+Community';
			break;
		case 'GBR':
			pnsName = 'British+Red+Cross';
			break;
		case 'CAN':
			pnsName = 'Canadian+Red+Cross';
			break;
		case 'DNK':
			pnsName = 'Danish+Red+Cross';
			break;
		case 'FIN':
			pnsName = 'Finnish+Red+Cross';
			break;
		case 'DEU':
			pnsName = 'German+Red+Cross';
			break;
		case 'IRL':
			pnsName = 'Irish+Red+Cross';
			break;
		case 'JPN':
			pnsName = 'Japanese+Red+Cross+Society';
			break;
		case 'LUX':
			pnsName = 'Luxembourg+Red+Cross';
			break;
		case 'NLD':
			pnsName = 'Netherlands+Red+Cross';
			break;
		case 'NOR':
			pnsName = 'Norwegian+Red+Cross';
			break;
		case 'ESP':
			pnsName = 'Spanish+Red+Cross';
			break;
		case 'CHE':
			pnsName = 'Swiss+Red+Cross';
			break;
		case 'SWE':
			pnsName = 'Swedish+Red+Cross';
			break;
		case 'ITA':
			pnsName = 'Italian+Red+Cross';
			break;
		case 'QAT':
			pnsName = 'Qatar+Red+Crescent+Society';
			break;
		case 'FRA':
			pnsName = 'French+Red+Cross';
			break;
		default:
			pnsName = 'unknown';
	}

	return pnsName;
}
//global vars

// Identify for which Partner National Society
var hash = decodeURIComponent(window.location.hash).substring(1);
var patt = new RegExp("^[a-zA-Z]{3}$");
if ( patt.test(hash) ) {
	hash = hash.toUpperCase();
} else {
	hash = "KEN";
}
var pnsName = getPNSname(hash);

var map = '';
var actURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23org%2Bpartner%3D';
actURL +=  pnsName;
actURL += '&filter02=sort&sort-tags02=%23date%2Bstart&sort-reverse02=on&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1pkoD2RJmUoZSuNCXYF49eG3tTdYkHiTrSamQ4LuxgOQ%2Fedit%23gid%3D363150129';

var delURL = 'https://proxy.hxlstandard.org/data.json?filter01=select&select-query01-01=%23org%2Bpartner%3D';
delURL +=  pnsName;
delURL += '&filter02=sort&sort-tags02=%23date%2Bstart&sort-reverse02=on&strip-headers=on&url=https%3A%2F%2Fdocs.google.com%2Fspreadsheets%2Fd%2F1DoVdp0DBZGlPD2JAUVSC9lKYB9dOu6YgmAjE4bd0RkU%2Fedit%23gid%3D2134989124';

$('#page-title').append(': ' + pnsName.replace(/\+/g, " "));

var actCall = $.ajax({
    type: 'GET',
    url: actURL,
    dataType: 'json',
});

var delCall = $.ajax({
    type: 'GET',
    url: delURL,
    dataType: 'json',
});

$.when(actCall, delCall).then(function(actArgs, delArgs){
    createActivityTable(actArgs[0]);
	createDelegateTable(delArgs[0]);
});


