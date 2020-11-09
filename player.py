#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
import flask

from sql import db_connect

app = flask.Flask(__name__)

DATABASE = "logs.db"

@app.template_filter('duration')
def duration_filter(timestamp):
    mm, ss = divmod(timestamp, 60)
    hh, mm = divmod(mm, 60)
    dd, hh = divmod(hh, 24)
    if dd:
        return "{:.0f} day{}, {:.0f}:{:02.0f}:{:02.0f}" \
               .format(dd, "s" if dd > 1 else "", hh, mm, ss)
    elif hh:
        return "{:.0f}:{:02.0f}:{:02.0f}".format(hh, mm, ss)
    else:
        return "{:.0f}:{:02.0f}".format(mm, ss)

@app.template_filter('date')
def date_filter(timestamp):
    return datetime.fromtimestamp(timestamp)

def get_player(c, steamid):
    cur = c.cursor().execute(
        """SELECT
             *,
             (wins + 0.5 * ties) /
                 (wins + losses + ties) AS winrate,
             (round_wins + 0.5 * round_ties) /
                 (round_wins + round_losses + round_ties) AS round_winrate
        FROM (
             SELECT
                 steamid64,
                 last_value(name) OVER (
                     ORDER BY logid
                 ) as name,
                 sum(round_wins) AS round_wins,
                 sum(round_losses) AS round_losses,
                 sum(round_ties) AS round_ties,
                 sum(round_wins > round_losses) AS wins,
                 sum(round_wins < round_losses) AS losses,
                 sum(round_wins == round_losses) AS ties
             FROM log_wlt
             WHERE steamid64 = ?
             GROUP BY steamid64
        );""", (steamid,))

    for row in cur:
        return row
    else:
        flask.abort(404)

def get_logs(c, steamid, limit=100, offset=0):
        return c.cursor().execute(
            """SELECT
                   logid,
                   title,
                   map,
                   classes,
                   round_wins AS wins,
                   round_losses AS losses,
                   round_ties AS ties,
                   format,
                   log.duration,
                   log.kills,
                   log.deaths,
                   log.assists,
                   log.dmg * 60.0 / log.duration AS dpm,
                   log.dt * 60.0 / log.duration AS dtm,
                   total(hits) / total(shots) AS acc,
                   healing * 60.0 / log.duration AS hpm,
                   time
               FROM log_wlt AS log
               JOIN (SELECT
                       logid,
                       steamid64,
                       group_concat(class) OVER (
                           PARTITION BY logid, steamid64
                           ORDER BY duration DESC
                           GROUPS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS classes
                   FROM class_stats
               ) USING (logid, steamid64)
               LEFT JOIN weapon_stats USING (logid, steamid64)
               WHERE steamid64 = ?
               GROUP BY logid
               ORDER BY logid DESC
               LIMIT ? OFFSET ?;""", (steamid, limit, offset))

@app.route('/player/<int:steamid>')
def player_overview(steamid):
    with db_connect(DATABASE) as c:
        return flask.render_template("player/overview.html", player=get_player(c, steamid),
                                     logs=get_logs(c, steamid, limit=25))
