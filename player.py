# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask

from common import get_filters, filter_clauses, get_order
from sql import get_db

player = flask.Blueprint('player', __name__)

@player.app_template_filter('duration')
def duration_filter(timestamp):
    mm, ss = divmod(timestamp, 60)
    hh, mm = divmod(mm, 60)
    dd, hh = divmod(hh, 24)
    if dd:
        return "{:.0f} day{}, {:.0f}:{:02.0f}:{:02.0f}" \
               .format(dd, "s" if dd > 1 else "", hh, mm, ss)
    elif hh:
        return "{:.0f}:{:02.0f}:{:02.0f}".format(hh, mm, ss)
    else:
        return "{:.0f}:{:02.0f}".format(mm, ss)

@player.app_template_filter('avatar')
def avatar_filter(hash, size='full'):
    if not hash:
        return ''
    url = "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/avatars/{}/{}{}.jpg"
    return url.format(hash[0:2], hash, {
            'small': '',
            'medium': '_medium',
            'full': '_full',
        }[size])

@player.url_value_preprocessor
def get_player(endpoint, values):
    flask.g.steamid = values['steamid']
    cur = get_db().cursor()
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
                    sum(wins) AS round_wins,
                    sum(losses) AS round_losses,
                    sum(ties) AS round_ties,
                    sum((wins > losses)::INT) AS wins,
                    sum((wins < losses)::INT) AS losses,
                    sum((wins = losses)::INT) AS ties
                FROM player_stats
                WHERE steamid64 = %(steamid)s
           ) AS overview
           CROSS JOIN player
           JOIN name USING (nameid)
           WHERE steamid64 = %(steamid)s;""", values)

    for row in cur:
        flask.g.player = row
        break
    else:
        flask.abort(404)

def get_logs(c, steamid, filters, order_clause="logid DESC", limit=100, offset=0):
    logs = c.cursor()
    logs.execute(
        """SELECT
               log.logid,
               title,
               map,
               classes,
               (SELECT
                       array_agg(duration * 1.0 / log.duration)
                   FROM unnest(class_durations) AS duration
               ) AS class_pct,
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
               acc,
               hsg.healing * 60.0 / log.duration AS hpm_given,
               hsr.healing * 60.0 / log.duration AS hpm_recieved,
               time
           FROM log
           JOIN player_stats AS ps USING (logid)
           JOIN map USING (mapid)
           JOIN format USING (formatid)
           JOIN (SELECT
                     logid,
                     steamid64,
                     array_agg(class ORDER BY duration DESC) AS classes,
                     array_agg(duration ORDER BY duration DESC) AS class_durations
                 FROM class_stats
                 JOIN class USING (classid)
                 -- Duplicate of below, but sqlite is dumb...
                 WHERE steamid64 = %(steamid)s
                 GROUP BY logid, steamid64
           ) AS classes USING (logid, steamid64)
           LEFT JOIN (SELECT
                   logid,
                   steamid64,
                   total(hits) / nullif(sum(shots), 0.0) AS acc
               FROM weapon_stats
               GROUP BY logid, steamid64
           ) AS ws USING (logid, steamid64)
           LEFT JOIN (SELECT
                   logid,
                   healer AS steamid64,
                   total(healing) AS healing
               FROM heal_stats
               GROUP BY logid, healer
           ) AS hsg USING (logid, steamid64)
           LEFT JOIN (SELECT
                   logid,
                   healee AS steamid64,
                   total(healing) AS healing
               FROM heal_stats
               GROUP BY logid, healee
           ) AS hsr USING (logid, steamid64)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=log.logid
               AND cs.steamid64=ps.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class ON (class.classid=cs.classid)
           WHERE ps.steamid64 = %(steamid)s
               {}
           ORDER BY {} NULLS LAST
           LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
           { 'steamid': steamid, **filters, 'limit': limit, 'offset': offset })
    return logs

@player.route('/')
def overview(steamid):
    c = get_db()
    classes = c.cursor()
    classes.execute(
        """WITH classes AS MATERIALIZED (
               SELECT
                   classid,
                   cs.duration * 1.5 > log.duration AS mostly,
                   wins AS round_wins,
                   losses AS round_losses,
                   cs.duration,
                   cs.dmg,
                   hits,
                   shots
               FROM log
               JOIN player_stats USING (logid)
               JOIN class_stats cs USING (logid, steamid64)
               JOIN (SELECT
                       logid,
                       steamid64,
                       classid,
                       sum(hits) AS hits,
                       sum(shots) AS shots
                   FROM weapon_stats
                   GROUP BY logid, steamid64, classid
               ) AS ws USING (logid, steamid64, classid)
               WHERE steamid64 = %s
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
                   sum(dmg) * 60.0 / sum(duration) AS dpm,
                   total(hits) / nullif(sum(shots), 0.0) AS acc
               FROM class
               LEFT JOIN classes USING (classid)
               GROUP BY classid
               ORDER BY classid
           ) AS classes;""", (steamid,))
    event_stats = c.cursor()
    event_stats.execute(
            """SELECT
                   event,
                   coalesce(avg(demoman), 0.0) AS demoman,
                   coalesce(avg(engineer), 0.0) AS engineer,
                   coalesce(avg(heavyweapons), 0.0) AS heavyweapons,
                   coalesce(avg(medic), 0.0) AS medic,
                   coalesce(avg(pyro), 0.0) AS pyro,
                   coalesce(avg(scout), 0.0) AS scout,
                   coalesce(avg(sniper), 0.0) AS sniper,
                   coalesce(avg(soldier), 0.0) AS soldier,
                   coalesce(avg(spy), 0.0) AS spy
               FROM event
               LEFT JOIN event_stats USING (eventid)
               WHERE steamid64=%s
               GROUP BY event
               ORDER BY event DESC;""", (steamid,))
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
    logs = get_logs(c, steamid, get_filters(flask.request.args), limit=25)
    return flask.render_template("player/overview.html", logs=logs, classes=classes,
                                 event_stats=event_stats, aliases=aliases)

@player.route('/logs')
def logs(steamid):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    filters = get_filters(flask.request.args)
    order, order_clause = get_order(flask.request.args, {
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
    logs = get_logs(get_db(), steamid, filters, order_clause, limit=limit, offset=offset).fetchall()
    return flask.render_template("player/logs.html", logs=logs, filters=filters, order=order,
                                 limit=limit, offset=offset)

@player.route('/peers')
def peers(steamid):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    order, order_clause = get_order(flask.request.args, {
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
                   FROM log
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
                   ) WHERE p1.steamid64 = %s
                      AND p2.steamid64 != p1.steamid64
                      AND p2.teamid NOTNULL
               ) AS peers
               GROUP BY steamid64
               ORDER BY {} NULLS LAST
               LIMIT %s OFFSET %s
           ) AS peers
           JOIN player USING (steamid64)
           JOIN name USING (nameid);""".format(order_clause), (steamid, limit, offset))
    return flask.render_template("player/peers.html", peers=peers.fetchall(), order=order,
                                 limit=limit, offset=offset)

@player.route('/totals')
def totals(steamid):
    filters = get_filters(flask.request.args)
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
           JOIN log USING (logid)
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           LEFT JOIN medic_stats AS ms USING (logid, steamid64)
           LEFT JOIN (SELECT
                   logid,
                   healer AS steamid64,
                   sum(healing) AS healing
               FROM heal_stats
               GROUP BY logid, steamid64
           ) AS hs USING (logid, steamid64)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=ps.logid
               AND cs.steamid64=ps.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class USING (classid)
           WHERE ps.steamid64 = %(steamid)s
               {};""".format(filter_clauses),
        {'steamid': steamid, **filters})
    return flask.render_template("player/totals.html", totals=totals.fetchone(), filters=filters)

@player.route('/weapons')
def weapons(steamid):
    filters = get_filters(flask.request.args)
    order, order_clause = get_order(flask.request.args, {
        'weapon': 'weapon',
        'kills': 'k30',
        'dpm': 'dpm',
        'acc': 'acc',
        'total_kills': 'kills',
        'dmg': 'dmg',
        'logs': 'logs',
        'time': 'duration',
    }, 'weapon', 'asc')
    weapons = get_db().cursor()
    weapons.execute(
        """SELECT
               weapon,
               sum(ws.kills) * 30.0 * 60 / nullif(sum(cs.duration), 0) AS k30,
               sum(ws.dmg) * 60.0 / nullif(sum(cs.duration), 0) AS dpm,
               total(hits) / nullif(sum(shots), 0.0) AS acc,
               total(ws.kills) AS kills,
               total(cs.duration) AS duration,
               total(ws.dmg) AS dmg,
               count(*) AS logs
           FROM weapon_stats AS ws
           JOIN weapon USING (weaponid)
           JOIN class_stats AS cs USING (logid, steamid64, classid)
           JOIN class USING (classid)
           JOIN log USING (logid)
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           WHERE steamid64 = %(steamid)s
               {}
           GROUP BY weapon
           ORDER BY {} NULLS LAST;""".format(filter_clauses, order_clause),
        {'steamid': steamid, **filters})
    return flask.render_template("player/weapons.html", weapons=weapons, filters=filters,
                                 order=order)

@player.route('/trends')
def trends(steamid):
    filters = get_filters(flask.request.args)
    cur = get_db().cursor()
    cur.execute(
        """SELECT
               log.logid,
               time,
               (sum((wins > losses)::INT) OVER win + 0.5 * sum((wins = losses)::INT) OVER win) /
                   count(*) OVER win AS winrate,
               (sum(wins + 0.5 * ties) OVER win) /
                   sum(wins + losses + ties) OVER win AS round_winrate,
               sum(ps.kills) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS kills,
               sum(ps.deaths) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS deaths,
               sum(ps.assists) OVER win * 30.0 * 60 /
                   nullif(sum(log.duration) OVER win, 0) AS assists,
               sum(ps.dmg) OVER win * 60.0 / nullif(sum(log.duration) OVER win, 0) AS dpm,
               sum(ps.dt) OVER win * 60.0 /
                   nullif(sum(CASE WHEN ps.dt NOTNULL THEN log.duration END) OVER win, 0) AS dtm,
               sum(hsg.healing) OVER win * 60.0 /
                   nullif(sum(log.duration) OVER win, 0) AS hpm_given,
               sum(hsr.healing) OVER win * 60.0 /
                   nullif(sum(log.duration) OVER win, 0) AS hpm_recieved
           FROM log
           JOIN player_stats AS ps USING (logid)
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=log.logid
               AND cs.steamid64=ps.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class USING (classid)
           LEFT JOIN (SELECT
                   logid,
                   healer,
                   sum(healing) AS healing
               FROM heal_stats
               GROUP BY logid, healer
           ) AS hsg ON (hsg.logid=log.logid AND hsg.healer=ps.steamid64)
           LEFT JOIN heal_stats AS hsr ON (hsr.logid=log.logid AND hsr.healee=ps.steamid64)
           WHERE ps.steamid64 = %(steamid)s
               {}
           WINDOW win AS (
               PARTITION BY ps.steamid64
               ORDER BY log.logid
               GROUPS BETWEEN 19 PRECEDING AND CURRENT ROW
           ) ORDER BY log.logid DESC
           LIMIT 1000;""".format(filter_clauses),
           {'steamid': steamid, **filters})
    trends = list(dict(row) for row in cur)
    trends.reverse()
    return flask.render_template("player/trends.html", trends=trends, filters=filters)
