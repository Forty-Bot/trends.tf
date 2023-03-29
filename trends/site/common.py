# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import flask

from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination, \
                  last_modified

def logs_last_modified():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT max(time) FROM log;")
    return last_modified(cur.fetchone()[0])

def get_logs():
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'title', 'format', 'map', 'time', 'logid')
    order, order_clause = get_order({
        'logid': "logid",
        'duration': "duration",
        'date': "time",
	}, 'logid')
    logs = get_db().cursor()
    logs.execute("""SELECT
                        logid,
                        time,
                        duration,
                        title,
                        map,
                        format,
                        duplicate_of
                    FROM log
                    JOIN map USING (mapid)
                    LEFT JOIN format USING (formatid)
                    WHERE TRUE
                        {}
                    ORDER BY {}
                    LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
                { **filters, 'limit': limit, 'offset': offset })
    return logs

def get_players(q):
    if len(q) < 3:
        flask.abort(400, "Searches must contain at least 3 characters")

    limit, offset = get_pagination(limit=25)
    results = get_db().cursor()
    results.execute(
        """SELECT
               steamid64::TEXT,
               name,
               avatarhash,
               aliases
           FROM (SELECT
                   playerid,
                   array_agg(DISTINCT name) AS aliases,
                   max(rank) AS rank
               FROM (SELECT
                       playerid,
                       name,
                       similarity(name, %(q)s) AS rank
                   FROM name
                   JOIN player_stats USING (nameid)
                   WHERE name ILIKE %(q)s
                   ORDER BY rank DESC
               ) AS matches
               GROUP BY playerid
           ) AS matches
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           WHERE last_active NOTNULL
           ORDER BY rank DESC, last_active DESC
           LIMIT %(limit)s OFFSET %(offset)s;""",
        { 'q': "%{}%".format(q), 'limit': limit, 'offset': offset})
    return results
