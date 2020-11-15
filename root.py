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
        return flask.redirect(flask.url_for('player.overview', steamid=str(steamid)), 302)
    except ValueError:
        pass

    error = None
    results = []
    results = get_db().cursor().execute(
        """SELECT
               steamid64,
               player_name.name
           FROM player_name
           JOIN player_stats ON (player_name.rowid=player_stats.rowid)
           WHERE player_name MATCH ?
           GROUP BY steamid64
           ORDER BY rank
           LIMIT ? OFFSET ?;""", ('"{}"'.format(q), limit, offset)).fetchall()
    return flask.render_template("search.html", q=q, results=results, error=error, offset=offset,
                                 limit=limit)
