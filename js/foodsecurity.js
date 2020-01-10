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

function loadKeyFigures(url){
    var hxlurl = 'https://proxy.hxlstandard.org/data.json?strip-headers=on&url='+url;
    $.ajax({
            type: 'GET',
            url: hxlurl,
            dataType: 'json',
            success: function(result){
                var data = hxlProxyToJSON(result);
                var html = '<div class="column small-up-2 medium-up-3 large-up-4"><h2>Key Figures</h2>';
                data.forEach(function(d){
                    html+='<div class="column"><div class="card no-border"><h4 class="keyfiguretitle text-center minheight">'+d['#meta+title']+'</h4><p class="keyfigure text-center">'+niceFormatNumber(d['#indicator'])+'</p><p class="small text-center">Source: <a href="'+d['#meta+url']+'" target="_blank">'+d['#meta+source']+'</a></p></div></div>'
                });
                html+='</div>'; //closing div for KF
                $('#keyfigures').html(html);
            }
    });
}

function createAppealsTable(data){
    var html = "";
    data.forEach(function(d,i){
        var url = 'https://ifrcgo.org/appeals/'+d['#meta+id'].toLowerCase()
        html += '<tr><td><a href="'+url+'" target="_blank">'+d['#crisis+name']+'</a></td><td>'+d['#date+start']+'</td><td>'+d['#date+end']+'</td><td style="text-align:right">'+niceFormatNumber(d['#targeted'])+'</td><td style="text-align:right">'+niceFormatNumber(d['#meta+value'])+'</td><td style="text-align:right">'+niceFormatNumber(d['#meta+funding'])+'</td><td id="coverage'+i+'"></td><td><a href="'+url+'" target="_blank">'+d['#meta+id']+'</a></td></tr>';
    });
    $('#appealstable').append(html);
    data.forEach(function(d,i){
        createPie('#coverage'+i,60,10,d['#meta+coverage'].substring(0, d['#meta+coverage'].length - 1)/100);
    });
}

function createPie(id,width,inner,percent){

    console.log(percent);
    var svg = d3.select(id).append("svg")
        .attr("width", width)
        .attr("height", width);

    var radius = width/2;

    var fundingArc = d3.svg.arc()
        .innerRadius(radius-inner)
        .outerRadius(radius)
        .startAngle(0)
        .endAngle(Math.PI*2*percent);

    var budgetArc = d3.svg.arc()
        .innerRadius(radius-inner)
        .outerRadius(radius)
        .startAngle(0)
        .endAngle(Math.PI*2);

    svg.append("path")
        .style("fill", "#dfdfdf")
        .attr("d", budgetArc)
        .attr("transform", "translate("+(width/2)+","+(width/2)+")");

    svg.append("path")
        .style("fill", "#D33F49")
        .attr("d", fundingArc)
        .attr("transform", "translate("+(width/2)+","+(width/2)+")");

    svg.append("text")
        .attr("x",width/2)
        .attr("y",width/2+5)
        .text(d3.format(".0%")(percent))
        .style("text-anchor", "middle");
}

var appeals = ['MDR60003','MDRET016','MDRSO005','MDRKE039'];
var hxlAppealString = '';
appeals.forEach(function(appeal,i){
    hxlAppealString+= '&select-query02-0'+(i+1)+'=%23meta%2Bid%3D'+appeal;
});

var hxlAppealsCallURL = 'https://proxy.hxlstandard.org/data.json?merge-tags03=%23meta%2Bcoverage%2C%23meta%2Bfunding&filter04=replace-map&replace-map-url04=https%3A//docs.google.com/spreadsheets/d/1hTE0U3V8x18homc5KxfA7IIrv1Y9F1oulhJt0Z4z3zo/edit%3Fusp%3Dsharing&merge-keys05=%23country%2Bname&filter03=merge&url=https%3A//docs.google.com/spreadsheets/d/19pBx2NpbgcLFeWoJGdCqECT2kw9O9_WmcZ3O41Sj4hU/edit%23gid%3D0&merge-url05=https%3A//docs.google.com/spreadsheets/d/1GugpfyzridvfezFcDsl6dNlpZDqI8TQJw-Jx52obny8/edit%3Fusp%3Dsharing&merge-keys03=%23meta%2Bid&filter02=select&filter01=clean&strip-headers=on&clean-date-tags01=%23date&force=on&merge-url03=https%3A//docs.google.com/spreadsheets/d/1rVAE8b3uC_XIqU-eapUGLU7orIzYSUmvlPm9tI0bCbU/edit%23gid%3D0&filter05=merge&merge-tags05=%23country%2Bcode'+hxlAppealString;
var hxlDocumentsCallURL = 'https://proxy.hxlstandard.org/data.json?filter02=select&strip-headers=on&url=https%3A//docs.google.com/spreadsheets/d/1gJ4N_PYBqtwVuJ10d8zXWxQle_i84vDx5dHNBomYWdU/edit%3Fusp%3Dsharing'+hxlAppealString;

$.ajax({
    type: 'GET',
    url: hxlAppealsCallURL,
    dataType: 'json',
    success:function(response){
        var data = hxlProxyToJSON(response);
        createAppealsTable(data);
    }
});

$.ajax({
    type: 'GET',
    url: hxlDocumentsCallURL,
    dataType: 'json',
    success:function(response){
        response = hxlProxyToJSON(response);
        appeals.forEach(function(a){
            $('#documents').append('<h3 id="appealname'+a+'" class="documenttitle"></h3><table id="documenttable'+a+'"><tr><th style="text-align:left">Document</th><th width="150" style="text-align:left">Country</th><th width="150" style="text-align:left">Date</th></tr></table>');
            response.forEach(function(d){
                if(d['#meta+id']==a){
                    $('#appealname'+a).html(d['#meta+appealname']);
                    if(d['#meta+url'].substring(0,1)=='/'){
                        d['#meta+url'] = 'https://www.ifrc.org'+d['#meta+url'];
                    }
                    $('#documenttable'+a).append('<tr><td><a href="'+d['#meta+url']+'">'+d['#meta+documentname']+'</a></td><td>'+d['#country']+'</td><td>'+d['#date']+'</td></tr>');
                }
            });
        });
    }
});

//example key figures running off a spreadsheet.
loadKeyFigures('https://docs.google.com/spreadsheets/d/1PwKRHEDkqUfmGDeyLrYwWhO50yfnh2ZHtIyn9W0zgdw/edit?usp=sharing');

/*
Here is a few suggestions:
Maps of countries with open operations.
Overview of:
DREF and Emergency Appeals launched in the four countries - x
Funding level - x
Links to relevant appeal documents - x
Global tools deployed
Operational teams in place
Public documents (joint statement, press release)
Links to appeal plus pages for each operation - x
*/