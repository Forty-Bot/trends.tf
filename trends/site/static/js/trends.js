// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

document.addEventListener('DOMContentLoaded', () => {
	const data = JSON.parse(document.getElementById("trend-data").textContent);

	const color_orange = '#CF7336';
	const color_purple = '#7D4071';
	const color_green = '#729E42';
	const color_blue = '#2F4F4F';

	function open_log(logid) {
		Object.assign(document.createElement('a'), {
			target: '_blank',
			href: `/log?id=${logid}#${steamid64}`,
		}).click();
	}

	function create_title(context) {
		return time_formatter.format(new Date(data[context[0].dataIndex].time * 1000));
	}

	function create_label(context, format) {
		return context.dataset.label + ": " + format(context.raw);
	}

	function create_footer(context) {
		context[0].chart.selectLogid = data[context[0].dataIndex].logid;
		return "Logid: " + data[context[0].dataIndex].logid;
	}

	const pm_format = (value) => parseFloat(value).toFixed(0);
	const kda_format = (value) => parseFloat(value).toFixed(1);
	const wr_format = (new Intl.NumberFormat('en-us', {
		style: 'percent',
		minimumFractionDigits: 2,
		maximumFractionDigits: 2
	})).format;

	const base_config = (format) => ({
		type: 'line',
		// Keep track of the last hovered over logid so the onClick works
		selectLogid: -1,
		options: {
			// Don't keep the aspect ratio since we're limiting the amount of space
			// on the y axis quite a bit
			maintainAspectRatio: false,
			animation: false,
			plugins: {
				tooltip: {
					callbacks: {
						title: create_title,
						label: (context) =>
							create_label(context, format),
						footer: create_footer
					}
				}
			},
			elements: {
				line: {
					borderWidth: 1,
				},
				point: {
					pointRadius: 0.5
				}
			},
			scales: {
				y: {
					ticks: {
						// Make sure we format the values for the y-axis as well
						callback : function (value) {
							return format(value);
						}
					}
				},
			},
			// When hovering over values we want to select all points over all datasets
			interaction: {
				mode: 'index',
				intersect: false
			},
			// Open a new tab with the logid on logs.tf
			onClick: function (test) {
				if (test.chart.selectLogid > 0)
					open_log(test.chart.selectLogid)
			},
			// Display a pointer cursor when hovering over the graph
			// so people know they can click on it
			onHover: (event, chartElement) => {
				if (chartElement[0])
					event.native.target.style.cursor = 'pointer';
				else
					event.native.target.style.cursor = 'default';
			}
		}
	});

	const pm_config = {...base_config(pm_format)};
	pm_config.data = {
		labels: [...Array(data.length).keys()],
		datasets: [{
			data: data.map((value) => value.dpm),
			label: "D/M",
			borderColor: color_orange,
			backgroundColor: color_orange
		}, {
			data: data.map((value) => value.dtm),
			label: "DT/M",
			borderColor: color_purple,
			backgroundColor: color_purple
		}, {
			data: data.map((value) => value.hpm_given),
			label: "HG/M",
			borderColor: color_green,
			backgroundColor: color_green
		}, {
			data: data.map((value) => value.hpm_recieved),
			label: "HR/M",
			borderColor: color_blue,
			backgroundColor: color_blue
		}],
	};
	new Chart(document.getElementById("pm-chart"), pm_config);

	const kda_config = {...base_config(kda_format)};
	kda_config.data = {
		labels: [...Array(data.length).keys()],
		datasets: [{
			data: data.map((value) => value.kills),
			label: "K/30",
			borderColor: color_orange,
			backgroundColor: color_orange
		}, {
			data: data.map((value) => value.deaths),
			label: "D/30",
			borderColor: color_purple,
			backgroundColor: color_purple
		}, {
			data: data.map((value) => value.assists),
			label: "A/30",
			borderColor: color_green,
			backgroundColor: color_green
		}],
	};
	new Chart(document.getElementById("kda-chart"), kda_config);

	const wr_config = {...base_config(wr_format)};
	wr_config.data = {
		labels: [...Array(data.length).keys()],
		datasets: [{
			data: data.map((value) => value.winrate),
			label: "WR",
			borderColor: color_orange,
			backgroundColor: color_orange
		}, {
			data: data.map((value) => value.round_winrate),
			label: "Round WR",
			borderColor: color_purple,
			backgroundColor: color_purple
		}],
	};
	new Chart(document.getElementById("wr-chart"), wr_config);
});
