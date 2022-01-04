// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

function colspan(element) {
	return Number(element.attributes.getNamedItem('colspan')?.value);
}

function cell_value(row, column) {
	let i = 0;
	let cell;
	for (let td of row.children) {
		cs = colspan(td) || 1;
		if (column >= i && column < i + cs) {
			cell = td;
			break;
		}
		i += cs;
	}

	return cell.dataset.value || cell.innerText || cell.textContent;
}

function comparer(column, asc) {
	console.log(column, asc);
	function compare(a, b) {
		a = cell_value(a, column);
		b = cell_value(b, column);
		if (a !== '' && b !== '' && !isNaN(a) && !isNaN(b)) {
			return a - b;
		} else if (Array.isArray(a) && Array.isArray(b)) {
			if (a > b) {
				return 1;
			} else if (a < b) {
				return -1;
			}
			return 0;
		}
		return a.toString().localeCompare(b);
	}

	if (asc) {
		return compare;
	}
	return (a, b) => compare(b, a);
}

function sort_rows(rows, insert, column, asc, reverse) {
	let fixed = {};

	rows = Array.from(rows).filter((row, index) => {
		if (row.classList.contains('padding-row') ||
		    row.classList.contains('subhead')) {
			fixed[index] = row;
			return false;
		}
		return true;
	}).sort(comparer(column, asc));

	Object.keys(fixed).sort().forEach(index => {
		rows.splice(index, 0, fixed[index]);
	});

	if (reverse) {
		rows.reverse();
	}

	rows.forEach(row => {
		insert(row);
		sort_rows(document.getElementsByClassName(row.id),
			  subrow => row.after(subrow),
			  column, asc, true);
	});
}

function register_sort(table, header) {
	let column = 0;
	for (th of header.parentNode.children) {
		if (th === header) {
			break;
		}
		column += colspan(th) || 1;
	}

	var asc = true;
	const selector = "tr:not(.padding-row):not(.hidable):not(.hidable2)";
	header.addEventListener('click', () => {
		Array.from(table.tBodies).forEach(body => {
			sort_rows(body.querySelectorAll(selector),
				  row => body.appendChild(row),
				  column, asc = !asc, false);
		});

		Array.from(table.getElementsByTagName('th')).forEach(th => {
			th.classList.remove('asc');
			th.classList.remove('desc');
		});

		if (asc) {
			header.classList.add('asc');
		} else {
			header.classList.add('desc');
		}
	});
}

document.addEventListener('DOMContentLoaded', () => {
	Array.from(document.getElementsByClassName('sortable')).forEach(sortable => {
		Array.from(sortable.getElementsByTagName('th'))
			.forEach(header => register_sort(sortable.closest('table'), header));
	});
});
