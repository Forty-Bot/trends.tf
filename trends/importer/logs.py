# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

import argparse
from datetime import datetime
import json
import logging

import psycopg2
import sentry_sdk
import systemd_watchdog

from .fetch import ListFetcher, BulkFetcher, FileFetcher, ReverseFetcher, CloneLogsFetcher
from ..steamid import SteamID
from ..sql import disable_tracing, delete_logs, log_tables, publicize, table_columns
from .. import util
from ..util import chunk

def filter_logids(c, logids, update_only=False):
    """Filter log ids to exclude those already present in the database.

    :param sqlite3.Connection c: The database connection
    :param logids: The log ids to filter
    :type logids: any iterable
    :return: The filtered log ids
    :rtype: sqlite3.Cursor
    :raises sqlite3.DatabaseError: if there was a problem accessing the database
    """

    def adapt(logids):
        for logid in logids:
            try:
                yield logid[0], logid[1]
            except TypeError:
                yield logid, None

    for logids in chunk(logids, 100):
        logids = adapt(logids)

        cur = c.cursor()
        psycopg2.extras.execute_values(cur,
            """SELECT
                new.logid,
                log.logid AS old,
                log.logid NOTNULL AS exists,
                coalesce(log.time < new.time::BIGINT, TRUE) AS newer
            FROM (VALUES %s) AS new(logid, time)
            LEFT JOIN public.log USING (logid);""", logids, "(%s, %s)")

        for row in cur:
            if not update_only if not row['exists'] else row['newer']:
                yield row['logid']

def import_log(c, logid, log):
    """Import a log into the database.

    :param sqlite3.Connection c: The database connection
    :param int logid: The id of the log
    :param log: A log parsed from json
    :raises TypeError: if a required property is missing
    :raised IndexError: if there are no rounds in the log
    :raises sqlite3.DatabaseError: if there was a problem accessing the database
    """

    # Unused for the moment
    log['version'] = log.get('version', 1)

    info = log['info']
    info['logid'] = logid
    info['AD_scoring'] = info.get('AD_scoring', None)
    info['uploader_name'] = info['uploader']['name']
    info['uploader_steamid'] = str(SteamID(info['uploader']['id']))

    try:
        info['red_score'] = log['teams']['Red']['score']
        info['blue_score'] = log['teams']['Blue']['score']
    except KeyError:
        # On some very-old logs, some data lives under .info
        info['red_score'] = info['Red']['score']
        info['blue_score'] = info['Blue']['score']

    c.execute("INSERT INTO map (map) VALUES (%(map)s) ON CONFLICT DO NOTHING;", info)
    c.execute("INSERT INTO name (name) VALUES (%(uploader_name)s) ON CONFLICT DO NOTHING;", info)
    c.execute("""INSERT INTO player (steamid64, nameid) VALUES (
                     %(uploader_steamid)s,
                     (SELECT nameid FROM name WHERE name = %(uploader_name)s)
                 ) ON CONFLICT (steamid64) DO NOTHING;""", info)
    c.execute("""INSERT INTO log (
                     logid, time, duration, title, mapid, red_score, blue_score, ad_scoring,
                     uploader, uploader_nameid
                 ) VALUES (
                     %(logid)s, %(date)s, %(total_length)s, %(title)s,
                     (SELECT mapid FROM map WHERE map = %(map)s),
                     %(red_score)s, %(blue_score)s, %(AD_scoring)s, %(uploader_steamid)s,
                     (SELECT nameid FROM name WHERE name = %(uploader_name)s)
                 );""",
              info)
    c.execute("INSERT INTO log_json (logid, data) VALUES (%s, %s)", (logid, log))

    # From here on in we want to keep our log and log_json rows
    c.execute("SAVEPOINT import;")

    # Ignore logs from banned players
    c.execute("SELECT banned FROM player WHERE steamid64 = %(uploader_steamid)s;", info);
    for row in c:
        if row[0]:
            return

    doubled_ubers = True

    for steamid_str, player in log['players'].items():
        # Some players don't have teams (they do actually have teams but they weren't parsed
        # properly). Just ignore them, since we have no way to tell what team they were actually on.
        if not player['team']:
            continue

        try:
            steamid = SteamID(steamid_str)
        except ValueError:
            continue

        player['logid'] = logid
        player['steamid'] = steamid
        player['time'] = info['date']
        player['name'] = log['names'][steamid_str] 

        # If we don't have a property, it may be absent or set to 0.
        # Instead, set missing keys to None so they become NULLs.
        if not info.get('hasRealDamage'):
            player['dmg_real'] = None
            player['dt_real'] = None
        if not info.get('hasHP'):
            player['medkits'] = None
        if not info.get('hasHP_real'):
            player['medkits_hp'] = None
        if not info.get('hasHS'):
            player['headshots'] = None
        if not info.get('hasHS_real'):
            player['headshots_hit'] = None
        if not info.get('hasBS'):
            player['backstabs'] = None
        if not info.get('hasCP'):
            player['cpc'] = None
        if not info.get('hasSB'):
            player['sentries'] = None
        if not info.get('hasDT'):
            player['dt'] = None
        if not info.get('hasAS'):
            player['as'] = None
        if not info.get('hasHR'):
            player['hr'] = None
        if not info.get('hasIntel'):
            player['ic'] = None
        player['suicides'] = player.get('suicides')
        player['heal'] = player.get('heal')

        c.execute("INSERT INTO name (name) VALUES (%(name)s) ON CONFLICT DO NOTHING;", player)
        c.execute("""INSERT INTO player (
                         steamid64,
                         nameid,
                         last_active
                     ) VALUES (
                         %(steamid)s,
                         (SELECT nameid FROM name WHERE name = %(name)s),
                         %(time)s
                     ) ON CONFLICT (steamid64)
                     DO UPDATE SET
                         last_active = greatest(player.last_active, EXCLUDED.last_active);""",
                  player)
        c.execute("""INSERT INTO player_stats_backing (
                         logid, steamid64, teamid, nameid, kills, assists, deaths, dmg, dt
                     ) VALUES (
                         %(logid)s, %(steamid)s, (SELECT teamid FROM team WHERE team = %(team)s),
                         (SELECT nameid FROM name WHERE name = %(name)s), %(kills)s, %(assists)s,
                         %(deaths)s, %(dmg)s, %(dt)s
                     );""", player)
        if any((player[key] for key in ('suicides', 'dmg_real', 'dt_real', 'hr', 'lks', 'as',
                                        'medkits', 'medkits_hp', 'backstabs', 'headshots',
                                        'headshots_hit', 'sentries', 'heal', 'cpc', 'ic'))):
            c.execute("""INSERT INTO player_stats_extra (
                             logid, steamid64, suicides, dmg_real, dt_real, hr, lks, airshots,
                             medkits, medkits_hp, backstabs, headshots, headshots_hit, sentries,
                             healing, cpc, ic
                         ) VALUES (
                             %(logid)s, %(steamid)s, %(suicides)s, %(dmg_real)s, %(dt_real)s,
                             %(hr)s, %(lks)s, %(as)s, %(medkits)s, %(medkits_hp)s, %(backstabs)s,
                             %(headshots)s, %(headshots_hit)s, %(sentries)s, %(heal)s, %(cpc)s,
                             %(ic)s
                         );""", player)

        for prop, event in util.events.items():
            if not log.get(prop):
                continue

            # If they never got a kill/assist/death then don't bother
            events = log[prop].get(steamid_str)
            if not events:
                continue

            events['logid'] = logid
            events['steamid'] = steamid
            events['event'] = event
            for cls in util.classes:
                events[cls] = events.get(cls, 0)

            # There are also 'unknown' events, but we skip them; they can be determined by the
            # difference between the sum of this event and the event in player_stats
            c.execute("""INSERT INTO event_stats (
                             logid, steamid64, eventid, demoman, engineer, heavyweapons, medic,
                             pyro, scout, sniper, soldier, spy
                         ) VALUES (
                             %(logid)s, %(steamid)s,
                             (SELECT eventid FROM event WHERE event = %(event)s), %(demoman)s,
                             %(engineer)s, %(heavyweapons)s, %(medic)s, %(pyro)s, %(scout)s,
                             %(sniper)s, %(soldier)s, %(spy)s
                         );""", events)

        for cls in player['class_stats']:
            # 99% of these contain no info which can't be inferred from player_stats
            if cls['type'] == 'undefined' or cls['type'] == 'unknown' or cls['type'] == '':
                continue

            if cls['type'] == 'medic':
                medic = player.get('medicstats', {})
                medic['logid'] = logid
                medic['steamid'] = steamid
                medic['ubers'] = player['ubers']
                medic['drops'] = player['drops']

                try:
                    uber_types = player['ubertypes'];
                except KeyError:
                    medic['medigun_ubers'] = None
                    medic['kritz_ubers'] = None
                    medic['quick_ubers'] = None
                    medic['vacc_ubers'] = None
                    medic['other_ubers'] = None
                else:
                    medic['medigun_ubers'] = uber_types.get('medigun', 0)
                    medic['kritz_ubers'] = uber_types.get('kritzkrieg', 0)
                    medic['quick_ubers'] = uber_types.get('quickfix', 0)
                    medic['vacc_ubers'] = uber_types.get('vaccinator', 0)

                    known_ubers = medic['medigun_ubers'] + medic['kritz_ubers'] \
                                + medic['quick_ubers'] + medic['vacc_ubers']
                    # Sometimes ubers are counted twice for whatever reason...
                    if known_ubers == uber_types.get('unknown', 0):
                        medic['ubers'] -= known_ubers
                        doubled_ubers = True

                    other_ubers = medic['ubers'] - medic['medigun_ubers'] - medic['kritz_ubers']
                    medic['other_ubers'] = other_ubers

                # All of these could be missing
                for prop in ('avg_time_before_healing', 'avg_time_before_using',
                             'avg_time_to_build', 'avg_uber_length', 'advantages_lost',
                             'biggest_advantage_lost', 'deaths_within_20s_after_uber',
                             'deaths_with_95_99_uber'):
                    medic[prop] = medic.get(prop)

                c.execute("""INSERT INTO medic_stats (
                                 logid, steamid64, ubers, medigun_ubers, kritz_ubers,
                                 other_ubers, drops, advantages_lost, biggest_advantage_lost,
                                 avg_time_before_healing, avg_time_before_using,
                                 avg_time_to_build, avg_uber_duration, deaths_after_uber,
                                 deaths_before_uber
                             ) VALUES (
                                 %(logid)s, %(steamid)s, %(ubers)s, %(medigun_ubers)s,
                                 %(kritz_ubers)s, %(other_ubers)s, %(drops)s, %(advantages_lost)s,
                                 %(biggest_advantage_lost)s, %(avg_time_before_healing)s,
                                 %(avg_time_before_using)s, %(avg_time_to_build)s,
                                 %(avg_uber_length)s, %(deaths_within_20s_after_uber)s,
                                 %(deaths_with_95_99_uber)s
                            );""", medic)

            cls['logid'] = logid
            cls['steamid'] = steamid

            # Some logs accidentally have a timestamp instead of a duration. Try and fix this up as
            # best we can... This may also fix some logs where players have slightly more time
            # played than the match duration.
            cls['total_time'] = min(cls['total_time'], info['total_length'])

            c.execute("""INSERT INTO class_stats (
                             logid, steamid64, classid, kills, assists, deaths, dmg, duration
                         ) VALUES (
                             %(logid)s, %(steamid)s,
                             (SELECT classid FROM class WHERE class = %(type)s), %(kills)s,
                             %(assists)s, %(deaths)s, %(dmg)s, %(total_time)s
                         );""", cls);

            # Some very old logs have no weapons stats at all
            if not cls.get('weapon'):
                continue
            for weapon_name, weapon in cls['weapon'].items():
                # No useful stats here... only ever have hits and nothing else
                if weapon_name == 'undefined':
                    continue

                # Some older logs just have the bare number of kills instead of a dict
                if type(weapon) is int:
                    weapon = { 'kills': weapon }

                weapon['logid'] = logid
                weapon['steamid'] = steamid
                weapon['class'] = cls['type']
                weapon['name'] = weapon_name

                if not info.get('hasWeaponDamage'):
                    weapon['dmg'] = None
                    weapon['avg_dmg'] = None
                if not info.get('hasAccuracy'):
                    weapon['shots'] = None
                    weapon['hits'] = None

                c.execute("INSERT INTO weapon (weapon) VALUES (%(name)s) ON CONFLICT DO NOTHING;",
                          weapon)
                c.execute("""INSERT INTO weapon_stats (
                                 logid, steamid64, classid, weaponid, kills, dmg, avg_dmg, shots,
                                 hits
                             ) VALUES (
                                 %(logid)s, %(steamid)s,
                                 (SELECT classid FROM class WHERE class = %(class)s),
                                 (SELECT weaponid FROM weapon WHERE weapon = %(name)s), %(kills)s,
                                 %(dmg)s, %(avg_dmg)s, %(shots)s, %(hits)s
                             );""", weapon)

    for (seq, msg) in enumerate(log['chat']):
        try:
            steamid = SteamID(msg['steamid']) if msg['steamid'] != 'Console' else None
        except ValueError:
            continue

        c.execute("INSERT INTO name (name) VALUES (%(name)s) ON CONFLICT DO NOTHING;", msg)
        if steamid:
            c.execute("""INSERT INTO player (steamid64, nameid) VALUES (
                             %s, (SELECT nameid FROM name WHERE name = %s)
                         ) ON CONFLICT (steamid64) DO NOTHING;""",
                      (steamid, msg['name']))
        c.execute("INSERT INTO chat (logid, steamid64, seq, msg) VALUES (%s, %s, %s, %s);",
                  (logid, steamid, seq, msg['msg']))

    for (healer, healees) in log['healspread'].items():
        try:
            healer = SteamID(healer)
        except ValueError:
            continue

        for (healee, healing) in healees.items():
            try:
                healee = SteamID(healee)
            except ValueError:
                continue

            try:
                # Sometimes we get the same row more than once (e.g. with different text
                # representations of the same steamid). It appears that later rows are a result of
                # healing being logged more than once, and aren't distinct instances of healing.
                c.execute("SAVEPOINT before_heal_stats;")
                c.execute("""INSERT INTO heal_stats (logid, healer, healee, healing)
                             VALUES (%s, %s, %s, %s)
                             ON CONFLICT DO NOTHING;""",
                          (logid, healer, healee, healing))
            # Sometimes a player only shows up in rounds and healspread...
            except psycopg2.errors.ForeignKeyViolation:
                logging.warning("Either %s or %s is only present in healspread for log %s",
                                healer, healee, logid)
                c.execute("ROLLBACK TO SAVEPOINT before_heal_stats;")

    rounds = None
    try:
        rounds = log['rounds']
    except KeyError:
        # Old-style rounds
        rounds = log['info']['rounds']

    for (seq, round) in enumerate(rounds):
        teams = round.get('team', round)
        red = teams['Red']
        blue = teams['Blue']

        round['logid'] = logid
        round['seq'] = seq
        round['time'] = round.get('start_time')
        # Some rounds have completely bogus times
        if round['time'] is None or abs(round['time'] - info['date']) > 24 * 60 * 60:
            round['time'] = info['date']

        round['firstcap'] = round.get('firstcap')

        round['red_score'] = red.get('score', info['red_score'])
        round['blue_score'] = blue.get('score', info['blue_score'])
        round['red_kills'] = red['kills']
        round['blue_kills'] = blue['kills']
        try:
            round['red_dmg'] = red['dmg']
            round['blue_dmg'] = blue['dmg']
        except KeyError:
            round['red_dmg'] = red['damage']
            round['blue_dmg'] = blue['damage']
        round['red_ubers'] = red['ubers']
        round['blue_ubers'] = blue['ubers']
        if doubled_ubers:
            round['red_ubers'] /= 2
            round['blue_ubers'] /= 2

        c.execute("""INSERT INTO round (
                         logid, seq, duration, time, winner, firstcap, red_score, blue_score,
                         red_kills, blue_kills, red_dmg, blue_dmg, red_ubers, blue_ubers
                     ) VALUES (
                         %(logid)s, %(seq)s, %(length)s, %(time)s,
                         (SELECT teamid FROM team WHERE team = %(winner)s),
                         (SELECT teamid FROM team WHERE team = %(firstcap)s),
                         %(red_score)s, %(blue_score)s, %(red_kills)s, %(blue_kills)s, %(red_dmg)s,
                         %(blue_dmg)s, %(red_ubers)s, %(blue_ubers)s
                     );""", round)

def delete_dup_logs(c):
    """Delete duplicate logs

    Process (perhaps to be amended in the future):
    1. Find logs with duplicate rounds
    2. Delete all data from the earlier logs (by logid) except the log itself
    3. Set log.duplicate_of of the earlier logs

    :param sqlite.Connection c: The database connection
    :return: The number of logs deduplicated
    :rtype: int
    :raises sqlite3.DatabaseError: if there was a problem accessing the database
    """

    cur = c.cursor()
    cur.execute("""SELECT
                       min(logid)
                   FROM combined_logs
                   WHERE time > (SELECT min(time) FROM log) - 24 * 60 * 60
                   UNION ALL
                   SELECT
                       max(logid)
                   FROM combined_logs
                   WHERE time > (SELECT max(time) FROM log) + 24 * 60 * 60;""")
    min, max = (row[0] for row in cur)

    cur = c.cursor()
    cur.execute("""CREATE TEMP TABLE dupes AS SELECT
                     r1.logid AS logid,
                     max(r2.logid) AS of
                 FROM round AS r1
                 JOIN combined_rounds AS r2 USING (time, duration) WHERE r2.logid > r1.logid
                     AND (r2.logid > %(min)s OR %(min)s ISNULL)
                     AND (r2.logid < %(max)s OR %(max)s ISNULL)
                 GROUP BY r1.logid;""", { 'min': min, 'max': max})

    cur.execute("""UPDATE log
                 SET duplicate_of=dupes.of
                 FROM dupes
                 WHERE log.logid=dupes.logid;""")
    cur.execute("DROP TABLE dupes;")

def delete_bogus_logs(c):
    """Delete bogus logs

    In some logs, players have negative damage. There are not very many, so just delete them.
    """

    c.execute("""INSERT INTO to_delete SELECT
                    DISTINCT logid
                 FROM weapon_stats
                 WHERE dmg < 0
                 ON CONFLICT DO NOTHING;""")

def delete_dup_rounds(c):
    """Delete duplicate rounds

    Some logs have duplicate rounds. Delete them.

    :param sqlite.Connection c: The database connection:
    """

    c.execute("""CREATE TABLE dupes AS SELECT
                     r1.logid,
                     r1.seq
                 FROM round AS r1
                 JOIN round AS r2 USING (
                     logid, time, duration, winner, firstcap, red_score, blue_score, red_dmg,
                     blue_dmg, red_kills, blue_kills, red_ubers, blue_ubers
                 ) WHERE r1.seq > r2.seq;""")

    c.execute("DELETE FROM round WHERE (logid, seq) IN (SELECT * FROM dupes);")
    c.execute("DROP TABLE dupes;")

def update_stalemates(c):
    """Find stalemates and mark the winner as NULL

    This should be run after removing duplicate rounds

    :param sqlite.Connection c: The database connection:
    """

    c.execute("""UPDATE round
                 SET winner = NULL
                 WHERE (logid, seq) IN (SELECT
                         logid,
                         max(seq)
                     FROM log
                     JOIN round USING (logid)
                     GROUP BY logid, log.red_score, log.blue_score
                     HAVING count(winner) > (log.red_score + log.blue_score)
                 );""")

def update_formats(c):
    """Set the format for all logs

    See the SQL comments for details on this heuristic.

    :param sqlite.Connection c: The database connection:
    """

    c.execute("""UPDATE log
                 SET formatid = new.formatid
                 FROM (
                     SELECT
                         logid,
                         coalesce(
                             -- If the difference between total and average is too high, then the
                             -- total player count is more accurate. This is because some logs have
                             -- broken playtime (e.g. average players of 8.5 with 12 total players).
                             CASE WHEN total_players - avg_players > 2 THEN ft.formatid END,
                             -- Otherwise, prefer average playtime, since it detects sixes vs
                             -- prolander better
                             fa.formatid,
                             ft.formatid,
                             fo.formatid
                         ) AS formatid
                     FROM (
                         SELECT
                             logid,
                             total_duration / log.duration AS avg_players,
                             total_players
                         FROM log
                         JOIN (SELECT
                                 logid,
                                 count(DISTINCT steamid64) AS total_players,
                                 total(duration) as total_duration
                             FROM class_stats
                             GROUP BY logid
                         ) AS counts USING (logid)
                         -- Only set the format if it isn't already set
                         WHERE log.formatid ISNULL
                     ) AS intermediate
                     LEFT JOIN format AS fa ON (
                         -- By inspection, almost all games in a format have players in this range
                         -- This has some slight overlap between sixes and prolander (oh well)
                         avg_players BETWEEN fa.players - 1 AND fa.players + 1
                     ) LEFT JOIN format AS ft ON (
                         total_players BETWEEN ft.players - 1 AND ft.players + 1
                     ) JOIN format AS fo ON (
                         fo.format = 'other'
                     )
                 ) AS new
                 WHERE log.logid = new.logid;""")

def update_wlt(c):
    c.execute("""UPDATE player_stats_backing AS ps
                 SET wins = CASE new.teamid
                         WHEN 1 THEN new.red_score
                         WHEN 2 THEN new.blue_score
                         ELSE 0
                     END,
                     losses = CASE new.teamid
                         WHEN 1 THEN new.blue_score
                         WHEN 2 THEN new.red_score
                         ELSE 0
                     END,
                     ties = CASE WHEN new.teamid NOTNULL
                         THEN new.ties
                         ELSE 0
                     END
                 FROM (SELECT
                         logid,
                         steamid64,
                         teamid,
                         CASE WHEN ad_scoring
                             THEN log.red_score
                             ELSE coalesce(round.red_score, log.red_score)
                         END AS red_score,
                         CASE WHEN ad_scoring
                             THEN log.blue_score
                             ELSE coalesce(round.blue_score, log.blue_score)
                         END AS blue_score,
                         CASE WHEN ad_scoring
                             THEN 0
                             ELSE coalesce(round.ties, 0)
                         END AS ties
                     FROM player_stats_backing
                     JOIN log USING (logid)
                     LEFT JOIN (SELECT
                             logid,
                             sum((round.winner = 1)::INT) AS red_score,
                             sum((round.winner = 2)::INT) AS blue_score,
                             sum((round.winner ISNULL AND round.duration >= 60)::INT) AS ties
                         FROM round
                         GROUP BY logid
                     ) AS round USING (logid)
                 ) AS new
                 WHERE ps.logid = new.logid
                     AND ps.steamid64 = new.steamid64""")

def update_player_classes(cur, bounds=None):
    cur.execute("""UPDATE player_stats_backing AS ps SET
                       classids = new.classids,
                       class_durations = new.durations
                   FROM (SELECT
                           logid,
                           steamid64,
                           array_agg(classid ORDER BY duration DESC) AS classids,
                           array_agg(duration ORDER BY duration DESC) AS durations
                       FROM class_stats
                       {}
                       GROUP BY logid, steamid64
                       ORDER BY steamid64, logid
                   ) AS new
                   WHERE ps.logid = new.logid
                       AND ps.steamid64 = new.steamid64;"""
                   .format("WHERE logid BETWEEN %s AND %s" if bounds else ""),
                bounds)

def update_acc(cur, bounds=None):
    cur.execute("""UPDATE class_stats AS cs SET
                        hits = new.hits,
                        shots = new.shots
                    FROM (SELECT
                            logid,
                            steamid64,
                            classid,
                            sum(hits) AS hits,
                            sum(shots) AS shots
                        FROM weapon_stats
                        {}
                        GROUP BY logid, steamid64, classid
                        ORDER BY steamid64, logid, classid
                    ) AS new
                    WHERE cs.logid = new.logid
                        AND cs.steamid64 = new.steamid64
                        AND cs.classid = new.classid"""
                 .format("WHERE logid BETWEEN %s AND %s" if bounds else ""),
              bounds)

    cur.execute("""UPDATE player_stats_backing AS ps SET
                        hits = new.hits,
                        shots = new.shots
                    FROM (SELECT
                            logid,
                            steamid64,
                            sum(hits) AS hits,
                            sum(shots) AS shots
                        FROM weapon_stats
                        {}
                        GROUP BY logid, steamid64
                        ORDER BY steamid64, logid
                    ) AS new
                    WHERE ps.logid = new.logid
                        AND ps.steamid64 = new.steamid64"""
                 .format("WHERE logid BETWEEN %s AND %s" if bounds else ""),
              bounds)

def create_logs_parser(sub):
    class LogAction(argparse.Action):
        def __init__(self, option_strings, dest, **kwargs):
            if kwargs['nargs'] != 2:
                raise ValueError("nargs must be 2")
            super().__init__(option_strings, dest, **kwargs)

        def __call__(self, parse, namespace, values, option_string=None):
            items = getattr(namespace, self.dest)
            if items is None:
                items = {}

            try:
                items[int(values[0])] = values[1]
            except ValueError as e:
                raise argparse.ArgumentError(self, "LOGID must be an integer") from e

            setattr(namespace, self.dest, items)

    logs = sub.add_parser("logs", help="Import logs")
    logs.set_defaults(importer=import_logs_cli)
    log_sub = logs.add_subparsers()
    f = log_sub.add_parser("file", help="Import from the local filesystem")
    f.set_defaults(fetcher=FileFetcher)
    f.add_argument("-l", "--log", action=LogAction, nargs=2, metavar=("LOGID", "LOG"),
                   dest='logs',
                   help="Import a log with a given id. May be specified multiple times")
    b = log_sub.add_parser("bulk", help="Bulk import from logs.tf")
    b.set_defaults(fetcher=BulkFetcher)
    b.add_argument("-p", "--player", action='append', type=SteamID, metavar="STEAMID",
                   dest='players',
                   help="Only fetch this player's logs. May be specified multiple times")
    b.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=datetime.fromtimestamp(0), metavar="DATE",
                   help="Only fetch logs created since DATE")
    b.add_argument("-c", "--count", type=int, default=None,
                   help="Fetch up to COUNT logs, defaults to unlimited")
    b.add_argument("-o", "--offset", type=int, default=0,
                   help="Start at OFFSET")
    l = log_sub.add_parser("list", help="Import a list of logs from logs.tf")
    l.set_defaults(fetcher=ListFetcher)
    l.add_argument("-i", "--id", action='append', type=int, metavar="LOGID",
                   dest='logids', help="Fetch log LOGID")
    r = log_sub.add_parser("reverse", help="Import all logs in reverse order from logs.tf")
    r.set_defaults(fetcher=ReverseFetcher)
    c = log_sub.add_parser("clone_logs", help="Import a sqlite database generated with clone_logs")
    c.set_defaults(fetcher=CloneLogsFetcher)
    c.add_argument("-d", "--database", type=str, metavar="DB", dest='db',
                   help="Database to import logs from")
    logs.add_argument("-u", "--update-only", action='store_true',
                      help="Only update logs already in the database")

def import_logs_cli(args, c):
    with sentry_sdk.start_transaction(op="import", name="logs"):
        return import_logs(c, args.fetcher(**vars(args)), args.update_only)

def import_logs(c, fetcher, update_only):
    cur = c.cursor()
    wd = systemd_watchdog.watchdog()

    # Create some temporary tables so deletes don't cost so much later
    cur.execute("CREATE TEMP TABLE to_delete (logid INTEGER PRIMARY KEY);")
    for table in log_tables:
        cur.execute("""CREATE TEMP TABLE {} (
                           LIKE {} INCLUDING ALL EXCLUDING INDEXES,
                           PRIMARY KEY ({})
                       );""".format(table[0], table[0], table[1]))
    # This doesn't include foreign keys, so include some which we want to handle in import_log
    cur.execute("""ALTER TABLE heal_stats
                   ADD FOREIGN KEY (logid, healer)
                       REFERENCES player_stats_backing (logid, steamid64),
	               ADD FOREIGN KEY (logid, healee)
                       REFERENCES player_stats_backing (logid, steamid64);""")
    # We need this index to calculate formats efficiently
    cur.execute("CREATE INDEX class_stats_logid ON class_stats (logid);")
    # And this index to limit dupes
    cur.execute("CREATE INDEX log_time ON log (time);")
    # Finally, add some convenience views
    cur.execute("""CREATE TEMP VIEW combined_logs AS
                   SELECT * FROM log
                   UNION ALL
                   SELECT * FROM public.log;""");
    cur.execute("""CREATE TEMP VIEW combined_rounds AS
                   SELECT * FROM round
                   UNION ALL
                   SELECT * FROM public.round;""")

    def commit():
        with sentry_sdk.start_span(op='db.transaction', description="commit"):
            cur.execute("BEGIN;")
            cur.execute("SET CONSTRAINTS ALL DEFERRED;");
            delete_dup_logs(c)
            delete_bogus_logs(cur)
            delete_logs(cur)

            delete_dup_rounds(cur)
            update_stalemates(cur)
            update_formats(cur)
            update_wlt(cur)
            update_player_classes(cur)
            update_acc(cur)
            publicize(c, log_tables)
            wd.ping()
            cur.execute("COMMIT;")
            logging.info("Committed %s imported log(s)...", count)

    count = 0
    start = datetime.now()
    wd.ready()
    for logid in filter_logids(c, fetcher.get_logids(), update_only=update_only):
        wd.ping()
        log = fetcher.get_log(logid)
        if log is None:
            continue

        wd.ping()
        with sentry_sdk.start_span(op='db.transaction', description=f"import {logid}"), \
             disable_tracing():
            cur.execute("BEGIN;")
            cur.execute("SAVEPOINT import;")
            try:
                import_log(c.cursor(), logid, log)
            except (IndexError, KeyError, psycopg2.errors.NumericValueOutOfRange):
                logging.exception("Could not parse log %s", logid)
                cur.execute("ROLLBACK TO SAVEPOINT import;")
                cur.execute("INSERT INTO to_delete VALUES (%s);", (logid,))
            except psycopg2.Error:
                logging.error("Could not import log %s", logid)
                raise
            else:
                count += 1
            cur.execute("COMMIT;")

        now = datetime.now()
        if (now - start).total_seconds() > 60 or count > 500:
            commit()
            cur.execute("BEGIN;")
            count = 0
            # Committing may take a while, so start the timer when we can actually import stuff
            start = datetime.now()
        wd.ping()

    commit()
