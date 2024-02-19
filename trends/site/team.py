# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

from .common import get_players
from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination, \
                  last_modified
from ..util import leagues

team = flask.Blueprint('team', __name__)

@team.url_value_preprocessor
def get_teamid(endpoint, values):
    flask.g.teamid = values['teamid']

@team.before_request
def get_comp():
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """SELECT
               teamid,
               (array_agg(team_name ORDER BY compid DESC))[1] AS name,
               (array_agg(avatarhash ORDER BY compid DESC))[1] AS avatarhash,
               (array_agg(rgl_teamid ORDER BY compid DESC))[1] AS rgl_teamid,
               max(fetched) AS fetched
           FROM team_comp
           WHERE league = %(league)s AND teamid = %(teamid)s
           GROUP BY league, teamid
           UNION ALL
           SELECT teamid, NULL, NULL, NULL, NULL
           FROM team_comp_backing
           WHERE league = %(league)s AND rgl_teamid = %(teamid)s
           UNION ALL
           SELECT NULL, NULL, NULL, NULL, NULL;""",
        { 'league': flask.g.league, 'teamid': flask.g.teamid })

    flask.g.team = cur.fetchone()
    if flask.g.team['teamid'] is None:
        flask.abort(404)
    elif flask.g.team['teamid'] != flask.g.teamid:
        args = flask.request.args | flask.request.view_args
        args['teamid'] = flask.g.team['teamid']
        return flask.redirect(flask.url_for(flask.request.endpoint, **args), 301)

    # FIXME: not quite accurate when we display logs
    if resp := last_modified(flask.g.team['fetched']):
        return resp

    cur.execute(
        """SELECT
               *,
               (wins + 0.5 * ties) / nullif(wins + losses + ties, 0) AS winrate,
               rounds_won / nullif(rounds_won + rounds_lost, 0) AS round_winrate
           FROM (SELECT
                   total(win) AS wins,
                   total(loss) AS losses,
                   total(tie) AS ties,
                   total(rounds_won) AS rounds_won,
                   total(rounds_lost) AS rounds_lost
               FROM match_wlt
               WHERE league = %s AND teamid = %s
           ) AS wlt;""", (flask.g.league, flask.g.teamid))
    flask.g.team_wlt = cur.fetchone()

def get_matches(league, teamid, filters, order_clause="scheduled DESC", limit=100, offset=0):
    filter_clauses = get_filter_clauses(filters, comp='competition.name', time='scheduled')
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

    matches = get_db().cursor()
    matches.execute(
        """WITH match_semifiltered AS (SELECT
                   match.league,
                   matchid,
                   match.compid,
                   competition.name AS comp,
                   division as div,
                   tier,
                   opponent AS teamid,
                   team_name,
                   round_seq,
                   round,
                   mapids,
                   (SELECT
                           array_agg(map)
                       FROM map
                       JOIN unnest(mapids) AS mapid USING(mapid)
                   ) AS maps,
                   rounds_won AS won,
                   rounds_lost AS lost,
                   forfeit,
                   scheduled,
                   our_team
               FROM match_wlt AS match
               LEFT JOIN div_round USING (league, divid, round_seq)
               LEFT JOIN comp_round USING (league, compid, round_seq)
               JOIN round_name ON (
                   round_name.round_nameid = coalesce(div_round.round_nameid,
                                                      comp_round.round_nameid)
               ) JOIN competition USING (league, compid)
               LEFT JOIN division USING (league, divid)
               LEFT JOIN div_name USING (div_nameid)
               JOIN team_comp AS tc ON (
                   tc.league = match.league
                   AND tc.compid = match.compid
                   AND tc.teamid = match.opponent
               ) WHERE match.league = %(league)s AND match.teamid = %(teamid)s
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
               teamid AS teamid2,
               team_name AS team2,
               won AS score1,
               lost AS score2,
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
                       'score1', CASE WHEN equal(team1_is_red, our_team = 1) THEN
                           red_score
                       ELSE
                           blue_score
                       END,
                       'score2', CASE WHEN equal(NOT team1_is_red, our_team = 2) THEN
                           blue_score
                       ELSE
                           red_score
                       END,
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
        { **filters, 'league': flask.g.league, 'teamid': teamid, 'limit': limit,
          'offset': offset })

    return matches

def get_comps(league, teamid, order_clause="compid DESC", limit=100, offset=0):
    comps = get_db().cursor()
    comps.execute(
        """SELECT
               compid,
               competition.name AS comp,
               division AS div,
               format,
               rgl_teamid,
               team_name,
               wins,
               losses,
               ties,
               (wins + 0.5 * ties) / nullif(wins + losses + ties, 0) AS winrate,
               rounds_won,
               rounds_lost,
               rounds_won::NUMERIC / nullif(rounds_won + rounds_lost, 0) AS round_winrate,
               date_from AS from,
               date_to AS to
           FROM team_comp
           JOIN competition USING (league, compid)
           LEFT JOIN division USING (league, compid, divid)
           LEFT JOIN div_name USING (div_nameid)
           JOIN format USING (formatid)
           JOIN (SELECT
                   league,
                   compid,
                   teamid,
                   sum(win) AS wins,
                   sum(loss) AS losses,
                   sum(tie) AS ties,
                   sum(rounds_won) AS rounds_won,
                   sum(rounds_lost) AS rounds_lost,
                   max(scheduled) AS date_to,
                   min(scheduled) AS date_from
               FROM match_wlt
               GROUP BY league, compid, teamid
           ) AS match USING (league, compid, teamid)
           WHERE league = %s AND teamid = %s
           ORDER BY {}
           LIMIT %s OFFSET %s;""".format(order_clause), (league, teamid, limit, offset))

    return comps

@team.route('/')
def overview(league, teamid):
    db = get_db()
    roster = db.cursor()
    roster.execute(
        """SELECT
               steamid64,
               avatarhash,
               name,
               lower(rostered) AS joined
           FROM team_player
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           WHERE league = %s
               AND teamid = %s
               AND (league_team_per_comp(league) OR compid ISNULL)
               AND upper(rostered) ISNULL
           ORDER BY lower(rostered);""", (league, teamid))

    old_roster = db.cursor()
    old_roster.execute(
        """SELECT
               steamid64,
               avatarhash,
               name,
               lower(rostered) AS joined,
               upper(rostered) AS left
           FROM (SELECT
                   playerid,
                   range_max(rostered) AS rostered
               FROM team_player
               WHERE league = %s
                   AND teamid = %s
                   AND (league_team_per_comp(league) OR compid ISNULL)
               GROUP BY league, compid, teamid, playerid
               HAVING upper(range_max(rostered)) NOTNULL
           ) AS team_player
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           ORDER BY upper(rostered) DESC
           LIMIT 10;""", (league, teamid))

    comps = get_comps(league, teamid, limit=10)
    matches = get_matches(league, teamid, get_filter_params(), limit=25)

    return flask.render_template("league/team/overview.html", roster=roster, old_roster=old_roster,
                                 comps=comps, matches=matches)

@team.route('/roster')
def roster(league, teamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'playerid', date_range='rostered')
    order, order_clause = get_order({
        'newer': "greatest(lower(rostered), upper(rostered))",
        'older': "least(lower(rostered), upper(rostered))",
        'from': "lower(rostered)",
        'to': "upper(rostered)",
    }, 'newer')

    db = get_db()
    roster = db.cursor()
    roster.execute(
        """SELECT
               compid,
               competition.name AS comp,
               steamid64,
               name.name,
               avatarhash,
               lower(rostered) AS from,
               upper(rostered) AS to
           FROM team_player
           LEFT JOIN competition USING (league, compid)
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           WHERE league=%(league)s AND teamid=%(teamid)s
               {}
           ORDER BY {}
           LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
       { **filters, 'league': league, 'teamid': teamid, 'limit': limit, 'offset': offset })

    return flask.render_template("league/team/roster.html", roster=roster.fetchall())

@team.route('/comps')
def comps(league, teamid):
    limit, offset = get_pagination()
    order, order_clause = get_order({
        'compid': "compid",
        'from': "date_from",
        'to': "date_to",
    }, 'compid')

    comps = get_comps(league, teamid, order_clause, limit, offset)

    return flask.render_template("league/team/comps.html", comps=comps.fetchall())

def get_comp_list(league, teamid):
    comps = get_db().cursor()
    comps.execute(
        """SELECT name
           FROM team_comp
           JOIN competition USING (league, compid)
           WHERE league = %s AND teamid = %s;
        """, (league, teamid));

    return comps

@team.route('/matches')
def matches(league, teamid):
    limit, offset = get_pagination()
    order, order_clause = get_order({
        'round': "round_seq",
        'date': "scheduled",
        'matchid': "matchid",
    }, 'date')

    comps = get_comp_list(league, teamid)
    matches = get_matches(league, teamid, get_filter_params(), order_clause, limit, offset)

    return flask.render_template("league/team/matches.html", matches=matches.fetchall(),
                                 comps=comps)

@team.route('/players')
def players(league, teamid):
    limit, offset = get_pagination()
    filters = get_filter_params()

    comps = get_comp_list(league, teamid)
    players = get_players(league, None, teamid, filters, limit, offset,
                          default_order=('duration', 'desc'))

    return flask.render_template("league/team/players.html", players=players.fetchall(),
                                 comps=comps)
