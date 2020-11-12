# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
import flask

from trends import get_db

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

@player.app_template_filter('date')
def date_filter(timestamp):
    return datetime.fromtimestamp(timestamp)

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
                 last_value(name) OVER (
                     ORDER BY logid
                 ) as name,
                 sum(round_wins) AS round_wins,
                 sum(round_losses) AS round_losses,
                 sum(round_ties) AS round_ties,
                 sum(round_wins > round_losses) AS wins,
                 sum(round_wins < round_losses) AS losses,
                 sum(round_wins == round_losses) AS ties
             FROM log_wlt
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
                           GROUPS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS classes
                   FROM class_stats
               ) USING (logid, steamid64)
               LEFT JOIN weapon_stats USING (logid, steamid64)
               WHERE steamid64 = ?
               GROUP BY logid
               ORDER BY logid DESC
               LIMIT ? OFFSET ?;""", (steamid, limit, offset))

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
               FROM (
                   SELECT
                       class.name,
                       cs.duration * 1.5 > log_wlt.duration AS mostly,
                       round_wins,
                       round_losses,
                       cs.duration,
                       cs.dmg,
                       sum(hits) AS hits,
                       sum(shots) AS shots
                   FROM class
                   LEFT JOIN class_stats cs ON (cs.class=class.name AND steamid64=?)
                   LEFT JOIN log_wlt USING (logid, steamid64)
                   LEFT JOIN weapon_stats USING (logid, steamid64, class)
                   GROUP BY logid, steamid64, class.name
           )
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
    return flask.render_template("player/overview.html",
                                 logs=get_logs(c, steamid, limit=25), classes=classes,
                                 event_stats=event_stats)

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
               sum(CASE WHEN with THEN healing END) * 60.0 /
                   sum(CASE WHEN with THEN duration END) AS hpm,
               total(CASE WHEN with THEN duration END) as time_with,
               total(CASE WHEN against THEN duration END) as time_against
           FROM (
               SELECT
                   p2.steamid64,
                   p2.name,
                   p1.team = p2.team AS with,
                   p1.team != p2.team AS against,
                   p1.round_wins > p1.round_losses AS win,
                   p1.round_wins = p1.round_losses AS tie,
                   p1.dmg,
                   p1.dt,
                   p1.healing,
                   p1.duration
               FROM log_wlt AS p1
               JOIN log_wlt AS p2 USING (logid)
               WHERE p1.steamid64 = ?
                  AND p2.steamid64 != p1.steamid64
                  AND p2.team NOTNULL
           ) GROUP BY steamid64
           ORDER BY count(*) DESC
           LIMIT ? OFFSET ?;""", (steamid, limit, offset)).fetchall()
    return flask.render_template("player/peers.html", peers=peers, limit=limit, offset=offset)

@player.route('/totals')
def totals(steamid):
    totals = get_db().cursor().execute(
        """SELECT
               total(kills) AS kills,
               total(deaths) AS deaths,
               total(assists) AS assists,
               total(duration) AS duration,
               total(dmg) AS dmg,
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
           FROM log
           JOIN player_stats USING (logid)
           LEFT JOIN medic_stats USING (logid, steamid64)
           WHERE steamid64 = ?;""", (steamid,)).fetchone()
    return flask.render_template("player/totals.html", totals=totals)

@player.route('/weapons')
def weapons(steamid):
    weapons = get_db().cursor().execute(
        """SELECT
               weapon,
               avg(ws.kills) as kills,
               sum(ws.dmg) * 60.0 / sum(CASE WHEN ws.dmg THEN duration END) AS dpm,
               total(hits) / sum(shots) AS acc
           FROM weapon_stats AS ws
           JOIN class_stats USING (logid, steamid64, class)
           WHERE steamid64 = ?
           GROUP BY weapon;""", (steamid,))
    return flask.render_template("player/weapons.html", weapons=weapons)

@player.route('/trends')
def trends(steamid):
    args = flask.request.args
    cls = args.get('class', None, str) or None
    weapon = args.get('weapon', None, str) or None
    fmt = args.get('format', None, str) or None
    map = args.get('map', None, str) or None
    date_from = args.get('date_from', None, datetime.fromisoformat)
    if date_from:
        date_from = date_from.timestamp()
    date_to = args.get('date_to', None, datetime.fromisoformat)
    if date_to:
        date_to = date_to.timestamp()

    cur = get_db().cursor().execute(
        """SELECT
               logid,
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
                   sum(CASE WHEN log.healing THEN log.duration END) OVER win AS hpm,
               total(hits) OVER win / sum(shots) OVER win AS acc
           FROM log_wlt AS log
           JOIN class_stats USING (logid, steamid64)
           JOIN weapon_stats USING (logid, steamid64, class)
           WHERE steamid64 = ?
               AND class = ifnull(?, class)
               AND weapon = ifnull(?, weapon)
               AND format = ifnull(?, format)
               AND map LIKE ifnull(?, map)
               AND time >= ifnull(?, time)
               AND time <= ifnull(?, time)
           GROUP BY logid, steamid64
           WINDOW win AS (
               PARTITION BY steamid64
               ORDER BY logid
               GROUPS BETWEEN 19 PRECEDING AND CURRENT ROW
           )""", (steamid, cls, weapon, fmt, map, date_from, date_to))
    trends = list(dict(row) for row in cur)
    return flask.render_template("player/trends.html", trends=trends)
