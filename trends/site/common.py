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
    filter_clauses = get_filter_clauses(filters, 'title', 'league', 'format', 'map', 'time',
                                        'logid')
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
                        duplicate_of,
                        demoid,
                        league,
                        matchid
                    FROM log
                    JOIN map USING (mapid)
                    LEFT JOIN format USING (formatid)
                    WHERE TRUE
                        {}
                    ORDER BY {}
                    LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
                { **filters, 'limit': limit, 'offset': offset })
    return logs

def search_players(q):
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

def get_matches(compid, filters, limit=100, offset=0):
    if compid is None:
        filter_clauses = get_filter_clauses(filters, 'comp', 'divid', time='scheduled')
    else:
        filter_clauses = get_filter_clauses(filters, 'divid', time='scheduled')
        filter_clauses += "\nAND compid = %(compid)s"
    if filters['map']:
        maps = """JOIN (SELECT
                          mapid
                      FROM (SELECT
                              unnest(mapids) AS mapid
                          FROM match_semifiltered
                          GROUP BY mapid
                      ) AS maps
                      JOIN map USING (mapid)
                      WHERE map ILIKE %(map)s
                  ) AS maps ON (mapid = ANY(mapids))"""
    else:
        maps = ""
    order, order_clause = get_order({
        'round': "round_seq",
        'date': "scheduled",
        'matchid': "matchid",
    }, 'date')

    matches = get_db().cursor()
    matches.execute(
        """WITH match_semifiltered AS (SELECT *
               FROM match_pretty
               WHERE league = %(league)s
                   {0}
           ), match AS MATERIALIZED (SELECT *
               FROM match_semifiltered
               {1}
               ORDER BY {2} NULLS LAST, compid DESC, tier ASC, matchid DESC
               LIMIT %(limit)s OFFSET %(offset)s
           ) SELECT
               matchid,
               comp,
               compid,
               div,
               round,
               teamid1,
               teamid2,
               team1,
               team2,
               score1,
               score2,
               forfeit,
               maps,
               scheduled,
               logs
           FROM match
           LEFT JOIN LATERAL (SELECT
                   league,
                   matchid,
                   json_object_agg(logid, json_build_object(
                       'logid', logid,
                       'time', time,
                       'title', title,
                       'map', map,
                       'score1', CASE WHEN team1_is_red THEN red_score ELSE blue_score END,
                       'score2', CASE WHEN team1_is_red THEN blue_score ELSE red_score END,
                       'demoid', demoid
                   ) ORDER BY time DESC) AS logs
               FROM log_nodups
               LEFT JOIN format USING (formatid)
               JOIN map USING (mapid)
               WHERE league=match.league AND matchid=match.matchid
               GROUP BY league, matchid
           ) AS log USING (league, matchid)
           ORDER BY {2} NULLS LAST, compid DESC, tier ASC, matchid DESC;"""
        .format(filter_clauses, maps, order_clause),
        { **filters, 'league': flask.g.league, 'compid': compid, 'limit': limit,
          'offset': offset })
    return matches

def get_players(league, compid, filters, limit=100, offset=0):
    filter_clauses = get_filter_clauses(filters, 'divid', 'primary_classid', 'map', 'time', 'logid')
    filter_clauses += "\nAND compid = %(compid)s"

    order, order_clause = get_order({
        'name': "name",
        'k30': "k30",
        'd30': "d30",
        'a30': "a30",
        'kd': "kd",
        'kad': "kad",
        'dpm': "dpm",
        'dtm': "dtm",
        'ddm': "ddm",
        'dr': "dr",
        'acc': "acc",
        'dps': "dps",
        'kills': "kills",
        'deaths': "deaths",
        'assists': "assists",
        'dmg': "dmg",
        'dt': "dt",
        'duration': "duration",
    }, 'name', 'asc')

    players = get_db().cursor()
    players.execute(
        """SELECT
               steamid64,
               avatarhash,
               name,
               (SELECT json_object_agg(class, d * 1.0 / duration ORDER BY d DESC)
                FROM unnest(classes, durations) AS c(class, d)) AS classes,
               kills * 30.0 * 60 / duration AS k30,
               deaths * 30.0 * 60 / duration AS d30,
               assists * 30.0 * 60 / duration AS a30,
               kills * 1.0 / nullif(deaths, 0) AS kd,
               (kills + assists) * 1.0 / nullif(deaths, 0) AS kad,
               dmg * 60.0 / duration AS dpm,
               dt * 60.0 / duration AS dtm,
               (dmg - dt) * 60.0 / duration AS ddm,
               dmg * 1.0 / nullif(dt, 0) AS dr,
               hits * 1.0 / nullif(shots, 0) AS acc,
               dmg * 1.0 / nullif(shots, 0) AS dps,
               kills,
               deaths,
               assists,
               dmg,
               dt,
               duration
           FROM(SELECT
                   playerid,
                   sum(kills) AS kills,
                   sum(deaths) AS deaths,
                   sum(assists) AS assists,
                   sum(dmg) AS dmg,
                   sum(dt) AS dt,
                   sum(hits) AS hits,
                   sum(shots) AS shots,
                   sum(duration) AS duration,
                   array_agg(class ORDER BY duration DESC) AS classes,
                   array_agg(duration ORDER BY duration DESC) AS durations
               FROM (SELECT
                       playerid,
                       primary_classid AS classid,
                       sum(kills) AS kills,
                       sum(deaths) AS deaths,
                       sum(assists) AS assists,
                       sum(dmg) AS dmg,
                       sum(dt) AS dt,
                       sum(hits) AS hits,
                       sum(shots) AS shots,
                       sum(duration) AS duration
                   FROM match
                   JOIN log USING (league, matchid)
                   JOIN player_stats USING (logid)
                   JOIN map USING (mapid)
                   WHERE league = %(league)s
                       {}
                   GROUP BY playerid, primary_classid
               ) AS player_stats
               JOIN class USING (classid)
               GROUP BY playerid
           ) AS player_stats
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           ORDER BY {} NULLS LAST
           LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
        { **filters, 'league': league, 'compid': compid, 'teamid': teamid, 'limit': limit,
          'offset': offset })

    return players
