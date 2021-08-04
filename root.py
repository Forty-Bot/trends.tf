# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask
import sqlite3

from common import get_filters
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
               JOIN player_last USING (steamid64)
               JOIN name USING (nameid)
               ORDER BY rank DESC, logid DESC
               LIMIT %s OFFSET %s;""", (q, limit, offset))
        results = results.fetchall()
    else:
        error = "Searches must contain at least 3 characters"
    return flask.render_template("search.html", q=q, results=results, error=error,
                                 offset=offset, limit=limit)

@root.route('/leaderboard')
def leaderboard():
    sort = flask.request.args.get('sort', 'rating', str)
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    filters = get_filters(flask.request.args)

    db = get_db()
    ids = db.cursor()
    ids.execute("""SELECT
                       (SELECT
                               classid
                           FROM class
                           WHERE class = %(class)s
                       ) AS classid,
                       (SELECT
                               formatid
                           FROM format
                           WHERE format = %(format)s
                       ) AS formatid;""", filters)
    ids = ids.fetchone()
    print(ids)
    leaderboard = db.cursor()
    leaderboard.execute("""SELECT
                               name,
                               steamid64,
                               duration,
                               logs,
                               winrate,
                               rating
                           FROM (SELECT
                                   *
                               FROM (SELECT
                                       steamid64,
                                       sum(duration) AS duration,
                                       sum(wins + losses + ties) AS logs,
                                       sum(0.5 * ties + wins) /
                                           sum(wins + losses + ties) AS winrate,
                                       (50 + sum(0.5 * ties + wins)) /
                                           (100 + sum(wins + losses + ties)) AS rating
                                   FROM leaderboard_cube
                                   LEFT JOIN map USING (mapid)
                                   WHERE steamid64 NOTNULL
                                       AND (classid = %(classid)s
                                           OR (%(classid)s ISNULL AND classid ISNULL))
                                       AND (formatid = %(formatid)s
                                           OR (%(formatid)s ISNULL AND formatid ISNULL))
                                       AND (map ILIKE %(map)s
                                           OR (%(map)s ISNULL AND map ISNULL))
                                   GROUP BY steamid64
                               ) AS player_filtered
                               ORDER BY CASE %(sort)s
                                   WHEN 'logs' THEN logs
                                   WHEN 'duration' THEN duration
                                   WHEN 'rating' THEN rating
                               END DESC
                               LIMIT %(limit)s OFFSET %(offset)s
                           ) AS players_sorted
                           LEFT JOIN player_last USING (steamid64)
                           LEFT JOIN name USING (nameid);""",
                           { **filters, **ids, 'sort': sort, 'limit': limit, 'offset': offset })
    return flask.render_template("leaderboard.html", leaderboard=leaderboard.fetchall(),
                                 filters=filters, offset=offset, limit=limit)
