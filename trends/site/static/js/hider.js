// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

/**
 * update_hidden() - Update hidden rows after a click
 * @hider - The row which was clicked
 * @hide - Whether to unconditionally hide rows, or toggle them
 * @recursive - Whether to recurse into child rows
 */
function update_hidden(hider, hide, recursive) {
	if (hide) {
		hider.classList.add('hiding');
	} else {
		hider.classList.toggle('hiding');
	}

	let elements = document.getElementsByClassName(hider.id);
	for (let element of elements) {
		let hidden = true;
		if (hide) {
			element.classList.add('hidden');
		} else {
			hidden = element.classList.toggle('hidden');
		}

		if ((hidden || recursive) && element.classList.contains("hider")) {
			update_hidden(element, hidden);
		}
	}
}

document.addEventListener('DOMContentLoaded', () => {
	let hiders = document.getElementsByClassName("hider");
	for (let hider of hiders) {
		hider.addEventListener('click', function (evt) {
			if (evt.target.tagName == "A")
				return
			update_hidden(evt.currentTarget, false);
		});
	}

	let target = document.getElementById(window.location.hash.substring(1));
	if (target && target.classList.contains("hider")) {
		update_hidden(target, false, true);
		target.scrollIntoView({
			block: 'center',
		});
	}
});
