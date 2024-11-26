# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

from collections import defaultdict

import flask
import pylibmc

from .util import get_db, get_mc, get_filter_params, get_filter_clauses, get_order, \
                  get_pagination, last_modified
from ..util import clamp, classes

player = flask.Blueprint('player', __name__)

@player.url_value_preprocessor
def get_player(endpoint, values):
    flask.g.steamid = values['steamid']

@player.before_request
def get_overview():
    cur = get_db().cursor()
    cur.execute("SELECT playerid, eu_playerid, last_active FROM player WHERE steamid64 = %s;",
                (flask.g.steamid,))
    for flask.g.playerid, flask.g.etf2lid, last_active in cur:
        if not last_active:
            flask.abort(404)

        # FIXME: this is not really accurate...
        if resp := last_modified(last_active):
            return resp
        break
    else:
        flask.abort(404)

    mc = get_mc()
    key = "overview_{}".format(flask.g.steamid)
    player_overview, cas = mc.gets(key)
    if player_overview and player_overview['last_active'] == last_active:
        flask.g.player = player_overview
        return

    cur.execute(
        """SELECT
               *,
               name,
               avatarhash,
               (wins + 0.5 * ties) /
                   (wins + losses + ties) AS winrate,
               (round_wins + 0.5 * round_ties) /
                   (round_wins + round_losses + round_ties) AS round_winrate
           FROM (
                SELECT
                    count(*) AS logs,
                    sum(wins) AS round_wins,
                    sum(losses) AS round_losses,
                    sum(ties) AS round_ties,
                    sum((wins > losses)::INT) AS wins,
                    sum((wins < losses)::INT) AS losses,
                    sum((wins = losses)::INT) AS ties
                FROM player_stats
                WHERE playerid = %(playerid)s
           ) AS overview
           JOIN player ON (logs != 0)
           JOIN name USING (nameid)
           WHERE playerid = %(playerid)s;""", { 'playerid': flask.g.playerid })

    for row in cur:
        flask.g.player = row
        if cas is None:
            mc.add(key, row, time=86400)
        else:
            try:
                mc.cas(key, row, cas, time=86400)
            except pylibmc.NotFound:
                pass
        break
    else:
        flask.abort(404)

# The base set of column filters for most queries in this file
base_filter_columns = frozenset({'league', 'formatid', 'title', 'mapid', 'time', 'logid'})
# These columns filters should be used when pretty names for class, format, and map are not used
surrogate_filter_columns = base_filter_columns.union({'primary_classid'})

# Columns in player_stats_extra
log_extra_order_map = {
    'lks': "lks",
    'airshots': "airshots",
    'medkits': "medkits",
    'medkits_hp': "medkits_hp",
    'backstabs': "backstabs",
    'headshots': "headshots",
    'headshots_hit': "headshots_hit",
    'sentries': "sentries",
    'mks': "mks",
}

# Columns not in player_stats
log_joined_order_map = {
    'hgm': "hpm_given",
    'hrm': "hpm_recieved",
    # This is renamed, and needs special treatment
    'captures': "coalesce(cpc + ic, cpc, ic)",
    **log_extra_order_map,
}

# All columns we can sort logs by
log_order_map = {
    'logid': "logid",
    'wins': "wins",
    'losses': "losses",
    'ties': "ties",
    'duration': "duration",
    'kills': "kills",
    'deaths': "deaths",
    'assists': "assists",
    'dpm': "dpm",
    'dtm': "dtm",
    'acc': "acc",
    'date': "time",
    **log_joined_order_map,
}

def get_logs(c, playerid, filters, extra=False, order_clause="logid DESC", limit=100, offset=0):
    real_offset = offset
    filter_clauses = get_filter_clauses(filters, 'primary_classid', 'league', 'formatid', 'title',
                                        'mapid', 'time', 'logid', 'duplicate_of')
    if not any(col in order_clause for col in log_joined_order_map.values()):
        filter_clauses += """
            ORDER BY {} NULLS LAST, logid DESC
            LIMIT %(limit)s OFFSET %(real_offset)s
        """.format(order_clause)
        offset = 0

    if extra:
        extra_cols = ",\n               ".join((
            "",
            "coalesce(cpc + ic, cpc, ic) AS captures",
            *log_extra_order_map.values()
        ))
    else:
        extra_cols = ""

    logs = c.cursor()
    logs.execute(
        f"""SELECT
               ps.logid,
               title,
               map,
               classes,
               class_pct,
               wins,
               losses,
               ties,
               format,
               ps.duration,
               ps.kills,
               ps.deaths,
               ps.assists,
               dpm,
               dtm,
               acc,
               hsg.healing * 60.0 / nullif(ps.duration, 0) AS hpm_given,
               hsr.healing * 60.0 / nullif(ps.duration, 0) AS hpm_recieved,
               duplicate_of,
               demoid,
               league,
               matchid,
               time
               {extra_cols}
           FROM (SELECT
                   *,
                   ps.dmg * 60.0 / nullif(log.duration, 0) AS dpm,
                   ps.dt * 60.0 / nullif(log.duration, 0) AS dtm,
                   hits * 1.0 / nullif(shots, 0.0) AS acc
               FROM log
               JOIN player_stats AS ps USING (logid)
               WHERE playerid = %(playerid)s
                   {filter_clauses}
           ) as ps
           JOIN map USING (mapid)
           LEFT JOIN format USING (formatid)
           LEFT JOIN heal_stats_given AS hsg USING (logid, playerid)
           LEFT JOIN heal_stats_received AS hsr USING (logid, playerid)
           {"LEFT JOIN player_stats_extra AS pse USING (logid, playerid)" if extra else ""}
           WHERE ps.playerid = %(playerid)s
           ORDER BY {order_clause} NULLS LAST, logid DESC
           LIMIT %(limit)s OFFSET %(offset)s;""",
        {
            **filters,
            'playerid': flask.g.playerid,
            'limit': limit,
            'offset': offset,
            'real_offset': real_offset
        })
    return logs

def get_teams(c, filters, order_clause="rto DESC", limit=10, offset=0):
    inner_clauses = get_filter_clauses(filters, 'league', date_range='rostered')
    outer_clauses = get_filter_clauses(filters, 'formatid')

    teams = c.cursor()
    teams.execute(
        """WITH t AS (SELECT
                   tc.league,
                   tc.compid AS compid,
                   comp.compid AS ccompid,
                   tc.teamid,
                   tc.team_nameid,
                   divid,
                   rostered,
                   comp.scheduled
               FROM (SELECT
                        league,
                        teamid,
                        compid,
                        range_agg(rostered) AS rostered
                    FROM team_player
                    WHERE playerid = %(playerid)s
                        {}
                    GROUP BY league, teamid, compid
               ) AS tp
               JOIN team_comp_backing AS tc ON (
                   tp.league = tc.league
                   AND tp.teamid = tc.teamid
                   AND (NOT league_team_per_comp(tc.league)
                        OR tp.compid = tc.compid)
               ) LEFT JOIN (SELECT
                       league,
                       compid,
                       int8range(scheduled_from, scheduled_to, '[]') AS scheduled
                   FROM competition
                   WHERE scheduled_from NOTNULL
               ) AS comp ON (
                   tp.league = comp.league
                   AND NOT league_team_per_comp(tc.league)
                   AND tc.compid = comp.compid AND tp.rostered && comp.scheduled
               )
           ) SELECT
               league,
               format,
               l.comp AS comp2,
               l.compid AS compid2,
               u.comp AS comp1,
               u.compid AS compid1,
               div,
               team,
               teamid,
               rfrom AS from,
               rto AS to
           FROM (SELECT
                   league,
                   teamid,
                   coalesce(t.team_nameid, league_team.team_nameid) AS team_nameid,
                   competition.compid,
                   competition.name AS comp,
                   format,
                   division AS div,
                   upper(rostered) AS rto
               FROM (SELECT
                       league,
                       teamid,
                       coalesce(max(ccompid), max(compid)) as compid
                   FROM t
                   GROUP BY league, teamid
               ) AS u
               JOIN t USING (league, teamid, compid)
               JOIN competition USING (league, compid)
               JOIN format USING (formatid)
               LEFT JOIN division USING (league, divid)
               LEFT JOIN div_name USING (div_nameid)
               JOIN league_team USING (league, teamid)
               WHERE TRUE
                   {}
           ) AS u
           JOIN (SELECT
                   league,
                   teamid,
                   compid,
                   competition.name AS comp,
                   lower(rostered) AS rfrom
               FROM (SELECT
                       league,
                       teamid,
                       coalesce(min(ccompid), min(compid)) as compid
                   FROM t
                   GROUP BY league, teamid
               ) AS l
               JOIN t USING (league, teamid, compid)
               JOIN competition USING (league, compid)
           ) AS l USING (league, teamid)
           JOIN team_name USING (team_nameid)
           ORDER BY {}, rfrom DESC, u.compid DESC, l.compid DESC
           LIMIT %(limit)s OFFSET %(offset)s;""".format(inner_clauses, outer_clauses, order_clause),
           { 'playerid': flask.g.playerid, 'limit': limit, 'offset': offset, **filters })
    return teams.fetchall()

@player.route('/')
def overview(steamid):
    c = get_db()
    filters = get_filter_params()
    filters['dupes'] = False
    filter_clauses = get_filter_clauses(filters, *surrogate_filter_columns)

    classes = c.cursor()
    classes.execute("BEGIN;")
    classes.execute("LOCK log_nodups IN ACCESS SHARE MODE;")
    classes.execute(
        """CREATE TEMP TABLE classes AS SELECT
               classid,
               classid = primary_classid AS mostly,
               wins AS round_wins,
               losses AS round_losses,
               cs.duration,
               cs.dmg,
               cs.hits,
               cs.shots
           FROM player_stats
           JOIN class_stats cs USING (logid, playerid)
           JOIN log_nodups USING (logid)
           WHERE playerid = %(playerid)s
               {};""".format(filter_clauses), { 'playerid': flask.g.playerid, **filters})
    classes.execute("COMMIT;")
    classes.execute("ANALYZE classes");
    classes.execute(
        """SELECT
               *,
               (wins + 0.5 * ties) / (wins + losses + ties) AS winrate
           FROM (
               SELECT
                   class,
                   sum(CASE WHEN mostly THEN (round_wins > round_losses)::INT END) AS wins,
                   sum(CASE WHEN mostly THEN (round_wins < round_losses)::INT END) AS losses,
                   sum(CASE WHEN mostly THEN (round_wins = round_losses)::INT END) AS ties,
                   total(duration) AS time,
                   sum(dmg) * 60.0 / nullif(sum(duration), 0.0) AS dpm,
                   total(hits) / nullif(sum(shots), 0.0) AS acc,
                   total(dmg) / nullif(sum(shots), 0.0) AS dps
               FROM class
               LEFT JOIN classes USING (classid)
               WHERE TRUE
                   {}
               GROUP BY classid
               ORDER BY classid
           ) AS classes;""".format(get_filter_clauses(filters, 'class')),
        { 'playerid': flask.g.playerid, **filters})
    classes = classes.fetchall()

    formats = c.cursor()
    formats.execute(
        """SELECT
               format,
               (wins + 0.5 * ties) /
                   (wins + losses + ties) AS winrate,
               data.*
           FROM (SELECT
                   formatid,
                   sum((wins > losses)::INT) AS wins,
                   sum((wins < losses)::INT) AS losses,
                   sum((wins = losses)::INT) AS ties,
                   total(duration) as time
               FROM log_nodups
               JOIN player_stats USING (logid)
               WHERE playerid = %(playerid)s
                   {}
               GROUP BY formatid
           ) AS data
           JOIN format using (formatid);""".format(filter_clauses),
        { 'playerid': flask.g.playerid, **filters })

    aliases = c.cursor()
    aliases.execute(
            """SELECT
                   name,
                   count
               FROM (SELECT
                       nameid,
                       count(*) AS count
                   FROM player_stats
                   WHERE playerid = %s
                   GROUP BY nameid
                   ORDER BY count(*) DESC
                   LIMIT 10
               ) AS names
               JOIN name USING (nameid)""", (flask.g.playerid,))

    logs = get_logs(c, flask.g.playerid, filters, limit=25)
    teams = get_teams(c, filters)
    return flask.render_template("player/overview.html", logs=logs, classes=classes,
                                 formats=formats, aliases=aliases, teams=teams)

@player.route('/logs')
def logs(steamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    order, order_clause = get_order(log_order_map, 'logid')
    logs = get_logs(get_db(), flask.g.playerid, filters, extra=True, order_clause=order_clause,
                    limit=limit, offset=offset)
    return flask.render_template("player/logs.html", logs=logs.fetchall())

@player.route('/teams')
def teams(steamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    order, order_clause = get_order({
        'to': "rto",
        'from': "rfrom",
	}, 'to')
    teams = get_teams(get_db(), get_filter_params(), order_clause, limit=limit, offset=offset)
    return flask.render_template("player/teams.html", teams=teams)

@player.route('/peers')
def peers(steamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = \
        get_filter_clauses(filters, league='log.league', formatid='log.formatid',
                           title='log.title', mapid='log.mapid', time='log.time', logid='log.logid',
                           primary_classid='p1.primary_classid')
    order, order_clause = get_order({
        'logs': "count(*)",
        'with': '"with"',
        'against': '"against"',
        'winrate_with': "winrate_with",
        'winrate_against': "winrate_against",
        'time_with': "time_with",
        'time_against': "time_against",
        'dpm': "dpm",
        'dtm': "dtm",
        'hgm': "hpm_to",
        'hrm': "hpm_from",
    }, 'logs')
    peers = get_db().cursor()
    peers.execute(
        """SELECT
               *,
               name,
               avatarhash
           FROM (SELECT
                   playerid,
                   total("with"::INT) AS with,
                   total(against::INT) AS against,
                   (sum(CASE WHEN "with" THEN win END) +
                       0.5 * sum(CASE WHEN "with" THEN tie END)) /
                       sum("with"::INT) AS winrate_with,
                   (sum(CASE WHEN against THEN win END) +
                       0.5 * sum(CASE WHEN against THEN tie END)) /
                       sum(against::INT) AS winrate_against,
                   sum(CASE WHEN "with" THEN dmg END) * 60.0 /
                       sum(CASE WHEN "with" THEN duration END) AS dpm,
                   sum(CASE WHEN "with" THEN dt END) * 60.0 /
                       sum(CASE WHEN "with" THEN duration END) AS dtm,
                   sum(CASE WHEN "with" THEN healing_to END) * 60.0 /
                       sum(CASE WHEN "with" THEN duration END) AS hpm_to,
                   sum(CASE WHEN "with" THEN healing_from END) * 60.0 /
                       sum(CASE WHEN "with" THEN duration END) AS hpm_from,
                   total(CASE WHEN "with" THEN duration END) as time_with,
                   total(CASE WHEN against THEN duration END) as time_against
               FROM (
                   SELECT
                       p1.logid,
                       p2.playerid,
                       p1.team = p2.team AS with,
                       p1.team != p2.team AS against,
                       (p1.wins > p1.losses)::INT AS win,
                       (p1.wins = p1.losses)::INT AS tie,
                       p1.dmg,
                       p1.dt,
                       hs1.healing AS healing_to,
                       hs2.healing AS healing_from,
                       nullif(log.duration, 0) AS duration
                   FROM log_nodups AS log
                   JOIN player_stats AS p1 USING (logid)
                   JOIN player_stats AS p2 USING (logid)
                   LEFT JOIN heal_stats AS hs1 ON (
                       hs1.healer = p1.playerid
                       AND hs1.healee = p2.playerid
                       AND hs1.logid = p1.logid
                   ) LEFT JOIN heal_stats AS hs2 ON (
                       hs2.healer = p2.playerid
                       AND hs2.healee = p1.playerid
                       AND hs2.logid = p1.logid
                   ) WHERE p1.playerid = %(playerid)s
                      AND p2.playerid != p1.playerid
                      AND p2.team NOTNULL
                      {}
               ) AS peers
               GROUP BY playerid
               ORDER BY {} NULLS LAST
               LIMIT %(limit)s OFFSET %(offset)s
           ) AS peers
           JOIN player USING (playerid)
           JOIN name USING (nameid);""".format(filter_clauses, order_clause),
        { 'playerid': flask.g.playerid, **filters, 'limit': limit, 'offset': offset })
    return flask.render_template("player/peers.html", peers=peers.fetchall())

@player.route('/totals')
def totals(steamid):
    c = get_db()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, *surrogate_filter_columns)

    totals = c.cursor()
    totals.execute(
        """SELECT
               count(*) AS logs,
               (sum((wins > losses)::INT) + 0.5 * sum((wins = losses)::INT)) /
                   nullif(count(*), 0) AS winrate,
               (sum(wins) + 0.5 * sum(ties)) /
                   nullif(sum(wins + losses + ties), 0) AS round_winrate,
               sum(wins) AS round_wins,
               sum(losses) AS round_losses,
               sum(ties) AS round_ties,
               sum((wins > losses)::INT) AS wins,
               sum((wins < losses)::INT) AS losses,
               sum((wins = losses)::INT) AS ties,
               total(ps.kills) AS kills,
               total(ps.deaths) AS deaths,
               total(ps.assists) AS assists,
               total(log.duration) AS duration,
               total(ps.dmg) AS dmg,
               total(dt) AS dt,
               total(hr) AS hr,
               total(airshots) AS airshots,
               total(medkits) AS medkits,
               total(medkits_hp) AS medkits_hp,
               total(backstabs) AS backstabs,
               total(headshots) AS headshots,
               total(headshots_hit) AS headshots_hit,
               total(sentries) AS sentries,
               total(cpc) AS cpc,
               total(ic) AS ic,
               -- Medic stuff
               total(hs.healing) AS healing,
               total(ubers) AS ubers,
               total(drops) AS drops,
               total(advantages_lost) AS advantages_lost,
               total(deaths_after_uber) AS deaths_after_uber,
               total(deaths_before_uber) AS deaths_before_uber,
               -- Averages
               total(ps.kills) * 30 * 60 / nullif(total(log.duration), 0) AS k30,
               total(ps.deaths) * 30 * 60 / nullif(total(log.duration), 0) AS d30,
               total(ps.assists) * 30 * 60 / nullif(total(log.duration), 0) AS a30,
               total(ps.dmg) * 60 / nullif(total(log.duration), 0) AS dpm,
               total(ps.dt) * 60 / nullif(total(log.duration), 0) AS dtm,
               total(hr) * 60 / nullif(total(log.duration), 0) AS hrm,
               total(airshots) * 30 * 60 / nullif(total(log.duration), 0) AS as30,
               total(medkits) * 30 * 60 / nullif(total(log.duration), 0) AS mk30,
               total(medkits_hp) * 60 / nullif(total(log.duration), 0) AS mkhpm,
               total(backstabs) * 30 * 60 / nullif(total(log.duration), 0) AS bs30,
               total(headshots) * 30 * 60 / nullif(total(log.duration), 0) AS hs30,
               total(headshots_hit) * 30 * 60 / nullif(total(log.duration), 0) AS hsh30,
               total(sentries) * 30 * 60 / nullif(total(log.duration), 0) AS sen30,
               total(cpc) * 30 * 60 / nullif(total(log.duration), 0) AS cpc30,
               total(ic) * 30 * 60 / nullif(total(log.duration), 0) AS ic30,
               -- Medic averages
               total(hs.healing) * 60 / nullif(total(log.duration), 0) AS hgm,
               total(ubers) * 30 * 60 / nullif(total(log.duration), 0) AS ub30,
               total(drops) * 30 * 60 / nullif(total(log.duration), 0) AS drp30,
               total(advantages_lost) * 30 * 60 / nullif(total(log.duration), 0) AS adl30,
               total(deaths_after_uber) * 30 * 60 / nullif(total(log.duration), 0) AS dau30,
               total(deaths_before_uber) * 30 * 60 / nullif(total(log.duration), 0) AS abu30
           FROM player_stats AS ps
           LEFT JOIN player_stats_extra AS pse USING (logid, playerid)
           JOIN log_nodups AS log USING (logid)
           LEFT JOIN medic_stats AS ms USING (logid, playerid)
           LEFT JOIN (SELECT
                   logid,
                   healer AS playerid,
                   sum(healing) AS healing
               FROM heal_stats
               GROUP BY logid, playerid
           ) AS hs USING (logid, playerid)
           WHERE ps.playerid = %(playerid)s
               {};""".format(filter_clauses),
        {'playerid': flask.g.playerid, **filters})
    totals = totals.fetchone()

    events = c.cursor()
    events.execute(
            """SELECT *
               FROM event
               LEFT JOIN (SELECT
                       eventid,
                       total(demoman) AS demoman,
                       total(engineer) AS engineer,
                       total(heavyweapons) AS heavyweapons,
                       total(medic) AS medic,
                       total(pyro) AS pyro,
                       total(scout) AS scout,
                       total(sniper) AS sniper,
                       total(soldier) AS soldier,
                       total(spy) AS spy
                   FROM event
                   LEFT JOIN event_stats USING (eventid)
                   LEFT JOIN log_nodups AS log USING (logid)
                   LEFT JOIN player_stats USING (logid, playerid)
                   WHERE playerid = %(playerid)s
                       {}
                   GROUP BY eventid) AS data USING (eventid);""".format(filter_clauses),
               { 'playerid': flask.g.playerid, **filters })

    # Pivot from rows of events to rows of classes
    # Not done in postgres because crosstab messes up quoting
    class_totals = defaultdict(dict)
    for event in events:
        for cls in classes:
            class_totals[cls][event['event']] = event[cls]
            if totals['duration'] and event[cls] is not None:
                per30 = event[cls] * 30 * 60 / totals['duration']
            else:
                per30 = None
            class_totals[cls][f"{event['event']}30"] = per30

    return flask.render_template("player/totals.html", totals=totals, class_totals=class_totals)

@player.route('/weapons')
def weapons(steamid):
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'classid', *base_filter_columns)
    weapons = get_db().cursor()
    weapons.execute(
        """SELECT
               weapon,
               sum(ws.kills) * 30.0 * 60 / nullif(sum(cs.duration), 0) AS k30,
               sum(ws.dmg) * 60.0 / nullif(sum(cs.duration), 0) AS dpm,
               sum(CASE WHEN ws.shots::BOOL THEN ws.dmg END) / nullif(sum(ws.shots), 0.0) AS dps,
               sum(CASE WHEN ws.hits::BOOL THEN ws.dmg END) / nullif(sum(ws.hits), 0.0) AS dph,
               total(ws.hits) / nullif(sum(ws.shots), 0.0) AS acc,
               total(ws.kills) AS kills,
               total(cs.duration) AS duration,
               total(ws.dmg) AS dmg,
               sum(ws.shots) AS shots,
               sum(ws.hits) AS hits,
               count(*) AS logs
           FROM weapon_stats AS ws
           JOIN weapon_pretty USING (weaponid)
           JOIN class_stats AS cs USING (logid, playerid, classid)
           JOIN log_nodups AS log USING (logid)
           WHERE playerid = %(playerid)s
               {}
           GROUP BY weapon
           ORDER BY weapon ASC NULLS LAST;""".format(filter_clauses),
        {'playerid': flask.g.playerid, **filters})
    return flask.render_template("player/weapons.html", weapons=weapons)

@player.route('/trends')
def trends(steamid):
    filters = get_filter_params()
    window = clamp(flask.request.args.get('window', 20, int), 1, 500)
    cur = get_db().cursor()
    cur.execute(
        """SELECT
               log.logid,
               time,
               (sum((wins > losses)::INT) OVER win + 0.5 * sum((wins = losses)::INT) OVER win) /
                   count(*) OVER win AS winrate,
               (sum(wins + 0.5 * ties) OVER win) /
                   nullif(sum(wins + losses + ties) OVER win, 0) AS round_winrate,
               sum(ps.kills) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS kills,
               sum(ps.deaths) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS deaths,
               sum(ps.assists) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS assists,
               sum(ps.dmg) OVER win * 60.0 / nullif(sum(log.duration) OVER win, 0) AS dpm,
               sum(ps.dt) OVER win * 60.0 /
                   nullif(sum(nullelse(ps.dt, log.duration)) OVER win, 0) AS dtm,
               sum(hsg.healing) OVER win * 60.0 /
                   nullif(sum(nullelse(hsg.healing, log.duration)) OVER win, 0) AS hpm_given,
               sum(hsr.healing) OVER win * 60.0 /
                   nullif(sum(nullelse(hsr.healing, log.duration)) OVER win, 0) AS hpm_recieved
           FROM log_nodups AS log
           JOIN player_stats AS ps USING (logid)
           LEFT JOIN heal_stats_given AS hsg USING (logid, playerid)
           LEFT JOIN heal_stats_received AS hsr USING (logid, playerid)
           WHERE ps.playerid = %(playerid)s
               {}
           WINDOW win AS (
               PARTITION BY ps.playerid
               ORDER BY log.logid
               GROUPS BETWEEN %(window)s - 1 PRECEDING AND CURRENT ROW
           ) ORDER BY log.logid DESC
           LIMIT 10000;""".format(get_filter_clauses(filters, *surrogate_filter_columns)),
           {'playerid': flask.g.playerid, 'window': window, **filters})
    trends = list(dict(row) for row in cur)
    trends.reverse()
    return flask.render_template("player/trends.html", trends=trends, window=window)

@player.route('/maps')
def maps(steamid):
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, *surrogate_filter_columns)
    maps = get_db().cursor()
    maps.execute(
        """SELECT
               grouping(parts[1], parts[2], parts[3:]) AS grouping,
               parts[1] AS part1,
               parts[2] AS part2,
               (array_agg(map ORDER BY logs DESC))[1] AS map,
               (sum(wins) + 0.5 * sum(ties)) /
                   nullif(sum(wins + losses + ties), 0) AS winrate,
               (sum(round_wins) + 0.5 * sum(round_ties)) /
                   nullif(sum(round_wins + round_losses + round_ties), 0) AS round_winrate,
               sum(kills) AS kills,
               sum(deaths) AS deaths,
               sum(assists) AS assists,
               sum(dmg) AS dmg,
               sum(dt) AS dt,
               total(kills) * 30 * 60 / nullif(total(duration), 0) AS k30,
               total(deaths) * 30 * 60 / nullif(total(duration), 0) AS d30,
               total(assists) * 30 * 60 / nullif(total(duration), 0) AS a30,
               total(dmg) * 60 / nullif(total(duration), 0) AS dpm,
               total(dt) * 60 / nullif(total(duration), 0) AS dtm,
               total(hits) / nullif(sum(shots), 0.0) AS acc,
               sum(logs) AS logs,
               total(duration) AS duration
           FROM (WITH map_unprefixed AS (SELECT
                   mapid,
                   replace(map, 'workshop/', '') AS map
               FROM map) SELECT
                   map,
                   (SELECT
                        array_agg(part)
                    FROM unnest(regexp_split_to_array(lower(map), '[^a-z0-9]+')) AS part
                    WHERE part != '') AS parts,
                   stats.*
               FROM (SELECT
                       mapid,
                       count(*) AS logs,
                       sum(wins) AS round_wins,
                       sum(losses) AS round_losses,
                       sum(ties) AS round_ties,
                       sum((wins > losses)::INT) AS wins,
                       sum((wins < losses)::INT) AS losses,
                       sum((wins = losses)::INT) AS ties,
                       total(duration) AS duration,
                       total(kills) AS kills,
                       total(deaths) AS deaths,
                       total(assists) AS assists,
                       total(dmg) AS dmg,
                       total(dt) AS dt,
                       total(hits) AS hits,
                       total(shots) AS shots
                   FROM log_nodups
                   JOIN player_stats using (logid)
                   WHERE playerid = %(playerid)s
                       {}
                   GROUP BY mapid
               ) AS stats
               JOIN map USING (mapid)
           ) AS maps
           GROUP BY ROLLUP (parts[1], parts[2], parts[3:])
           HAVING parts[1] IS NOT NULL
           ORDER BY parts[1] NULLS FIRST,
               CASE
                   WHEN grouping(parts[2]) = 0 THEN coalesce(parts[2], '')
                   ELSE NULL
               END NULLS FIRST,
               parts[3:] COLLATE numeric NULLS FIRST;""".format(filter_clauses),
        {'playerid': flask.g.playerid, **filters})
    return flask.render_template("player/maps.html", maps=maps.fetchall())
