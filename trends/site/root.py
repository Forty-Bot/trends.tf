# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

from collections import defaultdict

import flask
from mpmetrics.flask import PrometheusMetrics

from ..cache import cache_result
from .common import get_logs, search_players, logs_last_modified
from .util import get_db, get_filter_params, get_filter_clauses, get_mc, get_order, \
                  get_pagination, last_modified
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

@root.route('/about')
def about():
    resp = flask.make_response(flask.render_template("about.html"))
    resp.cache_control.max_age = 300
    return resp

@root.route('/apidoc')
def api():
    resp = flask.make_response(flask.render_template("api.html"))
    resp.cache_control.max_age = 300
    return resp

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

    return flask.render_template("search.html", q=q, results=search_players(q).fetchall())

@root.route('/leaderboard')
def leaderboard():
    return flask.redirect(flask.url_for('leaderboards.overview'), 301)

@root.route('/logs')
def logs():
    if resp := logs_last_modified():
        return resp
    return flask.render_template("logs.html", logs=get_logs('basic').fetchall())

@root.route('/log')
def log_form():
    if not (logids := flask.request.args.getlist('id', int)):
        flask.abort(404)
    return flask.redirect(flask.url_for('.log', logids=logids), 301)

@cache_result("log_{}")
def get_log(mc, logid):
    log = {}
    params = { 'logid': logid }
    cur = get_db().cursor()

    cur.execute("""SELECT
                       logid,
                       time,
                       updated,
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
                   WHERE logid = %(logid)s;""", params)
    log['summary'] = cur.fetchone()
    if not log['summary']:
        return log
    log['summary'] = dict(log['summary'])

    cur.execute("""SELECT
                       league,
                       matchid,
                       compid,
                       comp,
                       div,
                       round,
                       teamid1,
                       teamid2,
                       team1,
                       team2,
                       score1,
                       score2,
                       forfeit,
                       maps,
                       full_logs
                   FROM match_pretty AS match
                   LEFT JOIN LATERAL (SELECT
                           league,
                           matchid,
                           array_agg(logid) AS full_logs
                       FROM log_nodups
                       WHERE league = match.league AND matchid = match.matchid
                       GROUP BY league, matchid
                   ) AS fl USING (league, matchid)
                   WHERE league = %s AND matchid = %s;""",
                (log['summary']['league'], log['summary']['matchid']))
    if m := cur.fetchone():
        log['match'] = dict(m)

    cur.execute("""SELECT
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
                   WHERE logid = %(logid)s;""", params)
    log['rounds'] = [dict(round) for round in cur]

    cur.execute(
        """SELECT
               steamid64,
               class_stats,
               heal_stats.healing,
               avatarhash,
               team,
               name,
               kills,
               deaths,
               assists,
               dmg,
               dt,
               duration,
               lks,
               airshots,
               medkits,
               medkits_hp,
               backstabs,
               headshots,
               headshots_hit,
               sentries,
               cpc,
               ic
           FROM log
           JOIN player_stats AS ps USING (logid)
           LEFT JOIN player_stats_extra AS pse USING (logid, playerid)
           LEFT JOIN heal_stats_received AS hsr USING (logid, playerid)
           JOIN name USING (nameid)
           JOIN player USING (playerid)
           LEFT JOIN (SELECT
                   playerid,
                   array_agg(json_build_object(
                       'classid', classid,
                       'class', class,
                       'duration', class_stats.duration,
                       'kills', kills,
                       'deaths', deaths,
                       'assists', assists,
                       'dmg', dmg,
                       'weapon_stats', weapon_stats
                   ) ORDER BY class_stats.duration DESC) AS class_stats
               FROM class_stats
               LEFT JOIN (SELECT
                       playerid,
                       classid,
                       array_agg(json_build_object(
                           'weaponid', weaponid,
                           'weapon', weapon,
                           'kills', kills,
                           'dmg', dmg,
                           'shots', shots,
                           'hits', hits
                       ) ORDER BY dmg DESC) AS weapon_stats
                   FROM weapon_stats
                   JOIN weapon_pretty USING (weaponid)
                   WHERE logid = %(logid)s
                   GROUP BY playerid, classid) AS ws USING (playerid, classid)
               JOIN class USING (classid)
               WHERE logid = %(logid)s
               GROUP BY playerid) AS cs USING (playerid)
           LEFT JOIN (SELECT
                    healee AS playerid,
                    total(healing) AS healing
                FROM heal_stats
                WHERE logid = %(logid)s
                GROUP BY healee
           ) AS heal_stats USING (playerid)
           WHERE logid = %(logid)s;""", params)
    log['players'] = [dict(player) for player in cur]

    # This query could be constructed based on the results of the above queries, but for now it is
    # done separately to aid development
    cur.execute("""SELECT
                       logid,
                       team,
                       log.duration,
                       sum(kills) AS kills,
                       sum(deaths) AS deaths,
                       sum(assists) AS assists,
                       sum(dmg) AS dmg,
                       sum(dt) AS dt,
                       total(hsr.healing) AS healing,
                       sum(dmg) * 60.0 / nullif(log.duration, 0) AS dpm,
                       sum(dt) * 60.0 / nullif(log.duration, 0) AS dtm,
                       total(hsr.healing) * 60.0 / nullif(log.duration, 0) AS hpm,
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
                           healee AS playerid,
                           sum(healing) AS healing
                       FROM heal_stats
                       WHERE logid = %(logid)s
                       GROUP BY healee
                   ) AS hsr USING (playerid)
                   WHERE logid = %(logid)s
                   GROUP BY logid, team
                   ORDER BY logid, team;""", params);
    log['totals'] = [dict(total) for total in cur]

    cur.execute("""SELECT
                       team,
                       steamid64,
                       coalesce(cs.duration, log.duration) AS duration,
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
                       healees
                   FROM medic_stats
                   JOIN player USING (playerid)
                   JOIN log USING (logid)
                   JOIN player_stats USING (logid, playerid)
                   CROSS JOIN class
                   LEFT JOIN class_stats AS cs USING (logid, playerid, classid)
                   LEFT JOIN (SELECT
                           healer AS playerid,
                           sum(healing) AS healing,
                           array_agg(json_build_object(
                               'steamid64', steamid64,
                               'healing', healing,
                               'duration', duration,
                               'classes', classes
                           ) ORDER BY healing DESC) AS healees
                       FROM heal_stats
                       JOIN (SELECT
                               healer,
                               playerid AS healee,
                               sum(duration) AS duration,
                               json_object_agg(class, duration ORDER BY duration DESC) AS classes
                           FROM class_stats AS cs
                           JOIN class USING (classid)
                           JOIN heal_stats AS hs ON (
                               hs.logid = cs.logid
                               AND hs.healee = cs.playerid
                           ) WHERE hs.logid = %(logid)s
                           GROUP BY healer, playerid
                       ) AS cs USING (healer, healee)
                       JOIN player ON (player.playerid = healee)
                       WHERE logid = %(logid)s
                       GROUP BY healer
                   ) AS heal_stats USING (playerid)
                   WHERE logid = %(logid)s AND class = 'medic';""", params);
    log['medics'] = [dict(medic) for medic in cur]

    cur.execute("""SELECT
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
                           'total', demoman + engineer + heavyweapons + medic + pyro +
                                    scout + sniper + soldier + spy
                       )) AS events
                   FROM event_stats
                   JOIN player USING (playerid)
                   JOIN event USING (eventid)
                   WHERE logid = %(logid)s
                   GROUP BY event;""", params)
    for e in cur:
        log[e['event']] = e['events']

    cur.execute("""SELECT
                       team,
                       steamid64,
                       name,
                       time,
                       killstreak.kills
                   FROM killstreak
                   JOIN player_stats USING (logid, playerid)
                   JOIN name USING (nameid)
                   JOIN player USING (playerid)
                   WHERE logid = %(logid)s
                   ORDER BY killstreak.time;""", params)
    log['ks'] = [dict(ks) for ks in cur]

    cur.execute("""SELECT
                       team,
                       steamid64,
                       coalesce(name, 'Console') AS name,
                       msg
                   FROM chat
                   LEFT JOIN player_stats USING (logid, playerid)
                   LEFT JOIN name USING (nameid)
                   LEFT JOIN player USING (playerid)
                   WHERE logid = %(logid)s
                   ORDER BY seq;""", params)
    log['chat'] = [dict(msg) for msg in cur]

    return log

@root.route('/log/<intlist:logids>')
def log(logids):
    if not logids:
        flask.abort(404)
    elif len(logids) > 10:
        flask.abort(400)

    logs = {}
    mc = get_mc()
    for logid in dict.fromkeys(logids):
        log = get_log(mc, logid)
        if log['summary']:
            logs[logid] = log

    if not logs:
        flask.abort(404)
    if resp := last_modified(max(log['summary']['updated'] for log in logs.values())):
        return resp

    def player_key(player):
        # 500 is probably greater than any teamid :)
        team_map = {
                'Red': 1,
                'Blue': 2,
                None: 500
        }
        teams = (team_map[player['teams'].get(logid)] for logid in logs)
        names = player.get('names', ())
        if classes := player.get('class_stats'):
            classes = tuple(cls['classid'] for cls in classes)
        else:
            classes = (500,)
        return (*teams, classes, names)

    matches = {}
    logid_set = set(logids)
    for logid, log in logs.items():
        if (m := log.get('match')) is None:
            continue

        key = m['league'], m['matchid']
        if key not in matches:
            m['full_logs'] = set(m['full_logs'])
            matches[key] = m
        matches[key]['full_logs'].add(logid)

    for m in matches.values():
        m['other_logs'] = list(m['full_logs'].difference(logid_set))
        m['current_logs'] = list(m['full_logs'].intersection(logid_set))

    rounds = []
    totals = []
    for log in logs.values():
        rounds.extend(log['rounds'])
        totals.extend(log['totals'])

    players = {}
    player_stats = (
        'kills',
        'deaths',
        'assists',
        'dmg',
        'duration',
        'airshots',
        'medkits',
        'medkits_hp',
        'backstabs',
        'headshots',
        'headshots_hit',
        'sentries',
        'cpc',
        'ic',
    )
    class_stats = (
        'kills',
        'deaths',
        'assists',
        'dmg',
        'duration',
    )
    weapon_stats = (
        'kills',
        'dmg',
        'shots',
        'hits',
    )
    for logid, log in logs.items():
        for u in log.get('players'):
            steamid = u['steamid64']
            if steamid in players:
                c = players[steamid]
                for stat in player_stats:
                    c[stat] += u[stat] or 0

                if c['dt'] is None:
                    c['dt'] = u['dt']
                else:
                    c['dt'] += u['dt'] or 0

                if c['healing'] is None:
                    c['healing'] = u['healing']
                else:
                    c['healing'] += u['healing'] or 0

                if c['lks'] is None or (u['lks'] is not None and u['lks'] > c['lks']):
                    c['lks'] = u['lks']          

                c['teams'][logid] = u['team']
                c['names'].add(u['name'])

                for uc in u['class_stats'] or ():
                    classid = uc['classid']
                    if classid in c['class_stats']:
                        cc = c['class_stats'][classid]
                        for stat in class_stats:
                            cc[stat] += uc[stat]

                        for uw in uc['weapon_stats'] or ():
                            weaponid = uw['weaponid']
                            if weaponid in cc['weapon_stats']:
                                cw = cc['weapon_stats'][weaponid]
                                for stat in weapon_stats:
                                    if cw[stat] is None:
                                        cw[stat] = uw[stat]
                                    else:
                                        cw[stat] += uw[stat] or 0
                            else:
                                cc['weapon_stats'][weaponid] = uw
                    else:
                        uc['weapon_stats'] = { uw['weaponid']: uw
                                               for uw in uc['weapon_stats'] or () }
                        c['class_stats'][classid] = uc
            else:
                c = { stat: u[stat] or 0 for stat in player_stats }
                c['dt'] = u['dt']
                c['healing'] = u['healing']
                c['lks'] = u['lks']
                c['teams'] = { logid: u['team'] }
                c['names'] = set((u['name'],))
                c['steamid64'] = steamid
                c['class_stats'] = {}
                for uc in u['class_stats'] or ():
                    uc['weapon_stats'] = { uw['weaponid']: uw for uw in uc['weapon_stats'] or () }
                    c['class_stats'][uc['classid']] = uc
                players[steamid] = c

    for player in players.values():
        player['names'] = sorted(player['names'])
        if player['duration']:
            player['dpm'] = player['dmg'] * 60 / player['duration']
            if player['dt'] is None:
                player['dtm'] = None
            else:
                player['dtm'] = player['dt'] * 60 / player['duration']
            if player['healing'] is None:
                player['hpm'] = None
            else:
                player['hpm'] = player['healing'] * 60 / player['duration']
        else:
            player['dpm'] = None
            player['dtm'] = None
            player['hpm'] = None

        player['class_stats'] = sorted(player['class_stats'].values(), reverse=True,
                                       key=lambda cls: cls['duration'])
        for cls in player['class_stats']:
            cls['pct'] = cls['duration'] / player['duration'] if player['duration'] else None
            cls['dpm'] = cls['dmg'] * 60 / cls['duration'] if cls['duration'] else None

            cls['weapon_stats'] = sorted(cls['weapon_stats'].values(), reverse=True,
                                         key=lambda w: (w['dmg'], -w['weaponid']))
            for weapon in cls['weapon_stats']:
                if weapon['shots']:
                    weapon['acc'] = weapon['hits'] / weapon['shots']
                    if weapon['dmg'] is None:
                        weapon['dps'] = None
                    else:
                        weapon['dps'] = weapon['dmg'] / weapon['shots']
                else:
                    weapon['acc'] = None
                    weapon['dps'] = None

    players = { player['steamid64']: player for player in
                sorted(players.values(), key=player_key) }

    medics = {}
    stats = (
        'duration',
        'ubers',
        'medigun_ubers',
        'kritz_ubers',
        'other_ubers',
        'drops',
        'advantages_lost',
        'deaths_after_uber',
        'deaths_before_uber',
        'healing',
    )
    for logid, log in logs.items():
        for u in log['medics'] or ():
            steamid = u['steamid64']
            if steamid in medics:
                c = medics[steamid]
                for stat in stats:
                    if c[stat] is None:
                        c[stat] = u[stat]
                    else:
                        c[stat] += u[stat] or 0

                stat = 'biggest_advantage_lost'
                if c[stat] is None or (u[stat] is not None and u[stat] > c[stat]):
                    c[stat] = u[stat]

                c['teams'][logid] = u['team']
                for uh in u['healees'] or ():
                    steamid = uh['steamid64']
                    if steamid in c['healees']:
                        ch = c['healees'][steamid]
                        ch['healing'] += uh['healing']
                        ch['duration'] += uh['duration']

                        for uhc, uhd in uh['classes'].items():
                            if uhc in ch['classes']:
                                ch['classes'][uhc] += uhd
                            else:
                                ch['classes'][uhc] = uhd
                    else:
                        c['healees'][steamid] = uh
            else:
                c = { stat: u[stat] for stat in stats }
                c['steamid64'] = steamid
                c['biggest_advantage_lost'] = u['biggest_advantage_lost']
                c['teams'] = { logid: u['team'] }
                c['healees'] = { healee['steamid64']: healee for healee in u['healees'] or () }
                medics[steamid] = c

    medics = sorted(medics.values(), key=player_key)
    for medic in medics:
        if not medic['duration'] or medic['healing'] is None:
            medic['hpm'] = None
        else:
            medic['hpm'] = medic['healing'] * 60 / medic['duration']
        medic['healees'] = sorted(medic['healees'].values(), reverse=True,
                                  key=lambda healee: healee['healing'])
        for healee in medic['healees']:
            classes = sorted(healee['classes'].items(), key=lambda cls: cls[1], reverse=True)
            healee['classes'] = [cls[0] for cls in classes]
            if healee['duration']:
                healee['hpm'] = healee['healing'] * 60 / healee['duration']
                healee['class_pcts'] = [cls[1] / healee['duration'] for cls in classes]
            else:
                healee['hpm'] = None
                healee['class_pcts'] = [None] * len(classes)

    events = {}
    stats = (
        'scout',
        'soldier',
        'pyro',
        'demoman',
        'heavyweapons',
        'engineer',
        'medic',
        'sniper',
        'spy',
        'total',
    )
    for event in ('kill', 'death', 'assist'):
        events[event] = {}
        for log in logs.values():
            for u in log.get(event, ()):
                steamid = u['steamid64']
                if steamid in events[event]:
                    c = events[event][steamid]
                    for stat in stats:
                        c[stat] += u[stat]
                else:
                    c = { stat: u[stat] for stat in stats }
                    c['steamid64'] = steamid
                    events[event][steamid] = c

        events[event] = sorted(events[event].values(), reverse=True,
                               key=lambda stats: (stats['total'], -stats['steamid64']))

    killstreaks = [{ 'title': log['summary']['title'], 'killstreaks': log['ks'] }
                   for log in logs.values() if log['ks']]
    chats = [{ 'title': log['summary']['title'], 'messages': log['chat'] }
             for log in logs.values()]

    return flask.render_template("log.html", logids=logs.keys(),
                                 logs=[log['summary'] for log in logs.values()], matches=matches,
                                 rounds=rounds, players=players, totals=totals,
                                 medics=medics, events=events, killstreaks=killstreaks,
                                 chats=chats)

metrics_extension = PrometheusMetrics.for_app_factory(group_by='endpoint', path=None)

@root.route('/metrics')
def metrics():
    metrics = metrics_extension.generate_metrics()
    resp = flask.make_response(metrics[0])
    resp.content_type = metrics[1]
    return resp
