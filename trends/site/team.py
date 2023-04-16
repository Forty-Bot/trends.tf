# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination, \
                  last_modified
from ..util import leagues

team = flask.Blueprint('team', __name__)

@team.url_value_preprocessor
def get_compid(endpoint, values):
    flask.g.teamid = values['teamid']

@team.before_request
def get_comp():
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """SELECT
               team_name AS name,
               avatarhash,
               fetched,
               compid
           FROM team_comp
           WHERE league = %s AND teamid = %s
           ORDER by FETCHED DESC
           LIMIT 1;""", (flask.g.league, flask.g.teamid))

    flask.g.team = cur.fetchone()
    if flask.g.team is None:
        flask.abort(404)

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
               AND (CASE WHEN league_team_per_comp(league) THEN
                        compid = %s
                    ELSE
                        compid ISNULL
                    END)
               AND upper(rostered) ISNULL
           ORDER BY lower(rostered);""", (league, teamid, flask.g.team['compid']))

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
                   AND (CASE WHEN league_team_per_comp(league) THEN
                            compid = %s
                        ELSE
                            compid ISNULL
                        END)
               GROUP BY league, compid, teamid, playerid
               HAVING upper(range_max(rostered)) NOTNULL
           ) AS team_player
           JOIN player USING (playerid)
           JOIN name USING (nameid)
           ORDER BY upper(rostered) DESC
           LIMIT 10;""", (league, teamid, flask.g.team['compid']))

    comps = db.cursor()
    comps.execute(
        """SELECT
               compid,
               competition.name AS comp,
               division AS div,
               format,
               wins,
               losses,
               ties,
               (wins + 0.5 * ties) / nullif(wins + losses + ties, 0) AS winrate,
               rounds_won,
               rounds_lost,
               rounds_won / nullif(rounds_won + rounds_lost, 0) AS round_winrate
           FROM team_comp
           JOIN competition USING (league, compid)
           JOIN division USING (league, compid, divid)
           JOIN div_name USING (div_nameid)
           JOIN format USING (formatid)
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
           WHERE league = %s AND teamid = %s
           ORDER BY compid desc
           LIMIT 10;""", (league, teamid))

    return flask.render_template("league/team/overview.html", roster=roster, old_roster=old_roster,
                                 comps=comps)
