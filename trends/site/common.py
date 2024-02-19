# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import flask

from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination, \
                  last_modified

def logs_last_modified():
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'title', 'formatd', 'mapid', 'time', 'logid',
                                        'updated', 'league')

    db = get_db()
    cur = db.cursor()
    if filters['date_to_ts'] is not None:
        # Postgres doesn't use log_time to filter on date_to_ts so we get a bad plan if date_to_ts
        # is too far in the past (as we end up doing a full scan of log_updated). Give the planner a
        # hint that it should use log_time instead. We pay the price by always reading 1000 rows.
        query = f"""WITH log AS MATERIALIZED (SELECT
                            updated
                        FROM log
                        WHERE TRUE
                            {filter_clauses}
                        ORDER BY updated DESC
                        LIMIT 1000
                    ) SELECT max(updated) FROM log;"""
    else:
        query = f"""SELECT max(updated)
                        FROM log
                        WHERE TRUE
                            {filter_clauses};"""

    cur.execute(query, filters)
    return last_modified(cur.fetchone()[0])

def get_logs(view):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'title', 'format', 'map', 'time', 'logid',
                                        'updated', league='log.league')
    order, order_clause = get_order({
        'logid': "logid",
        'duration': "duration",
        'date': "time",
        'updated': "updated",
	}, 'logid')

    if view == 'players':
        extra_cols = """,
            json_build_object(
                'teamid', CASE WHEN team1_is_red THEN teamid1 ELSE teamid2 END,
                'rgl_teamid', CASE WHEN team1_is_red THEN
                    team1.rgl_teamid
                ELSE
                    team2.rgl_teamid
                END,
                'players', red_players
            ) AS red,
            json_build_object(
                'teamid', CASE WHEN team1_is_red THEN teamid2 ELSE teamid1 END,
                'rgl_teamid', CASE WHEN team1_is_red THEN
                    team2.rgl_teamid
                ELSE
                    team1.rgl_teamid
                END,
                'players', blue_players
            ) AS blue"""

        extra_tables = """
            CROSS JOIN LATERAL (SELECT
                    array_agg(steamid64::TEXT) FILTER (WHERE team = 'Red') AS red_players,
                    array_agg(steamid64::TEXT) FILTER (WHERE team = 'Blue') AS blue_players
                FROM player_stats_backing
                JOIN player USING (playerid)
                WHERE logid = log.logid
            ) AS players
            LEFT JOIN match USING (league, matchid)
            LEFT JOIN team_comp_backing AS team1 ON (
                log.league = 'rgl'
                AND team1.league = 'rgl'
                AND team1.compid = match.compid
                AND team1.teamid = match.teamid1
            ) LEFT JOIN team_comp_backing AS team2 ON (
                log.league = 'rgl'
                AND team2.league = 'rgl'
                AND team2.compid = match.compid
                AND team2.teamid = match.teamid2
            )
            """
    else:
        extra_cols = ""
        extra_tables = ""

    logs = get_db().cursor()
    logs.execute(f"""SELECT
                        logid,
                        time,
                        updated,
                        duration,
                        title,
                        map,
                        format,
                        duplicate_of,
                        demoid,
                        log.league,
                        matchid{extra_cols}
                    FROM log
                    JOIN map USING (mapid)
                    LEFT JOIN format USING (formatid)
                    {extra_tables}
                    WHERE TRUE
                        {filter_clauses}
                    ORDER BY {order_clause}
                    LIMIT %(limit)s OFFSET %(offset)s;""",
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

def get_players(league, compid, teamid, filters, limit=100, offset=0,
                default_order=('name', 'asc')):
    if compid is not None:
        assert teamid is None
        filter_clauses = get_filter_clauses(filters, 'divid', 'primary_classid', 'map', 'time',
                                            'logid')
        filter_clauses += "\nAND compid = %(compid)s"
    elif teamid is not None:
        filter_clauses = get_filter_clauses(filters, 'compid', 'primary_classid', 'map', 'time',
                                            'logid')
        filter_clauses += """\nAND %(teamid)s in (teamid1, teamid2)
                             AND team = CASE WHEN equal(team1_is_red, %(teamid)s = teamid1) THEN
                                 'Red'::TEAM
                             ELSE
                                 'Blue'::TEAM
                             END"""
    else:
        assert False

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
    }, *default_order)

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
