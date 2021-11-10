// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

function update_checkboxes() {
	var checked = 0;
	checkboxes = document.getElementsByClassName("combine");
	for (let checkbox of checkboxes) {
		if (checkbox.checked) {
			checked++;
		}
	}

	if (checked >= 5) {
		for (let checkbox of checkboxes) {
			if (!checkbox.checked) {
				checkbox.disabled = true;
			}
		}
	} else {
		for (let checkbox of checkboxes) {
			if (!checkbox.checked) {
				checkbox.disabled = false;
			}
		}
	}
}

function register_checkboxes() {
	checkboxes = document.getElementsByClassName("combine");
	for (let checkbox of checkboxes) {
		checkbox.addEventListener('change', update_checkboxes);
	}
	update_checkboxes();
}
document.addEventListener('DOMContentLoaded', register_checkboxes);
