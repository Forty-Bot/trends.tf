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
    logstat = c.cursor().execute(
        """SELECT
               count(*) AS count,
               min(time) AS earliest
           FROM log""").fetchone()
    (players,) = c.cursor().execute("SELECT count(DISTINCT steamid64) FROM player_stats").fetchone()
    return flask.render_template("index.html", players=players, logstat=logstat)

@root.route('/search')
def search():
    args = flask.request.args
    limit = args.get('limit', 100, int)
    offset = args.get('offset', 0, int)
    q = args.get('q', '', str)

    try:
        steamid = SteamID(q)
        steamid = get_db().cursor().execute(
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
        # Use a CTE here so we can use the results twice. SQLite doesn't optimize the second
        # subselect, so we need to add a WHERE ... IN clause to help it out.
        results = get_db().cursor().execute(
            """WITH results AS (
                   SELECT DISTINCT
                       steamid64,
                       rank,
                       player_name.name AS alias
                   FROM player_name
                   JOIN player_stats ON (player_name.rowid=player_stats.rowid)
                   WHERE player_name MATCH ?
                   ORDER BY rank
               ) SELECT
                   steamid64,
                   name,
                   group_concat(alias, ', ') AS aliases
               FROM results
               JOIN (
                   SELECT
                       steamid64,
                       max(logid) AS newest_logid,
                       name
                   FROM player_stats
                   WHERE steamid64 IN (SELECT steamid64 FROM results)
                   GROUP BY steamid64
               ) USING (steamid64)
               GROUP BY steamid64
               ORDER BY min(rank), newest_logid
               LIMIT ? OFFSET ?;""", ('"{}"'.format(q), limit, offset)).fetchall()
    else:
        error = "Searches must contain at least 3 characters"
    return flask.render_template("search.html", q=q, results=results, error=error, offset=offset,
                                 limit=limit)
