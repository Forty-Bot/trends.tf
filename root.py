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
        cur = get_db().cursor()
        cur.execute(
            """SELECT steamid64
               FROM player_stats
               WHERE steamid64 = %s
               LIMIT 1""", (steamid,))
        for (steamid,) in cur:
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
                   name AS name,
                   aliases
               FROM (SELECT
                       steamid64,
                       array_agg(DISTINCT name) AS aliases,
                       max(rank) AS rank
                   FROM (SELECT
                           steamid64,
                           name,
                           ts_rank(name_vector, query) AS rank
                       FROM (SELECT
                               nameid,
                               name,
                               to_tsvector('english', name) AS name_vector
                           FROM name
                       ) AS name
                       JOIN (SELECT
                               phraseto_tsquery('english', %s) AS query
                       ) AS query ON (TRUE)
                       JOIN player_stats USING (nameid)
                       WHERE query @@ name_vector
                       ORDER BY rank DESC
                   ) AS matches
                   GROUP BY steamid64
               ) AS matches
               JOIN player USING (steamid64)
               JOIN name ON (name.nameid=last_nameid)
               ORDER BY rank DESC, last_logid
               LIMIT %s OFFSET %s;""", (q, limit, offset))
        results = results.fetchall()
    else:
        error = "Searches must contain at least 3 characters"
    return flask.render_template("search.html", q=q, results=results, error=error,
                                 offset=offset, limit=limit)
