# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
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
                    last_name AS name,
                    sum(round_wins) AS round_wins,
                    sum(round_losses) AS round_losses,
                    sum(round_ties) AS round_ties,
                    sum(round_wins > round_losses) AS wins,
                    sum(round_wins < round_losses) AS losses,
                    sum(round_wins == round_losses) AS ties
                FROM log_wlt
                JOIN player USING (steamid64)
                WHERE steamid64 = ?
                GROUP BY steamid64
           );""", (values['steamid'],))

    for row in cur:
        flask.g.player = row
        break
    else:
        flask.abort(404)

def get_logs(c, steamid, limit=100, offset=0):
    return c.cursor().execute(
        """SELECT
               logid,
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
               healing * 60.0 / log.duration AS hpm,
               time
           FROM log_wlt AS log
           JOIN (SELECT
                     logid,
                     steamid64,
                     group_concat(class) OVER (
                         PARTITION BY logid, steamid64
                         ORDER BY duration DESC
                         RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                     ) AS classes
                 FROM class_stats
                 -- Duplicate of below, but sqlite is dumb...
                 WHERE steamid64 = ?
           ) USING (logid, steamid64)
           LEFT JOIN weapon_stats USING (logid, steamid64)
           WHERE steamid64 = ?
           GROUP BY logid
           ORDER BY logid DESC
           LIMIT ? OFFSET ?;""", (steamid, steamid, limit, offset))

@player.route('/')
def overview(steamid):
    c = get_db()
    classes = c.cursor().execute(
        """SELECT
               *,
               (wins + 0.5 * ties) / (wins + losses + ties) AS winrate
           FROM (
               SELECT
                   name,
                   sum(CASE WHEN mostly THEN round_wins > round_losses END) AS wins,
                   sum(CASE WHEN mostly THEN round_wins < round_losses END) AS losses,
                   sum(CASE WHEN mostly THEN round_wins == round_losses END) AS ties,
                   total(duration) time,
                   sum(dmg) * 60.0 / sum(duration) AS dpm,
                   total(hits) / sum(shots) AS acc
               FROM class
               LEFT JOIN (
                   SELECT
                       class,
                       cs.duration * 1.5 > log_wlt.duration AS mostly,
                       round_wins,
                       round_losses,
                       cs.duration,
                       cs.dmg,
                       sum(hits) AS hits,
                       sum(shots) AS shots
                   FROM log_wlt
                   JOIN class_stats cs USING (logid, steamid64)
                   JOIN weapon_stats USING (logid, steamid64, class)
                   WHERE steamid64 = ?
                   GROUP BY logid, steamid64, class
               ) ON (class=name)
           GROUP BY name
           ORDER BY name
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
                   LEFT JOIN event_stats ON (event_stats.event=event.name AND steamid64=?)
               ) GROUP BY event
               -- Dirty hack to fix ordering
               ORDER BY event DESC;""", (steamid,))
    aliases = c.cursor().execute(
            """SELECT
                   name,
                   count(*) AS count
               FROM player_stats
               WHERE steamid64 = ?
               GROUP BY steamid64, name
               ORDER BY count(*) DESC
               LIMIT 10""", (steamid,))
    return flask.render_template("player/overview.html",
                                 logs=get_logs(c, steamid, limit=25), classes=classes,
                                 event_stats=event_stats, aliases=aliases)

@player.route('/logs')
def logs(steamid):
        limit = flask.request.args.get('limit', 100, int)
        offset = flask.request.args.get('offset', 0, int)
        logs = get_logs(get_db(), steamid, limit=limit, offset=offset).fetchall()
        return flask.render_template("player/logs.html", logs=logs, limit=limit, offset=offset)

@player.route('/peers')
def peers(steamid):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    peers = get_db().execute(
        """SELECT
               steamid64,
               max(logid),
               last_name AS name,
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
               sum(CASE WHEN with THEN healing END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS hpm,
               total(CASE WHEN with THEN duration END) as time_with,
               total(CASE WHEN against THEN duration END) as time_against
           FROM (
               SELECT
                   logid,
                   p2.steamid64,
                   p1.team = p2.team AS with,
                   p1.team != p2.team AS against,
                   p1.round_wins > p1.round_losses AS win,
                   p1.round_wins = p1.round_losses AS tie,
                   p1.dmg,
                   p1.dt,
                   p1.healing,
                   p1.duration
               FROM log_wlt AS p1
               JOIN player_stats AS p2 USING (logid)
               WHERE p1.steamid64 = ?
                  AND p2.steamid64 != p1.steamid64
                  AND p2.team NOTNULL
           ) JOIN player USING (steamid64)
           GROUP BY steamid64
           ORDER BY count(*) DESC
           LIMIT ? OFFSET ?;""", (steamid, limit, offset)).fetchall()
    return flask.render_template("player/peers.html", peers=peers, limit=limit, offset=offset)

def get_filters(args):
    ret = {}

    ret['class'] = args.get('class', None, str) or None
    ret['format'] = args.get('format', None, str) or None
    ret['map'] = args.get('map', None, str) or None
    date_from = args.get('date_from', None, datetime.fromisoformat)
    ret['date_from'] = date_from.timestamp() if date_from else None
    date_to = args.get('date_to', None, datetime.fromisoformat)
    ret['date_to'] = args.get('date_to', None, datetime.fromisoformat)
    ret['date_from'] = date_to.timestamp() if date_to else None

    return ret

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
               total(healing) AS healing,
               total(cpc) AS cpc,
               total(ic) AS ic,
               total(ubers) AS ubers,
               total(drops) AS drops,
               total(advantages_lost) AS advantages_lost,
               total(deaths_after_uber) AS deaths_after_uber,
               total(deaths_before_uber) AS deaths_before_uber
           FROM player_stats AS ps
           JOIN log ON (ps.logid=log.logid)
           LEFT JOIN medic_stats AS ms ON (
               ps.logid=ms.logid
               AND ps.steamid64=ms.steamid64)
           LEFT JOIN class_stats AS cs ON (
               cs.logid=ps.logid
               AND cs.steamid64=ps.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) WHERE ps.steamid64 = ?
               AND class IS ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY ps.steamid64;""",
        (steamid, filters['class'], filters['format'], filters['map'], filters['date_from'],
         filters['date_to'])
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
           JOIN class_stats USING (logid, steamid64, class)
           JOIN log USING (logid)
           WHERE steamid64 = ?
               AND class = ifnull(?, class)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY weapon;""",
        (steamid, filters['class'], filters['format'], filters['map'], filters['date_from'],
         filters['date_to']))
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
               sum(log.healing) OVER win * 60.0 /
                   sum(CASE WHEN log.healing THEN log.duration END) OVER win AS hpm
           FROM log_wlt AS log
           LEFT JOIN class_stats AS cs ON (
               cs.logid=log.logid
               AND cs.steamid64=log.steamid64
               AND cs.duration * 1.5 >= log.duration
           ) WHERE log.steamid64 = ?
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
           );""", (steamid, filters['class'], filters['format'], filters['map'],
                  filters['date_from'], filters['date_to']))
    trends = list(dict(row) for row in cur)
    return flask.render_template("player/trends.html", trends=trends, filters=filters)
