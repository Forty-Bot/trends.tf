// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

document.addEventListener('DOMContentLoaded', () => {
	var data = JSON.parse(d3.select("#trend-data").text());

	function onclick(d) {
		Object.assign(document.createElement('a'), {
			target: '_blank',
			href: `https://logs.tf/${data[d.index].logid}`,
		}).click();
	}

	var pct_format = d3.format(".2%");
	var int_format = d3.format(".0f");
	var tooltip = {
		format: {
			title: function (x, index) {
				return time_formatter.format(new Date(data[index].time * 1000));
			},
			value: function (value, ratio, id, index) {
				if (['winrate', 'round_winrate'].includes(id))
					return pct_format(value);
				else
					return int_format(value);
			},
		},
	};

	var base_config = {
		color: {
			pattern: ['#CF7336', '#7D4071', '#729E42', '#2F4F4F'],
		},
		axis: {
			x: {
				tick: {
					fit: false,
					count: 50,
					format: d3.format(".0f"),
				},
			},
			y: {
				min: 0,
				padding: 0,
			},
		},
		tooltip: tooltip,
		point: {
			show: false,
		},
	};

	pm_config = {...base_config};
	pm_config.bindto = '#pm-chart';
	pm_config.data = {
		json: data,
		keys: {
			value: ['dpm', 'dtm', 'hpm'],
		},
		names: {
			dpm: "D/M",
			dtm: "DT/M",
			hpm: "HP/M",
		},
		onclick: onclick,
	};
	c3.generate(pm_config);

	kda_config = {...base_config};
	kda_config.bindto = '#kda-chart';
	kda_config.data = {
		json: data,
		keys: {
			value: ['kills', 'deaths', 'assists'],
		},
		names: {
			kills: "Kills",
			deaths: "Deaths",
			assists: "Assists",
		},
		onclick: onclick,
	};
	c3.generate(kda_config);

	wr_config = {...base_config};
	wr_config.bindto = '#wr-chart';
	wr_config.data = {
		json: data,
		keys: {
			value: ['winrate', 'round_winrate'],
		},
		names: {
			winrate: "WR",
			round_winrate: "Round WR",
		},
		onclick: onclick,
	};
	wr_config.axis.y.max = 1;
	wr_config.axis.y.tick = {
		format: d3.format(".0%"),
	};
	c3.generate(wr_config);
})
