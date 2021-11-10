// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

var time_formatter = new Intl.DateTimeFormat('und', {dateStyle: 'medium', timeStyle: 'short'});

function format_dates() {
	for (date of document.getElementsByClassName("date"))
		date.textContent = time_formatter.format(
			new Date(date.getAttribute('timestamp') * 1000));
}
document.addEventListener('DOMContentLoaded', format_dates);

function set_timezone() {
	var timezone = document.getElementById('timezone');
	if (timezone) {
		timezone.value = time_formatter.resolvedOptions().timeZone;
	}
}
document.addEventListener('DOMContentLoaded', set_timezone);
