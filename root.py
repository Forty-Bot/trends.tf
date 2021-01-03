# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask
import sqlite3

from sql import get_db
from steamid import SteamID

root = flask.Blueprint('root', __name__)

@root.route('/')
def index():
    c = get_db()
    logstat = c.cursor()
    logstat.execute(
        """SELECT
               count(*) AS count,
               max(time) AS newest,
               min(time) AS oldest
           FROM log;""")
    players = c.cursor()
    players.execute("SELECT count(*) AS players FROM player;")
    return flask.render_template("index.html", logstat=logstat.fetchone(),
                                 players=players.fetchone()[0])

@root.route('/search')
def search():
    args = flask.request.args
    limit = args.get('limit', 25, int)
    offset = args.get('offset', 0, int)
    q = args.get('q', '', str)

    try:
        steamid = SteamID(q)
        steamid = get_db().cursor()
        steamid.execute(
            """SELECT steamid64
               FROM player_stats
               WHERE steamid64 = ?
               LIMIT 1""", (steamid,))
        for (steamid,) in steamid:
            return flask.redirect(flask.url_for('player.overview', steamid=steamid), 302)
    except ValueError:
        pass

    error = None
    results = []
    if len(q) >= 3:
        results = get_db().cursor()
        results.execute(
            """SELECT
                   steamid64,
                   name,
                   aliases
               FROM (
                   SELECT
                       steamid64,
                       min(rank) AS rank,
                       group_concat(DISTINCT name) AS aliases
                   FROM name_fts AS n
                   JOIN player_stats AS ps ON (ps.nameid=n.rowid)
                   WHERE name_fts MATCH ?
                   GROUP BY steamid64
                   ORDER BY rank
               ) JOIN player USING (steamid64)
               JOIN name ON (name.nameid=last_nameid)
               ORDER BY rank, last_logid
               LIMIT ? OFFSET ?;""", ('"{}"'.format(q), limit, offset))
    else:
        error = "Searches must contain at least 3 characters"
    return flask.render_template("search.html", q=q, results=results.fetchall(), error=error,
                                 offset=offset, limit=limit)
