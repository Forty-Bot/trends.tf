// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

function update_hidden(hider, hide) {
	elements = document.getElementsByClassName(hider.id);
	for (let element of elements) {
		hidden = true;
		if (hide) {
			element.classList.add('hidden');
		} else {
			hidden = element.classList.toggle('hidden');
		}

		if (hidden && element.classList.contains("hider")) {
			update_hidden(element, hidden);
		}
	}
}

function register_hiders() {
	hiders = document.getElementsByClassName("hider");
	for (let hider of hiders) {
		hider.addEventListener('click', function (evt) {
			update_hidden(evt.currentTarget, false);
		});
	}
}
document.addEventListener('DOMContentLoaded', register_hiders);
