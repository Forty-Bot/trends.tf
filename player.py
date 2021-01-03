# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
from dateutil import tz
import flask

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

@player.url_value_preprocessor
def get_player(endpoint, values):
    flask.g.steamid = values['steamid']
    cur = get_db().cursor().execute(
        """SELECT
               *,
               (wins + 0.5 * ties) /
                   (wins + losses + ties) AS winrate,
               (round_wins + 0.5 * round_ties) /
                   (round_wins + round_losses + round_ties) AS round_winrate
           FROM (
                SELECT
                    steamid64,
                    name,
                    sum(round_wins) AS round_wins,
                    sum(round_losses) AS round_losses,
                    sum(round_ties) AS round_ties,
                    sum(round_wins > round_losses) AS wins,
                    sum(round_wins < round_losses) AS losses,
                    sum(round_wins == round_losses) AS ties
                FROM log_wlt
                JOIN player USING (steamid64)
                JOIN name ON (name.nameid=last_nameid)
                WHERE steamid64 = ?
                GROUP BY steamid64
           );""", (values['steamid'],))

    for row in cur:
        flask.g.player = row
        break
    else:
        flask.abort(404)

def get_filters(args):
    ret = {}

    ret['class'] = args.get('class', None, str) or None
    ret['format'] = args.get('format', None, str) or None
    ret['map'] = args.get('map', None, str) or None

    timezone = args.get('timezone', tz.UTC, tz.gettz)

    def parse_date(name):
        date = args.get(name, None, datetime.fromisoformat)
        if date:
            date.replace(tzinfo=timezone)
            return (date.date().isoformat(), date.timestamp())
        return (None, None)

    (ret['date_from'], ret['date_from_ts']) = parse_date('date_from')
    (ret['date_to'], ret['date_to_ts']) = parse_date('date_to')

    return ret

def get_logs(c, steamid, filters, limit=100, offset=0):
    return c.cursor().execute(
        """SELECT
               log.logid,
               title,
               map,
               classes,
               round_wins AS wins,
               round_losses AS losses,
               round_ties AS ties,
               format,
               log.duration,
               log.kills,
               log.deaths,
               log.assists,
               log.dmg * 60.0 / log.duration AS dpm,
               log.dt * 60.0 / log.duration AS dtm,
               total(hits) / total(shots) AS acc,
               total(hsg.healing) * 60.0 / log.duration AS hpm_given,
               hsr.healing * 60.0 / log.duration AS hpm_recieved,
               time
           FROM log_wlt AS log
           JOIN map USING (mapid)
           JOIN format USING (formatid)
           JOIN (SELECT
                     logid,
                     steamid64,
                     group_concat(class) OVER (
                         PARTITION BY logid, steamid64
                         ORDER BY duration DESC
                         ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                     ) AS classes
                 FROM class_stats
                 JOIN class USING (classid)
                 -- Duplicate of below, but sqlite is dumb...
                 WHERE steamid64 = ?
           ) USING (logid, steamid64)
           LEFT JOIN weapon_stats USING (logid, steamid64)
           LEFT JOIN heal_stats AS hsg ON (hsg.healer=log.steamid64 AND hsg.logid=log.logid)
           LEFT JOIN heal_stats AS hsr ON (hsr.healee=log.steamid64 AND hsr.logid=log.logid)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=log.logid
               AND cs.steamid64=log.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class USING (classid)
           WHERE log.steamid64 = ?
               AND class IS ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY log.logid
           ORDER BY log.logid DESC
           LIMIT ? OFFSET ?;""",
           (steamid, steamid, filters['class'], filters['format'], filters['map'],
            filters['date_from_ts'], filters['date_to_ts'], limit, offset))

@player.route('/')
def overview(steamid):
    c = get_db()
    classes = c.cursor().execute(
        """SELECT
               *,
               (wins + 0.5 * ties) / (wins + losses + ties) AS winrate
           FROM (
               SELECT
                   class,
                   sum(CASE WHEN mostly THEN round_wins > round_losses END) AS wins,
                   sum(CASE WHEN mostly THEN round_wins < round_losses END) AS losses,
                   sum(CASE WHEN mostly THEN round_wins == round_losses END) AS ties,
                   total(duration) time,
                   sum(dmg) * 60.0 / sum(duration) AS dpm,
                   total(hits) / sum(shots) AS acc
               FROM class
               LEFT JOIN (
                   SELECT
                       classid,
                       cs.duration * 1.5 > log_wlt.duration AS mostly,
                       round_wins,
                       round_losses,
                       cs.duration,
                       cs.dmg,
                       sum(hits) AS hits,
                       sum(shots) AS shots
                   FROM log_wlt
                   JOIN class_stats cs USING (logid, steamid64)
                   JOIN weapon_stats USING (logid, steamid64, classid)
                   WHERE steamid64 = ?
                   GROUP BY logid, steamid64, classid
               ) USING (classid)
               GROUP BY classid
               ORDER BY classid
           );""", (steamid,))
    event_stats = c.cursor().execute(
            """SELECT
                   event,
                   avg(demoman) AS demoman,
                   avg(engineer) AS engineer,
                   avg(heavyweapons) AS heavyweapons,
                   avg(medic) AS medic,
                   avg(pyro) AS pyro,
                   avg(scout) AS scout,
                   avg(sniper) AS sniper,
                   avg(soldier) AS soldier,
                   avg(spy) AS spy
               FROM (
                   SELECT *
                   FROM event
                   LEFT JOIN event_stats ON (event_stats.eventid=event.eventid AND steamid64=?)
               ) GROUP BY event
               ORDER BY event DESC;""", (steamid,))
    aliases = c.cursor().execute(
            """SELECT
                   name,
                   count(*) AS count
               FROM player_stats
               JOIN name USING (nameid)
               WHERE steamid64 = ?
               GROUP BY steamid64, name
               ORDER BY count(*) DESC
               LIMIT 10""", (steamid,))
    logs = get_logs(c, steamid, get_filters(flask.request.args), limit=25)
    return flask.render_template("player/overview.html", logs=logs, classes=classes,
                                 event_stats=event_stats, aliases=aliases)

@player.route('/logs')
def logs(steamid):
        limit = flask.request.args.get('limit', 100, int)
        offset = flask.request.args.get('offset', 0, int)
        filters = get_filters(flask.request.args)
        logs = get_logs(get_db(), steamid, filters, limit=limit, offset=offset).fetchall()
        return flask.render_template("player/logs.html", logs=logs, filters=filters, limit=limit,
                                     offset=offset)

@player.route('/peers')
def peers(steamid):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    peers = get_db().execute(
        """SELECT
               steamid64,
               max(logid),
               name,
               total(with) AS with,
               total(against) AS against,
               (sum(CASE WHEN with THEN win END) +
                   0.5 * sum(CASE WHEN with THEN tie END)) / sum(with) AS winrate_with,
               (sum(CASE WHEN against THEN win END) +
                   0.5 * sum(CASE WHEN against THEN tie END)) / sum(against) AS winrate_against,
               sum(CASE WHEN with THEN dmg END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS dpm,
               sum(CASE WHEN with THEN dt END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS dtm,
               sum(CASE WHEN with THEN healing_to END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS hpm_to,
               sum(CASE WHEN with THEN healing_from END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS hpm_from,
               total(CASE WHEN with THEN duration END) as time_with,
               total(CASE WHEN against THEN duration END) as time_against
           FROM (
               SELECT
                   p1.logid,
                   p2.steamid64,
                   p1.teamid = p2.teamid AS with,
                   p1.teamid != p2.teamid AS against,
                   p1.round_wins > p1.round_losses AS win,
                   p1.round_wins = p1.round_losses AS tie,
                   p1.dmg,
                   p1.dt,
                   hs1.healing AS healing_to,
                   hs2.healing AS healing_from,
                   p1.duration
               FROM log_wlt AS p1
               JOIN player_stats AS p2 USING (logid)
               LEFT JOIN heal_stats AS hs1 ON (
                   hs1.healer = p1.steamid64
                   AND hs1.healee = p2.steamid64
                   AND hs1.logid = p1.logid
               ) LEFT JOIN heal_stats AS hs2 ON (
                   hs2.healer = p2.steamid64
                   AND hs2.healee = p1.steamid64
                   AND hs2.logid = p1.logid
               ) WHERE p1.steamid64 = ?
                  AND p2.steamid64 != p1.steamid64
                  AND p2.teamid NOTNULL
           ) JOIN player USING (steamid64)
           JOIN name ON (name.nameid=last_nameid)
           GROUP BY steamid64
           ORDER BY count(*) DESC
           LIMIT ? OFFSET ?;""", (steamid, limit, offset)).fetchall()
    return flask.render_template("player/peers.html", peers=peers, limit=limit, offset=offset)

@player.route('/totals')
def totals(steamid):
    filters = get_filters(flask.request.args)
    totals = get_db().cursor().execute(
        """SELECT
               count(*) AS logs,
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
               total(hs.healing) AS healing,
               total(cpc) AS cpc,
               total(ic) AS ic,
               total(ubers) AS ubers,
               total(drops) AS drops,
               total(advantages_lost) AS advantages_lost,
               total(deaths_after_uber) AS deaths_after_uber,
               total(deaths_before_uber) AS deaths_before_uber
           FROM player_stats AS ps
           JOIN log ON (ps.logid=log.logid)
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           LEFT JOIN medic_stats AS ms ON (
               ms.logid=ps.logid
               AND ms.steamid64=ps.steamid64)
           LEFT JOIN heal_stats AS hs ON (
               hs.logid=ps.logid
               AND hs.healer=ps.steamid64
           ) LEFT JOIN class_stats AS cs ON (
               cs.logid=ps.logid
               AND cs.steamid64=ps.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class USING (classid)
           WHERE ps.steamid64 = ?
               AND class IS ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time);""",
        (steamid, filters['class'], filters['format'], filters['map'], filters['date_from_ts'],
         filters['date_to_ts'])
    ).fetchone()
    return flask.render_template("player/totals.html", totals=totals, filters=filters)

@player.route('/weapons')
def weapons(steamid):
    filters = get_filters(flask.request.args)
    weapons = get_db().cursor().execute(
        """SELECT
               weapon,
               avg(ws.kills) as kills,
               sum(ws.dmg) * 60.0 / sum(CASE WHEN ws.dmg THEN class_stats.duration END) AS dpm,
               total(hits) / sum(shots) AS acc
           FROM weapon_stats AS ws
           JOIN weapon USING (weaponid)
           JOIN class_stats USING (logid, steamid64, classid)
           JOIN class USING (classid)
           JOIN log USING (logid)
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           WHERE steamid64 = ?
               AND class = ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY weapon;""",
        (steamid, filters['class'], filters['format'], filters['map'], filters['date_from_ts'],
         filters['date_to_ts']))
    return flask.render_template("player/weapons.html", weapons=weapons, filters=filters)

@player.route('/trends')
def trends(steamid):
    filters = get_filters(flask.request.args)
    cur = get_db().cursor().execute(
        """SELECT
               log.logid,
               time,
               (sum(round_wins > round_losses) OVER win +
                   0.5 * sum(round_wins = round_losses) OVER win) /
                   count(*) OVER win AS winrate,
               (sum(round_wins + 0.5 * round_ties) OVER win)
                   / sum(round_wins + round_losses + round_ties) OVER win AS round_winrate,
               avg(log.kills) OVER win AS kills,
               avg(log.deaths) OVER win AS deaths,
               avg(log.assists) OVER win AS assists,
               sum(log.dmg) OVER win * 60.0 /
                   sum(CASE WHEN log.dmg THEN log.duration END) OVER win AS dpm,
               sum(log.dt) OVER win * 60.0 /
                   sum(CASE WHEN log.dt THEN log.duration END) OVER win AS dtm,
               sum(hsg.healing) OVER win * 60.0 /
                   sum(CASE WHEN hsg.healing THEN log.duration END) OVER win AS hpm_given,
               sum(hsr.healing) OVER win * 60.0 /
                   sum(CASE WHEN hsr.healing THEN log.duration END) OVER win AS hpm_recieved
           FROM log_wlt AS log
           JOIN format USING (formatid)
           JOIN map USING (mapid)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=log.logid
               AND cs.steamid64=log.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) LEFT JOIN class USING (classid)
           LEFT JOIN (SELECT
                   logid,
                   healer,
                   sum(healing) AS healing
               FROM heal_stats
               GROUP BY logid, healer
           ) AS hsg ON (hsg.logid=log.logid AND hsg.healer=log.steamid64)
           LEFT JOIN heal_stats AS hsr ON (hsr.logid=log.logid AND hsr.healee=log.steamid64)
           WHERE log.steamid64 = ?
               AND class IS ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY log.logid, log.steamid64
           WINDOW win AS (
               PARTITION BY log.steamid64
               ORDER BY log.logid
               GROUPS BETWEEN 19 PRECEDING AND CURRENT ROW
           ) ORDER BY log.logid DESC
           LIMIT 1000;""", (steamid, filters['class'], filters['format'], filters['map'],
                              filters['date_from_ts'], filters['date_to_ts']))
    trends = list(dict(row) for row in cur)
    trends.reverse()
    return flask.render_template("player/trends.html", trends=trends, filters=filters)
