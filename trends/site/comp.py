# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

from .common import get_matches
from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination
from ..util import leagues

comp = flask.Blueprint('comp', __name__)

@comp.url_value_preprocessor
def get_compid(endpoint, values):
    flask.g.compid = values['compid']

@comp.before_request
def get_comp():
    db = get_db()
    comp = db.cursor()
    comp.execute(
        """SELECT
               name,
               format
           FROM competition
           JOIN format USING (formatid)
           WHERE league = %s AND compid = %s;""", (flask.g.league, flask.g.compid))
    flask.g.comp = comp.fetchone()
    if flask.g.comp is None:
        flask.abort(404)

    divs = db.cursor()
    divs.execute(
        """SELECT json_object_agg(divid, division ORDER BY tier ASC, division DESC)
           FROM division
           JOIN div_name USING (div_nameid)
           WHERE league=%s AND compid=%s;""", (flask.g.league, flask.g.compid))
    flask.g.divs = divs.fetchone()[0] or {}

@comp.route('/')
def overview(league, compid):
    db = get_db()
    divs = db.cursor()
    divs.execute(
        """SELECT
               divid,
               division AS name,
               teams
           FROM (SELECT
                   league,
                   compid,
                   divid,
                   array_agg(json_build_object(
                       'teamid', teamid,
                       'name', team_name,
                       'avatarhash', avatarhash,
                       'wins', wins,
                       'losses', losses,
                       'ties', ties,
                       'winrate', (wins + 0.5 * ties) / nullif(wins + losses + ties, 0),
                       'rounds_won', rounds_won,
                       'rounds_lost', rounds_lost,
                       'round_winrate', rounds_won / nullif(rounds_won + rounds_lost, 0)
                   ) ORDER BY wins + 0.5 * ties DESC,
                              rounds_won / (rounds_lost + 1) DESC,
                              team_name) AS teams
               FROM team_comp
               JOIN (SELECT
                       league,
                       compid,
                       teamid,
                       total(win) AS wins,
                       total(loss) AS losses,
                       total(tie) AS ties,
                       total(rounds_won) AS rounds_won,
                       total(rounds_lost) AS rounds_lost
                   FROM match_wlt
                   GROUP BY league, compid, teamid
               ) AS match USING (league, compid, teamid)
               GROUP BY league, compid, divid
           ) AS teams
           LEFT JOIN division USING (league, compid, divid)
           LEFT JOIN div_name USING (div_nameid)
           WHERE league = %s AND compid = %s
           ORDER BY tier ASC, divid ASC;""", (league, compid))

    matches = get_matches(compid, get_filter_params(), limit=25)

    return flask.render_template("league/comp/overview.html", divs=divs, matches=matches)

@comp.route('/matches')
def matches(league, compid):
    limit, offset = get_pagination()
    filters = get_filter_params()

    matches = get_matches(compid, filters, limit, offset)

    return flask.render_template("league/comp/matches.html", matches=matches.fetchall())

@comp.route('/players')
def players(league, compid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'divid', 'primary_classid', 'map', 'time', 'logid')
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
                   WHERE league = %(league)s AND compid = %(compid)s
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
        { **filters, 'league': league, 'compid': compid, 'limit': limit, 'offset': offset })

    return flask.render_template("league/comp/players.html", players=players.fetchall())
