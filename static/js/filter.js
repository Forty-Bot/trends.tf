// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

var maplist = document.getElementById('maps');

function autocomplete_maps() {
	fetch("/api/v1/maps")
		.then(response => {
			if (!response.ok) {
				return {};
			}
			return response.json();
		})
		.then(json => {
			json.maps.forEach(map => {
				option = document.createElement("option");
				option.setAttribute('value', map);
				maplist.append(option);
			});
		})
}
document.getElementById('map_input').addEventListener('focus', autocomplete_maps, {once: true });
