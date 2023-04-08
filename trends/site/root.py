# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

import flask
from mpmetrics.flask import PrometheusMetrics

from .common import get_logs, get_players, logs_last_modified
from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination, \
                  last_modified
from ..steamid import SteamID

root = flask.Blueprint('root', __name__)

@root.route('/')
def index():
    c = get_db()
    minmax = c.cursor()
    minmax.execute("""SELECT
                          max(time) AS newest,
                          min(time) AS oldest
                      FROM log;""")
    minmax = minmax.fetchone()
    if resp := last_modified(minmax['newest']):
        return resp

    counts = c.cursor()
    counts.execute("""SELECT count(*) FROM log
                      UNION ALL
                      SELECT count(*) FROM player""")
    logs, players = (row[0] for row in counts)
    return flask.render_template("index.html", minmax=minmax, logs=logs, players=players)

@root.route('/favicon.ico')
def favicon():
    return flask.redirect(flask.url_for('static', filename="img/favicon.ico"), 301)

@root.route('/search')
def search():
    q = flask.request.args.get('q', '', str)

    try:
        steamid = SteamID(q)
        cur = get_db().cursor()
        cur.execute(
            """SELECT steamid64
               FROM player_stats
               JOIN player USING (playerid)
               WHERE steamid64 = %s
               LIMIT 1""", (steamid,))
        for (steamid,) in cur:
            return flask.redirect(flask.url_for('player.overview', steamid=steamid), 307)
    except ValueError:
        pass

    return flask.render_template("search.html", q=q, results=get_players(q).fetchall())

@root.route('/leaderboard')
def leaderboard():
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'classid', 'league', 'formatid', 'mapid')

    # Since we are using a cube, we need to explicitly select the NULL rows
    cube_clauses = []
    for (name, column) in (('class', 'classid'), ('format', 'formatid'), ('map', 'mapid')):
        if not filters[name]:
            cube_clauses.append("AND {} ISNULL".format(column))
    if not filters['league']:
        cube_clauses.append("AND league ISNULL")
    cube_clauses = '\n'.join(cube_clauses)

    order, order_clause = get_order({
        'duration': "duration",
        'logs': "logs",
        'winrate': "winrate",
        'rating': "rating",
    }, 'rating')

    db = get_db()
    leaderboard = db.cursor()
    leaderboard.execute("""SELECT
                               name,
                               avatarhash,
                               steamid64,
                               duration,
                               logs,
                               winrate,
                               rating
                           FROM (SELECT
                                   playerid,
                                   sum(duration) AS duration,
                                   sum(wins + losses + ties) AS logs,
                                   sum(0.5 * ties + wins) /
                                       sum(wins + losses + ties) AS winrate,
                                   (50 + sum(0.5 * ties + wins)) /
                                       (100 + sum(wins + losses + ties)) AS rating
                               FROM leaderboard_cube
                               WHERE playerid NOTNULL
                                   {}
                                   {}
                               GROUP BY playerid
                               ORDER BY {} NULLS LAST
                               LIMIT %(limit)s OFFSET %(offset)s
                           ) AS leaderboard
                           LEFT JOIN player USING (playerid)
                           LEFT JOIN name USING (nameid);"""
                           .format(filter_clauses, cube_clauses, order_clause),
                        { **filters, 'limit': limit, 'offset': offset })
    resp = flask.make_response(flask.render_template("leaderboard.html",
                               leaderboard=leaderboard.fetchall()))
    resp.cache_control.max_age = 3600
    return resp

@root.route('/logs')
def logs():
    if resp := logs_last_modified():
        return resp
    return flask.render_template("logs.html", logs=get_logs().fetchall())

@root.route('/log')
def log_form():
    if not (logids := flask.request.args.getlist('id', int)):
        flask.abort(404)
    return flask.redirect(flask.url_for('.log', logids=logids), 301)

@root.route('/log/<intlist:logids>')
def log(logids):
    db = get_db()
    if not logids:
        flask.abort(404)
    elif len(logids) > 10:
        flask.abort(400)

    logs = db.cursor()
    logs.execute("""SELECT
                        logid,
                        time,
                        title,
                        map,
                        format,
                        duration,
                        red_score,
                        blue_score,
                        duplicate_of,
                        demoid,
                        league,
                        matchid,
                        team1_is_red
                    FROM log
                    LEFT JOIN format USING (formatid)
                    JOIN map USING (mapid)
                    WHERE logid IN %s
                    ORDER BY array_position(%s, logid);""", (tuple(logids), logids))
    logs = logs.fetchall()
    logids = tuple(log['logid'] for log in logs)
    if not logids:
        flask.abort(404)
    if resp := last_modified(max(log['time'] for log in logs)):
        return resp

    params = { 'logids': logids, 'llogids': list(logids) }

    matches = db.cursor()
    matches.execute("""SELECT
                           match.league,
                           matchid,
                           competition.name AS comp,
                           division AS div,
                           round,
                           tc1.team_name AS team1,
                           tc2.team_name AS team2,
                           score1,
                           score2,
                           (SELECT
                                   array_agg(map)
                               FROM map
                               JOIN unnest(mapids) AS mapid USING(mapid)
                           ) AS maps,
                           current_logs,
                           full_logs - current_logs AS other_logs
                       FROM (SELECT
                               league,
                               matchid,
                               array_agg(logid) AS current_logs
                           FROM log
                           WHERE logid IN %(logids)s
                           GROUP BY league, matchid
                       ) AS league
                       JOIN match USING (league, matchid)
                       LEFT JOIN div_round USING (league, divid, round_seq)
                       LEFT JOIN comp_round USING (league, compid, round_seq)
                       JOIN round_name ON (
                           round_name.round_nameid = coalesce(div_round.round_nameid,
                                                              comp_round.round_nameid)
                       ) JOIN competition USING (league, compid)
                       LEFT JOIN division USING (league, divid)
                       LEFT JOIN div_name USING (div_nameid)
                       LEFT JOIN (SELECT
                               league,
                               matchid,
                               array_agg(logid) AS full_logs
                           FROM log
                           WHERE duplicate_of ISNULL
                           GROUP BY league, matchid
                       ) AS fl USING (league, matchid)
                       JOIN team_comp AS tc1 ON (
                           tc1.league = match.league
                           AND tc1.compid = match.compid
                           AND tc1.teamid = match.teamid1
                       ) JOIN team_comp AS tc2 ON (
                           tc2.league = match.league
                           AND tc2.compid = match.compid
                           AND tc2.teamid = match.teamid2
                       );""", params)
    matches = { (m['league'], m['matchid']): m for m in matches.fetchall() }

    rounds = db.cursor()
    rounds.execute("""SELECT
                          logid,
                          seq,
                          duration,
                          red_score,
                          blue_score,
                          red_kills,
                          blue_kills,
                          red_dmg,
                          blue_dmg,
                          red_dmg * 60.0 / nullif(duration, 0) AS red_dpm,
                          blue_dmg * 60.0 / nullif(duration, 0) AS blue_dpm,
                          red_ubers,
                          blue_ubers
                      FROM round
                      WHERE logid IN %(logids)s;""", params)

    players = db.cursor()
    players.execute(
        """SELECT
               steamid64,
               players.*,
               class_stats,
               heal_stats.healing,
               healing * 60.0 / nullif(duration, 0) AS hpm,
               avatarhash
           FROM (SELECT
                   playerid,
                   json_object_agg(logid, team) AS teams,
                   array_agg(DISTINCT name ORDER BY name) AS names,
                   sum(kills) AS kills,
                   sum(deaths) AS deaths,
                   sum(assists) AS assists,
                   sum(dmg) AS dmg,
                   sum(dt) AS dt,
                   sum(dmg) * 60.0 / sum(duration) AS dpm,
                   sum(dt) * 60.0 / sum(duration) AS dtm,
                   sum(duration) AS duration,
                   max(lks) AS lks,
                   total(airshots) AS airshots,
                   total(medkits) AS medkits,
                   total(medkits_hp) AS medkits_hp,
                   total(backstabs) AS backstabs,
                   total(headshots) AS headshots,
                   total(headshots_hit) AS headshots_hit,
                   total(sentries) AS sentries,
                   total(cpc) AS cpc,
                   total(ic) AS ic
               FROM log
               JOIN player_stats AS ps USING (logid)
               LEFT JOIN player_stats_extra AS pse USING (logid, playerid)
               LEFT JOIN heal_stats_received AS hsr USING (logid, playerid)
               JOIN name USING (nameid)
               WHERE logid IN %(logids)s
               GROUP BY playerid
           ) AS players
           JOIN player USING (playerid)
           LEFT JOIN ({}) AS cs USING (playerid)
           LEFT JOIN (SELECT
                    healee AS playerid,
                    total(healing) AS healing
                FROM heal_stats
                WHERE logid IN %(logids)s
                GROUP BY healee
           ) AS heal_stats USING (playerid);""".format(
        """SELECT
               playerid,
               array_agg(json_build_object(
                   'classid', classid,
                   'class', class,
                   'duration', classes.duration,
                   'kills', kills,
                   'deaths', deaths,
                   'assists', assists,
                   'dmg', dmg,
                   'dpm', dpm,
                   'pct', classes.duration * 1.0 / logs.duration,
                   'tot_duration', logs.duration,
                   'weapon_stats', weapon_stats
               ) ORDER BY classes.duration DESC) AS class_stats
           FROM (SELECT
                   playerid,
                   classid,
                   sum(duration) AS duration,
                   sum(kills) AS kills,
                   sum(deaths) AS deaths,
                   sum(assists) AS assists,
                   sum(dmg) AS dmg,
                   sum(dmg) * 60.0 / nullif(sum(duration), 0.0) AS dpm
               FROM class_stats
               WHERE logid IN %(logids)s
               GROUP BY playerid, classid
           ) AS classes
           JOIN (SELECT
                  playerid,
                  sum(duration) AS duration
               FROM player_stats
               JOIN log USING (logid)
               WHERE logid IN %(logids)s
               GROUP BY playerid
           ) AS logs USING (playerid)
           LEFT JOIN ({}) AS ws USING (playerid, classid)
           JOIN class USING (classid)
           GROUP BY playerid""".format(
        """SELECT
               playerid,
               classid,
               array_agg(json_build_object(
                   'weapon', weapon,
                   'kills', kills,
                   'dmg', dmg,
                   'shots', shots,
                   'hits', hits,
                   'acc', hits * 1.0 / nullif(shots, 0),
                   'dps', dmg * 1.0 / nullif(shots, 0)
               ) ORDER BY dmg DESC) AS weapon_stats
           FROM (SELECT
                   playerid,
                   classid,
                   weaponid,
                   sum(kills) AS kills,
                   sum(dmg) AS dmg,
                   sum(shots) AS shots,
                   sum(hits) AS hits
               FROM weapon_stats
               WHERE logid IN %(logids)s
               GROUP BY playerid, classid, weaponid
           ) AS weapons
           JOIN class USING (classid)
           JOIN weapon_pretty USING (weaponid)
           GROUP BY playerid, classid"""
    )), params)
    players=players.fetchall()

    # This is difficult to do in SQL, since we don't have any rows for players who didn't play in a
    # log but still played in another log. So instead we do it in python.
    def player_key(player):
        # 500 is probably greater than any teamid :)
        team_map = {
                'Red': 1,
                'Blue': 2,
                None: 500
        }
        teams = (team_map[player['teams'].get(str(logid))] for logid in logids)
        names = player.get('names', ())
        if classes := player.get('class_stats'):
            classes = tuple(cls['classid'] for cls in classes)
        else:
            classes = (500,)
        return (*teams, classes, names)
    players.sort(key=player_key)
    players = { player['steamid64']: player for player in players }

    # This query could be constructed based on the results of the above queries, but for now it is
    # done separately to aid development
    totals = db.cursor()
    totals.execute("""SELECT
                          logid,
                          team,
                          log.duration,
                          sum(kills) AS kills,
                          sum(deaths) AS deaths,
                          sum(assists) AS assists,
                          sum(dmg) AS dmg,
                          sum(dt) AS dt,
                          total(hsr.healing) AS healing,
                          sum(dmg) * 60.0 / log.duration AS dpm,
                          sum(dt) * 60.0 / log.duration AS dtm,
                          total(hsr.healing) * 60.0 / log.duration AS hpm,
                          max(lks) AS lks,
                          total(airshots) AS airshots,
                          total(medkits) AS medkits,
                          total(medkits_hp) AS medkits_hp,
                          total(backstabs) AS backstabs,
                          total(headshots) AS headshots,
                          total(headshots_hit) AS headshots_hit,
                          total(sentries) AS sentries,
                          total(cpc) AS cpc,
                          total(ic) AS ic
                      FROM log
                      JOIN player_stats USING (logid)
                      LEFT JOIN player_stats_extra USING (logid, playerid)
                      LEFT JOIN (SELECT
                              logid,
                              healee AS playerid,
                              sum(healing) AS healing
                          FROM heal_stats
                          WHERE logid IN %(logids)s
                          GROUP BY logid, healee
                      ) AS hsr USING (logid, playerid)
                      WHERE logid IN %(logids)s
                      GROUP BY logid, team
                      ORDER BY array_position(%(llogids)s, logid), team;""", params);

    medics = db.cursor()
    medics.execute("""SELECT
                          teams,
                          steamid64,
                          duration,
                          ubers,
                          medigun_ubers,
                          kritz_ubers,
                          other_ubers,
                          drops,
                          advantages_lost,
                          biggest_advantage_lost,
                          deaths_after_uber,
                          deaths_before_uber,
                          healing,
                          healees,
                          healing * 60.0 / nullif(duration, 0) AS hpm
                      FROM (SELECT
                             json_object_agg(logid, team) AS teams,
                             playerid,
                             sum(coalesce(cs.duration, log.duration)) AS duration,
                             sum(ubers) AS ubers,
                             sum(medigun_ubers) AS medigun_ubers,
                             sum(kritz_ubers) AS kritz_ubers,
                             sum(other_ubers) AS other_ubers,
                             sum(drops) AS drops,
                             sum(advantages_lost) AS advantages_lost,
                             max(biggest_advantage_lost) AS biggest_advantage_lost,
                             sum(deaths_after_uber) AS deaths_after_uber,
                             sum(deaths_before_uber) AS deaths_before_uber
                          FROM medic_stats
                          JOIN player_stats USING (logid, playerid)
                          JOIN log USING (logid)
                          CROSS JOIN class
                          LEFT JOIN class_stats AS cs USING (logid, playerid, classid)
                          WHERE logid IN %(logids)s
                              AND class = 'medic'
                          GROUP BY playerid
                      ) AS medic_stats
                      LEFT JOIN (SELECT
                              healer AS playerid,
                              sum(healing) AS healing,
                              array_agg(json_build_object(
                                  'steamid64', steamid64,
                                  'healing', healing,
                                  'hpm', healing * 60.0 / nullif(duration, 0),
                                  'duration', duration,
                                  'classes', classes,
                                  'class_pcts', (SELECT
                                                     array_agg(duration * 1.0
                                                               / nullif(cs.duration, 0))
                                                 FROM unnest(class_durations) AS duration)
                              ) ORDER BY healing DESC) AS healees
                          FROM (SELECT
                                  healer,
                                  healee,
                                  sum(healing) AS healing
                              FROM heal_stats
                              WHERE logid IN %(logids)s
                              GROUP BY healer, healee
                          ) AS hs
                          JOIN (SELECT
                                  healer,
                                  healee,
                                  sum(duration) AS duration,
                                  array_agg(class ORDER BY duration DESC) AS classes,
                                  array_agg(duration ORDER BY duration DESC) AS class_durations
                              FROM (SELECT
                                      healer,
                                      playerid AS healee,
                                      classid,
                                      sum(duration) AS duration
                                  FROM class_stats AS cs
                                  JOIN heal_stats AS hs ON (
                                      hs.logid = cs.logid
                                      AND hs.healee = cs.playerid
                                  ) WHERE hs.logid IN %(logids)s
                                  GROUP BY healer, playerid, classid
                              ) AS cs
                              JOIN class USING (classid)
                              GROUP BY healer, healee
                          ) AS cs USING (healer, healee)
                          JOIN player ON (player.playerid = healee)
                          GROUP BY healer
                      ) AS heal_stats USING (playerid)
                      JOIN player USING (playerid);""", params);
    medics = medics.fetchall()
    medics.sort(key=player_key)

    events = db.cursor()
    events.execute("""SELECT
                          event,
                          array_agg(json_build_object(
                              'steamid64', steamid64,
                              'demoman', demoman,
                              'engineer', engineer,
                              'heavyweapons', heavyweapons,
                              'medic', medic,
                              'pyro', pyro,
                              'scout', scout,
                              'sniper', sniper,
                              'soldier', soldier,
                              'spy', spy,
                              'total', total
                          ) ORDER BY total DESC) AS events
                      FROM (SELECT
                              eventid,
                              playerid,
                              sum(demoman) AS demoman,
                              sum(engineer) AS engineer,
                              sum(heavyweapons) AS heavyweapons,
                              sum(medic) AS medic,
                              sum(pyro) AS pyro,
                              sum(scout) AS scout,
                              sum(sniper) AS sniper,
                              sum(soldier) AS soldier,
                              sum(spy) AS spy,
                              sum(demoman) + sum(engineer) + sum(heavyweapons) + sum(medic)
                                  + sum(pyro) + sum(scout) + sum(sniper) + sum(soldier) + sum(spy)
                                  AS total
                          FROM event_stats
                          WHERE logid IN %(logids)s
                          GROUP BY eventid, playerid
                      ) AS events
                      JOIN event USING (eventid)
                      JOIN player USING (playerid)
                      GROUP BY event;""", params)
    events = { event_stats['event']: event_stats['events'] for event_stats in events.fetchall() }

    chats = db.cursor()
    chats.execute("""SELECT
                        logid,
                        title,
                        array_agg(json_build_object(
                            'team', team,
                            'steamid64', steamid64,
                            'name', name,
                            'msg', msg
                        ) ORDER BY seq) AS messages
                    FROM (SELECT
                            logid,
                            seq,
                            team,
                            playerid,
                            coalesce(name, 'Console') AS name,
                            msg
                        FROM chat
                        LEFT JOIN player_stats USING (logid, playerid)
                        LEFT JOIN name USING (nameid)
                        WHERE logid IN %(logids)s
                    ) AS chat
                    JOIN log USING (logid)
                    JOIN player USING (playerid)
                    GROUP BY logid, title
                    ORDER BY array_position(%(llogids)s, logid);""", params)

    return flask.render_template("log.html", logids=logids, logs=logs, matches=matches,
                                 rounds=rounds.fetchall(), players=players, totals=totals,
                                 medics=medics, events=events, chats=chats)

metrics_extension = PrometheusMetrics.for_app_factory(group_by='endpoint', path=None)

@root.route('/metrics')
def metrics():
    metrics = metrics_extension.generate_metrics()
    resp = flask.make_response(metrics[0])
    resp.content_type = metrics[1]
    return resp
