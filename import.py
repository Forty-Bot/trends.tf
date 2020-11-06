#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import argparse
from datetime import datetime
import logging
import sqlite3

from fetch import ListFetcher, BulkFetcher, FileFetcher
from steamid import SteamID

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

    rounds = None
    try:
        rounds = log['rounds']
    except KeyError:
        # Old-style rounds
        rounds = log['info']['rounds']

    # All rounds have a "winner", but it might just be whoever had the lead in points when time ran
    # out. Instead, try and detect if there was a stalemate by seeing if the points changed from the
    # penultimate round to the ultimate round.
    info['final_duration'] = rounds[-1]['length']
    try:
        # Older logs have Red and Blue directly under the round
        ult_teams = rounds[-1].get('team', rounds[-1])
        penult_teams = rounds[-2].get('team', rounds[-2])
        # Some logs have no scores for the ult rounds, so assume no stalemate
        info['final_stalemate'] = \
            ult_teams['Red'].get('score') == penult_teams['Red']['score'] and \
            ult_teams['Blue'].get('score') == penult_teams['Blue']['score']
    except IndexError:
        # In games with only one round, there was a stalemate if there was no round winner
        info['final_stalemate'] = rounds[-1]['winner'] is None

    c.execute("""INSERT INTO log (
                     logid, time, duration, title, map, red_score, blue_score,
                     final_round_stalemate, final_round_duration
                 ) VALUES (
                     :logid, :date, :total_length, :title, :map, :red_score, :blue_score,
                     :final_stalemate, :final_duration
                 );""",
              info)

    for steamid_str, player in log['players'].items():
        steamid = SteamID(steamid_str)
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
        player['suicides'] = info.get('suicides')

        c.execute("""INSERT INTO player_stats (
                         logid, steamid64, team, name, kills, assists, deaths, suicides, dmg,
                         dmg_real, dt, dt_real, hr, lks, airshots, medkits, medkits_hp, backstabs,
                         headshots, headshots_hit, sentries, healing, cpc, ic
                     ) VALUES (
                         :logid, :steamid, :team, :name, :kills, :assists, :deaths, :suicides, :dmg,
                         :dmg_real, :dt, :dt_real, :hr, :lks, :as, :medkits, :medkits_hp,
                         :backstabs, :headshots, :headshots_hit, :sentries, :heal, :cpc, :ic
                     );""", player)


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
                             logid, steamid64, class, kills, assists, deaths, dmg, duration
                         ) VALUES (
                             :logid, :steamid, :type, :kills, :assists, :deaths, :dmg, :total_time
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

                c.execute("""INSERT INTO weapon_stats (
                                 logid, steamid64, class, weapon, kills, dmg, avg_dmg, shots, hits
                             ) VALUES (
                                 :logid, :steamid, :class, :name, :kills, :dmg, :avg_dmg, :shots,
                                 :hits
                             );""", weapon)

    for (healer, healees) in log['healspread'].items():
        healer = SteamID(healer)
        for (healee, healing) in healees.items():
            healee = SteamID(healee)
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
    b.add_argument("-c", "--count", type=int, default=1000,
                        help="Fetch up to COUNT logs, defaults to 1000")
    l = sub.add_parser("list", help="Import a list of logs from logs.tf")
    l.set_defaults(fetcher=ListFetcher)
    l.add_argument("-i", "--id", action='append', type=int, metavar="LOGID",
                   dest='logids', help="Fetch log LOGID")

    for p in (f, b, l):
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

    sqlite3.register_adapter(SteamID, str)
    c = sqlite3.connect(args.database, isolation_level=None)
    c.execute("PRAGMA foreign_keys = TRUE");
    with open("schema.sql") as schema:
        c.executescript(schema.read())

    # Only commit every 10s for performance
    c.execute("BEGIN;");

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

        count += 1
        now = datetime.now()
        if (now - start).total_seconds() > 10:
            logging.info("Committing %s imported log(s)...", count)
            c.execute("COMMIT;")
            c.execute("BEGIN;")
            count = 0
            start = now

    logging.info("Committing %s imported log(s)...", count)
    c.execute("COMMIT;");
    c.execute("PRAGMA optimize;")

if __name__ == "__main__":
    main()
