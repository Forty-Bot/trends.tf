function draw() {
	var data = JSON.parse(d3.select("#trend-data").text());

	function onclick(d) {
		Object.assign(document.createElement('a'), {
			target: '_blank',
			href: `https://logs.tf/${data[d.index].logid}`,
		}).click();
	}

	var pct_format = d3.format(".2%")
	var int_format = d3.format(".0f")
	var tooltip = {
		format: {
			title: function (x, index) {
				return (new Date(data[index].time * 1000)).toLocaleString()
			},
			value: function (value, ratio, id, index) {
				if (['acc', 'winrate', 'round_winrate'].includes(id))
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
			y2: {
				min: 0,
				max: 1,
				padding: 0,
				tick: {
					format: d3.format(".0%"),
				},
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
			value: ['dpm', 'dtm', 'hpm', 'acc'],
		},
		names: {
			dpm: "D/M",
			dtm: "DT/M",
			hpm: "HP/M",
			acc: "Acc",
		},
		axes: {
			dpm: 'y',
			dtm: 'y',
			hpm: 'y',
			acc: 'y2',
		},
		onclick: onclick,
	};
	pm_config.axis.y2.show = true;
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
	kda_config.axis.y2.show = false;
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
}

window.onload = draw