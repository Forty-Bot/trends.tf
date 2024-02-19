// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

var date_formatter = new Intl.DateTimeFormat('und', {dateStyle: 'medium'});
var datetime_formatter = new Intl.DateTimeFormat('und', {dateStyle: 'medium', timeStyle: 'short'});

document.addEventListener('DOMContentLoaded', () => {
	for (date of document.getElementsByClassName("datetime"))
		date.textContent = datetime_formatter.format(
			new Date(date.getAttribute('timestamp') * 1000));

	for (date of document.getElementsByClassName("date"))
		date.textContent = date_formatter.format(
			new Date(date.getAttribute('timestamp') * 1000));
});

document.addEventListener('DOMContentLoaded', () => {
	let timezone = document.getElementById('timezone');
	if (timezone) {
		timezone.value = datetime_formatter.resolvedOptions().timeZone;
	}
});
