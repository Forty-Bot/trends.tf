// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

var maplist = document.getElementById('maps');

function unwrap_json(response) {
	if (!response.ok) {
		return {};
	}
	return response.json();
}

document.addEventListener('DOMContentLoaded', () => {
	document.getElementById('map_input').addEventListener('focus', () => {
		fetch("/api/v1/maps").then(unwrap_json).then(json => {
			json.maps.forEach(map => {
				option = document.createElement("option");
				option.setAttribute('value', map);
				maplist.append(option);
			});
		});
	}, {once: true });
});

function render_option(data, escape) {
	div = document.createElement('div');
	img = document.createElement('img');
	img.classList.add('avatar_small');
	img.setAttribute('src', "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/" +
	                        `avatars/${data.avatarhash.slice(0, 2)}/${data.avatarhash}.jpg`);
	div.append(img, " ", data.name);
	return div;
}

document.addEventListener('DOMContentLoaded', () => {
	new TomSelect(document.getElementById('players_input'), {
		plugins: ['remove_button'],
		maxItems: 5,
		valueField: 'steamid64',
		labelField: 'name',
		searchField: ['aliases', 'name'],
		load: (query, callback) => {
			fetch(`/api/v1/players?q=${query}`)
				.then(unwrap_json)
				.then(json => {
					callback(json.players);
				});
		},
		shouldLoad: query => query.length > 3,
		render: {
			item: render_option,
			option: render_option,
		},
	});
})
