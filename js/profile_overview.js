 function africaStyle(feature){
    return {
	   fillColor:'brown',
	   weight:2,
	   opacity:1,
	   color:'black',
	   dashArray:3,
	   fillOpacity:0.7

           }
		   }


 var map=L.map('map').setView([0,0],10);
 var country_url="https://ifrcgo.org/africa/profile.html#";
/*   L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                }).addTo(map); */
 L.tileLayer('https://data.humdata.org/mapbox-base-tiles/{z}/{x}/{y}.png', {});
 var popup = L.popup();

function showCountryProfile(e){
		var code=e.target.feature.properties.ISO_A3;
		console.log(e.target.feature.properties.ISO_A3);
		window.open(country_url+code,'_blank');
 }

 function showName(e){
	popup
        .setLatLng(e.latlng)
        .setContent(e.target.feature.properties.NAME)
        .openOn(map);
 }
var geojsonMarkerOptions = {
    radius: 8,
    fillColor: "#ff7800",
    color: "#000",
    weight: 1,
    opacity: 1,
    fillOpacity: 0.8
};
 function onEachFeature(feature, layer) {
           layer.on({
				click: showCountryProfile,
				mouseover: showName
			});
        }
	var africaLayer= L.geoJson(africa,{
				style:africaStyle,

                onEachFeature:onEachFeature,

				pointToLayer: function (feature, latlng) {
					return L.circleMarker(latlng, geojsonMarkerOptions);
				}
	}).addTo(map);
	map.fitBounds(africaLayer.getBounds());
	map.zoomIn();
