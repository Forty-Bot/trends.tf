#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import argparse
from datetime import datetime
import logging
import sqlite3

from fetch import ListFetcher, BulkFetcher, FileFetcher, ReverseFetcher
from steamid import SteamID
from sql import db_connect, db_init

def filter_logids(c, logids):
    """Filter log ids to exclude those already present in the database.

    :param sqlite3.Connection c: The database connection
    :param logids: The log ids to filter
    :type logids: any iterable
    :return: The filtered log ids
    :rtype: sqlite3.Cursor
    :raises sqlite3.DatabaseError: if there was a problem accessing the database
    """

    for logid in logids:
        for _ in c.execute("SELECT 1 FROM log WHERE logid=?", (logid,)):
            break
        else:
            yield logid

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

    try:
        info['red_score'] = log['teams']['Red']['score']
        info['blue_score'] = log['teams']['Blue']['score']
    except KeyError:
        # On some very-old logs, some data lives under .info
        info['red_score'] = info['Red']['score']
        info['blue_score'] = info['Blue']['score']

    c.execute("INSERT OR IGNORE INTO map (map) VALUES (:map)", info)
    c.execute("""INSERT INTO log (
                     logid, time, duration, title, mapid, red_score, blue_score
                 ) VALUES (
                     :logid, :date, :total_length, :title,
                     (SELECT mapid FROM map WHERE map = :map), :red_score, :blue_score
                 );""",
              info)

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
        if round['time'] is not None and abs(round['time'] - info['date']) > 24 * 60 * 60:
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

        c.execute("""INSERT INTO round (
                         logid, seq, time, duration, winner, firstcap, red_score, blue_score,
                         red_kills, blue_kills, red_dmg, blue_dmg, red_ubers, blue_ubers
                     ) VALUES (
                         :logid, :seq, :start_time, :length,
                         (SELECT teamid FROM team WHERE team = :winner),
                         (SELECT teamid FROM team WHERE team = :firstcap), :red_score, :blue_score,
                         :red_kills, :blue_kills, :red_dmg, :blue_dmg, :red_ubers, :blue_ubers
                     );""", round)

    for steamid_str, player in log['players'].items():
        steamid = None
        try:
            steamid = SteamID(steamid_str)
        except ValueError:
            continue

        player['logid'] = logid
        player['steamid'] = steamid
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

        c.execute("INSERT OR IGNORE INTO name (name) VALUES (:name)", player)
        c.execute("""INSERT INTO player_stats (
                         logid, steamid64, teamid, nameid, kills, assists, deaths, suicides, dmg,
                         dmg_real, dt, dt_real, hr, lks, airshots, medkits, medkits_hp, backstabs,
                         headshots, headshots_hit, sentries, healing, cpc, ic
                     ) VALUES (
                         :logid, :steamid, (SELECT teamid FROM team WHERE team = :team),
                         (SELECT nameid FROM name WHERE name = :name), :kills, :assists, :deaths,
                         :suicides, :dmg, :dmg_real, :dt, :dt_real, :hr, :lks, :as, :medkits,
                         :medkits_hp, :backstabs, :headshots, :headshots_hit, :sentries, :heal,
                         :cpc, :ic
                     );""", player)

        for (prop, event) in (('classkills', 'kill'), ('classdeaths', 'death'),
                              ('classkillassists', 'assist')):
            if not log.get(prop):
                continue

            # If they never got a kill/assist/death then don't bother
            events = log[prop].get(steamid_str)
            if not events:
                continue

            events['logid'] = logid
            events['steamid'] = steamid
            events['event'] = event
            for cls in ('demoman', 'engineer', 'heavyweapons', 'medic', 'pyro', 'scout', 'sniper',
                        'soldier', 'spy'):
                events[cls] = events.get(cls, 0)

            # There are also 'unknown' events, but we skip them; they can be determined by the
            # difference between the sum of this event and the event in player_stats
            c.execute("""INSERT INTO event_stats (
                             logid, steamid64, eventid, demoman, engineer, heavyweapons, medic,
                             pyro, scout, sniper, soldier, spy
                         ) VALUES (
                             :logid, :steamid, (SELECT eventid FROM event WHERE event = :event),
                             :demoman, :engineer, :heavyweapons, :medic, :pyro, :scout, :sniper,
                             :soldier, :spy
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
                    medic['medigun_ubers'] = uber_types.get('medigun', 0)
                    medic['kritz_ubers'] = uber_types.get('kritzkrieg', 0)
                    # Sometimes other_ubers is missing and needs to be inferred
                    other_ubers = player['ubers'] - player['medigun_ubers'] - player['kritz_ubers']
                    medic['other_ubers'] = uber_types.get('unknown', other_ubers)
                except KeyError:
                    medic['medigun_ubers'] = None
                    medic['kritz_ubers'] = None
                    medic['other_ubers'] = None

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
                                 :logid, :steamid, :ubers, :medigun_ubers, :kritz_ubers,
                                 :other_ubers, :drops, :advantages_lost,
                                 :biggest_advantage_lost, :avg_time_before_healing,
                                 :avg_time_before_using, :avg_time_to_build, :avg_uber_length,
                                 :deaths_within_20s_after_uber, :deaths_with_95_99_uber
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
                             :logid, :steamid, (SELECT classid FROM class WHERE class = :type),
                             :kills, :assists, :deaths, :dmg, :total_time
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

                c.execute("INSERT OR IGNORE INTO weapon (weapon) VALUES (:name)", weapon)
                c.execute("""INSERT INTO weapon_stats (
                                 logid, steamid64, classid, weaponid, kills, dmg, avg_dmg, shots,
                                 hits
                             ) VALUES (
                                 :logid, :steamid, (SELECT classid FROM class WHERE class = :class),
                                 (SELECT weaponid FROM weapon WHERE weapon = :name), :kills, :dmg,
                                 :avg_dmg, :shots, :hits
                             );""", weapon)

    for (seq, msg) in enumerate(log['chat']):
        # poor man's goto...
        first = True
        while True:
            try:
                c.execute("INSERT INTO chat (logid, steamid64, seq, msg) VALUES (?, ?, ?, ?);",
                          (logid, SteamID(msg['steamid']) if msg['steamid'] != 'Console' else None,
                           seq, msg['msg']))
            # Spectator?
            except sqlite3.IntegrityError:
                if not first:
                    raise
                first = False


                c.execute("INSERT OR IGNORE INTO name (name) VALUES (:name)", msg)
                c.execute("""INSERT INTO player_stats (
                               logid, steamid64, nameid, kills, assists, deaths, dmg, lks, healing
                           ) VALUES (
                               ?, ?, (SELECT nameid FROM name WHERE name = ?), 0, 0, 0, 0, 0, 0
                           );""",
                          (logid, SteamID(msg['steamid']), msg['name']))
                continue
            except ValueError:
                break
            break

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
                c.execute("""INSERT OR IGNORE INTO heal_stats (logid, healer, healee, healing)
                             VALUES (?, ?, ?, ?);""",
                          (logid, healer, healee, healing))
            # Sometimes a player only shows up in rounds and healspread...
            except sqlite3.IntegrityError:
                logging.warning("Either %s or %s is only present in healspread for log %s",
                                healer, healee, logid)

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

    c.execute("""CREATE TEMP TABLE dupes AS SELECT
                     r1.logid AS logid,
                     max(r2.logid) AS of
                 FROM temp.new_log
                 JOIN log AS l1 ON (l1.logid=temp.new_log.logid)
                 JOIN round AS r1 ON (r1.logid=l1.logid)
                 JOIN log AS l2 ON (
                     l2.logid > l1.logid
                     AND l2.time BETWEEN l1.time - 24 * 60 * 60 AND l1.time + 24 * 60 * 60)
                 JOIN round AS r2 ON (
                     r2.logid=l2.logid
                     AND r2.seq=r1.seq
                     AND r2.time=r1.time
                     AND r2.duration=r1.duration
                     AND r2.winner=r1.winner
                     AND r2.firstcap=r1.firstcap
                     AND r2.red_score=r1.red_score
                     AND r2.blue_score=r1.blue_score
                     AND r2.red_kills=r1.red_kills
                     AND r2.blue_kills=r1.blue_kills
                     AND r2.red_dmg=r1.red_dmg
                     AND r2.blue_dmg=r1.blue_dmg
                     AND r2.red_ubers=r1.red_ubers
                     AND r2.blue_ubers=r1.blue_ubers
                 ) GROUP BY r1.logid;""")

    # Done in reverse order as import_log
    for table in ('chat', 'event_stats', 'weapon_stats', 'class_stats', 'heal_stats', 'medic_stats',
                  'player_stats', 'round'):
        c.execute("DELETE FROM {} WHERE logid IN (SELECT logid FROM temp.dupes);".format(table))

    c.execute("""UPDATE log
                 SET duplicate_of=temp.dupes.of
                 FROM temp.dupes
                 WHERE log.logid=temp.dupes.logid;""")
    (ret,) = c.execute("SELECT count(*) FROM temp.dupes;").fetchone()
    c.execute("DROP TABLE temp.dupes;")
    return ret

def delete_bogus_logs(c):
    """Delete bogus logs

    In some logs, players have negative damage. There are not very many, so just delete them.
    """

    c.execute("""CREATE TEMP TABLE bogus AS SELECT
                    DISTINCT logid
                 FROM temp.new_log
                 JOIN class_stats USING (logid)
                 WHERE dmg < 0 OR dt < 0;""")
    for table in ('chat', 'event_stats', 'weapon_stats', 'class_stats', 'heal_stats', 'medic_stats',
                  'player_stats', 'round'):
        c.execute("DELETE FROM {} WHERE logid IN (SELECT logid FROM temp.bogus);".format(table))
    c.execute("DROP TABLE temp.bogus");

def delete_dup_rounds(c):
    """Delete duplicate rounds

    Some logs have duplicate rounds. Delete them.

    :param sqlite.Connection c: The database connection:
    """

    c.execute("""DELETE FROM round
                 WHERE (logid, seq) IN (
                     SELECT r1.logid, r1.seq
                     FROM temp.new_log
                     JOIN round AS r1 USING (logid)
                     JOIN round AS r2 USING (
                         logid, time, duration, winner, firstcap, red_score, blue_score, red_dmg,
                         blue_dmg, red_kills, blue_kills, red_ubers, blue_ubers
                     ) WHERE r1.seq > r2.seq
                 );""")

def update_stalemates(c):
    """Find stalemates and mark the winner as NULL

    This should be run after removing duplicate rounds

    :param sqlite.Connection c: The database connection:
    """

    c.execute("""UPDATE round
                 SET winner = NULL
                 WHERE (logid, seq) IN (
                     SELECT logid, max(seq)
                     FROM temp.new_log
                     JOIN log USING (logid)
                     JOIN round USING (logid)
                     GROUP BY logid
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
                             total(class_stats.duration) / log.duration AS avg_players,
                             count(DISTINCT player_stats.steamid64) AS total_players
                         FROM temp.new_log
                         JOIN log USING (logid)
                         JOIN player_stats USING (logid)
                         JOIN class_stats USING (logid, steamid64)
                         -- Only set the format if it isn't already set
                         WHERE log.formatid ISNULL
                         GROUP BY logid
                     ) LEFT JOIN format AS fa ON (
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

def parse_args(*args, **kwargs):
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

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    f = sub.add_parser("file", help="Import from the local filesystem")
    f.set_defaults(fetcher=FileFetcher)
    f.add_argument("-l", "--log", action=LogAction, nargs=2, metavar=("LOGID", "LOG"),
                        dest='logs',
                        help="Import a log with a given id. May be specified multiple times")
    b = sub.add_parser("bulk", help="Bulk import from logs.tf")
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
    l = sub.add_parser("list", help="Import a list of logs from logs.tf")
    l.set_defaults(fetcher=ListFetcher)
    l.add_argument("-i", "--id", action='append', type=int, metavar="LOGID",
                   dest='logids', help="Fetch log LOGID")
    r = sub.add_parser("reverse", help="Import all logs in reverse order from logs.tf")
    r.set_defaults(fetcher=ReverseFetcher)

    for p in (f, b, l, r):
        p.add_argument("-v", "--verbose", action='count', default=0, dest='verbosity',
                            help=("Print additional debug information. May be specified multiple "
                                  "times for increased verbosity."))

    parser.add_argument("database", default="logs.db", help="SQLite database to store logs in")

    return parser.parse_args(*args, **kwargs)

def main():
    args = parse_args()
    fetcher = args.fetcher(**vars(args))

    log_level = logging.WARNING
    if args.verbosity == 1:
        log_level = logging.INFO
    elif args.verbosity > 1:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level)

    c = db_connect(args.database)
    db_init(c)
    # Only commit every 60s for performance
    c.execute("CREATE TEMP TABLE new_log (logid INTEGER PRIMARY KEY);")
    c.execute("BEGIN;");

    def commit():
        logging.info("Removed %s duplicate log(s)", delete_dup_logs(c))
        delete_bogus_logs(c)
        delete_dup_rounds(c)
        update_stalemates(c)
        update_formats(c)
        c.execute("DELETE FROM new_log;")
        c.execute("COMMIT;")
        c.execute("PRAGMA optimize;")

    count = 0
    start = datetime.now()
    for logid in filter_logids(c, fetcher.get_logids()):
        log = fetcher.get_log(logid)
        if log is None:
            continue

        try:
            import_log(c.cursor(), logid, log)
        except (IndexError, KeyError):
            logging.exception("Could not parse log %s", logid)
        except sqlite3.Error:
            logging.error("Could not import log %s", logid)
            raise

        c.execute("INSERT INTO new_log (logid) VALUES (?);", (logid,))

        count += 1
        now = datetime.now()
        if (now - start).total_seconds() > 60:
            commit()
            logging.info("Commited %s imported log(s)...", count)
            c.execute("BEGIN;")
            count = 0
            # Committing may take a while, so start the timer when we can actually import stuff
            start = datetime.now()

    logging.info("Committing %s imported log(s)...", count)
    commit()

if __name__ == "__main__":
    main()
