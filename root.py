# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask
import sqlite3

from common import get_filters, filter_clauses
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

    # This factor controls how much we weight the expected winrate for each player
    # Increasing this factor will cause players with low numbers of logs to be rated closer to m
    # This should be approximately the average number of logs per player
    C = 100
    # The expected winrate
    m = 0.5

    filters = get_filters(flask.request.args)
    leaderboard = get_db().cursor()
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
                                       duration,
                                       logs,
                                       (0.5 * ties + wins) / (logs) AS winrate,
                                       (%(C)s * %(m)s + 0.5 * ties + wins) /
                                           (%(C)s + logs) AS rating
                                   FROM (SELECT
                                           steamid64,
                                           sum(round_wlt.duration) AS duration,
                                           sum((wins > losses)::INT) AS wins,
                                           sum((wins = losses)::INT) AS ties,
                                           count(*) AS logs
                                       FROM round_wlt
                                       LEFT JOIN log USING (logid)
                                       LEFT JOIN format USING (formatid)
                                       LEFT JOIN map USING (mapid)
                                       -- Hack to avoid joining this table if we don't filter
                                       LEFT JOIN (SELECT
                                               logid,
                                               steamid64,
                                               classid
                                           FROM class_stats
                                           WHERE %(class)s NOTNULL
                                       ) AS class_stats USING (logid, steamid64)
                                       LEFT JOIN class USING (classid)
                                       WHERE TRUE
                                           {}
                                       GROUP BY steamid64
                                   ) AS player_wlt
                               ) AS player_filtered
                               ORDER BY CASE %(sort)s
                                   WHEN 'logs' THEN logs
                                   WHEN 'duration' THEN duration
                                   WHEN 'rating' THEN rating
                               END DESC
                               LIMIT %(limit)s OFFSET %(offset)s
                           ) AS players_sorted
                           LEFT JOIN player_last USING (steamid64)
                           LEFT JOIN name USING (nameid);""".format(filter_clauses),
                           { 'C': C, 'm': m, **filters, 'sort': sort, 'limit': limit,
                             'offset': offset })
    return flask.render_template("leaderboard.html", leaderboard=leaderboard.fetchall(),
                                 filters=filters, offset=offset, limit=limit)
