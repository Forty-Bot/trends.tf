# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

import flask

from .util import get_db, get_mc, get_filter_params, get_filter_clauses, get_order, \
                  get_pagination, last_modified
from ..util import clamp

player = flask.Blueprint('player', __name__)

@player.url_value_preprocessor
def get_player(endpoint, values):
    flask.g.steamid = values['steamid']

@player.before_request
def get_overview():
    cur = get_db().cursor()
    cur.execute("SELECT last_active FROM player WHERE steamid64 = %s;", (flask.g.steamid,))
    for row in cur:
        last_active = row[0]
        if not last_active:
            flask.abort(404)

        if resp := last_modified(last_active := row[0]):
            return resp
        break
    else:
        flask.abort(404)

    mc = get_mc()
    key = "overview_{}".format(flask.g.steamid)
    player_overview = mc.get(key)
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
                WHERE steamid64 = %(steamid)s
           ) AS overview
           JOIN player ON (logs != 0)
           JOIN name USING (nameid)
           WHERE steamid64 = %(steamid)s;""", { 'steamid': flask.g.steamid })

    for row in cur:
        flask.g.player = row
        mc.set(key, row)
        break
    else:
        flask.abort(404)

# The base set of column filters for most queries in this file
base_filter_columns = frozenset({'formatid', 'title', 'mapid', 'time', 'logid'})
# These columns filters should be used when pretty names for class, format, and map are not used
surrogate_filter_columns = base_filter_columns.union({'primary_classid'})

def get_logs(c, steamid, filters, duplicates=True, order_clause="logid DESC", limit=100, offset=0):
    filter_clauses = get_filter_clauses(filters, 'primary_classid', 'format', 'title', 'map',
                                        'time', 'logid')
    if not duplicates:
        filter_clauses += "\nAND duplicate_of ISNULL"
    logs = c.cursor()
    logs.execute(
        """SELECT
               log.logid,
               title,
               map,
               classes,
               class_pct,
               wins,
               losses,
               ties,
               format,
               log.duration,
               ps.kills,
               ps.deaths,
               ps.assists,
               ps.dmg * 60.0 / log.duration AS dpm,
               ps.dt * 60.0 / log.duration AS dtm,
               hits * 1.0 / nullif(shots, 0.0) AS acc,
               hsg.healing * 60.0 / log.duration AS hpm_given,
               hsr.healing * 60.0 / log.duration AS hpm_recieved,
               duplicate_of,
               demoid,
               time
           FROM log
           JOIN player_stats AS ps USING (logid)
           JOIN map USING (mapid)
           LEFT JOIN format USING (formatid)
           LEFT JOIN heal_stats_given AS hsg USING (logid, steamid64)
           LEFT JOIN heal_stats_received AS hsr USING (logid, steamid64)
           WHERE ps.steamid64 = %(steamid)s
               {}
           ORDER BY {} NULLS LAST
           LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
        { 'steamid': steamid, **filters, 'limit': limit, 'offset': offset })
    return logs

@player.route('/')
def overview(steamid):
    c = get_db()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, *surrogate_filter_columns)

    classes = c.cursor()
    classes.execute(
        """WITH classes AS MATERIALIZED (
               SELECT
                   classid,
                   classid = primary_classid AS mostly,
                   wins AS round_wins,
                   losses AS round_losses,
                   cs.duration,
                   cs.dmg,
                   cs.hits,
                   cs.shots
               FROM player_stats
               JOIN class_stats cs USING (logid, steamid64)
               JOIN log_nodups USING (logid)
               WHERE steamid64 = %(steamid)s
                   {}
           ) SELECT
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
           ) AS classes;""".format(filter_clauses, get_filter_clauses(filters, 'class')),
        { 'steamid': steamid, **filters})
    classes = classes.fetchall()

    duration = sum(cls['time'] or 0 for cls in classes)
    event_stats = c.cursor()
    event_stats.execute(
            """SELECT
                   event,
                   total(demoman) * 30 * 60 / nullif(%(duration)s, 0) AS demoman,
                   total(engineer) * 30 * 60 / nullif(%(duration)s, 0) AS engineer,
                   total(heavyweapons) * 30 * 60 / nullif(%(duration)s, 0) AS heavyweapons,
                   total(medic) * 30 * 60 / nullif(%(duration)s, 0) AS medic,
                   total(pyro) * 30 * 60 / nullif(%(duration)s, 0) AS pyro,
                   total(scout) * 30 * 60 / nullif(%(duration)s, 0) AS scout,
                   total(sniper) * 30 * 60 / nullif(%(duration)s, 0) AS sniper,
                   total(soldier) * 30 * 60 / nullif(%(duration)s, 0) AS soldier,
                   total(spy) * 30 * 60 / nullif(%(duration)s, 0) AS spy
               FROM event
               LEFT JOIN event_stats USING (eventid)
               LEFT JOIN log_nodups AS log USING (logid)
               LEFT JOIN player_stats USING (logid, steamid64)
               WHERE steamid64 = %(steamid)s
                   {}
               GROUP BY event
               ORDER BY event DESC;""".format(filter_clauses),
               { 'steamid': steamid, 'duration': duration, **filters })
    aliases = c.cursor()
    aliases.execute(
            """SELECT
                   name,
                   count
               FROM (SELECT
                       nameid,
                       count(*) AS count
                   FROM player_stats
                   WHERE steamid64 = %s
                   GROUP BY nameid
                   ORDER BY count(*) DESC
                   LIMIT 10
               ) AS names
               JOIN name USING (nameid)""", (steamid,))
    logs = get_logs(c, steamid, filters, limit=25, duplicates=False)
    return flask.render_template("player/overview.html", logs=logs, classes=classes,
                                 event_stats=event_stats, aliases=aliases)

@player.route('/logs')
def logs(steamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    order, order_clause = get_order({
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
        'hgm': "hpm_given",
        'hrm': "hpm_recieved",
        'acc': "acc",
        'date': "time",
	}, 'logid')
    logs = get_logs(get_db(), steamid, filters, order_clause=order_clause, limit=limit, offset=offset)
    return flask.render_template("player/logs.html", logs=logs.fetchall())

@player.route('/peers')
def peers(steamid):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, *surrogate_filter_columns,
                                        player_prefix='p1.', log_prefix='log.')
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
                   steamid64,
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
                       p2.steamid64,
                       p1.teamid = p2.teamid AS with,
                       p1.teamid != p2.teamid AS against,
                       (p1.wins > p1.losses)::INT AS win,
                       (p1.wins = p1.losses)::INT AS tie,
                       p1.dmg,
                       p1.dt,
                       hs1.healing AS healing_to,
                       hs2.healing AS healing_from,
                       log.duration
                   FROM log_nodups AS log
                   JOIN player_stats AS p1 USING (logid)
                   JOIN player_stats AS p2 USING (logid)
                   LEFT JOIN heal_stats AS hs1 ON (
                       hs1.healer = p1.steamid64
                       AND hs1.healee = p2.steamid64
                       AND hs1.logid = p1.logid
                   ) LEFT JOIN heal_stats AS hs2 ON (
                       hs2.healer = p2.steamid64
                       AND hs2.healee = p1.steamid64
                       AND hs2.logid = p1.logid
                   ) WHERE p1.steamid64 = %(steamid)s
                      AND p2.steamid64 != p1.steamid64
                      AND p2.teamid NOTNULL
                      {}
               ) AS peers
               GROUP BY steamid64
               ORDER BY {} NULLS LAST
               LIMIT %(limit)s OFFSET %(offset)s
           ) AS peers
           JOIN player USING (steamid64)
           JOIN name USING (nameid);""".format(filter_clauses, order_clause),
        { 'steamid': steamid, **filters, 'limit': limit, 'offset': offset })
    return flask.render_template("player/peers.html", peers=peers.fetchall())

@player.route('/totals')
def totals(steamid):
    filters = get_filter_params()
    totals = get_db().cursor()
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
           LEFT JOIN player_stats_extra AS pse USING (logid, steamid64)
           JOIN log_nodups AS log USING (logid)
           LEFT JOIN medic_stats AS ms USING (logid, steamid64)
           LEFT JOIN (SELECT
                   logid,
                   healer AS steamid64,
                   sum(healing) AS healing
               FROM heal_stats
               GROUP BY logid, steamid64
           ) AS hs USING (logid, steamid64)
           WHERE ps.steamid64 = %(steamid)s
               {};""".format(get_filter_clauses(filters, *surrogate_filter_columns)),
        {'steamid': steamid, **filters})
    return flask.render_template("player/totals.html", totals=totals.fetchone())

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
           JOIN class_stats AS cs USING (logid, steamid64, classid)
           JOIN log_nodups AS log USING (logid)
           WHERE steamid64 = %(steamid)s
               {}
           GROUP BY weapon
           ORDER BY weapon ASC NULLS LAST;""".format(filter_clauses),
        {'steamid': steamid, **filters})
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
           LEFT JOIN heal_stats_given AS hsg USING (logid, steamid64)
           LEFT JOIN heal_stats_received AS hsr USING (logid, steamid64)
           WHERE ps.steamid64 = %(steamid)s
               {}
           WINDOW win AS (
               PARTITION BY ps.steamid64
               ORDER BY log.logid
               GROUPS BETWEEN %(window)s - 1 PRECEDING AND CURRENT ROW
           ) ORDER BY log.logid DESC
           LIMIT 10000;""".format(get_filter_clauses(filters, *surrogate_filter_columns)),
           {'steamid': steamid, 'window': window, **filters})
    trends = list(dict(row) for row in cur)
    trends.reverse()
    return flask.render_template("player/trends.html", trends=trends, window=window)
