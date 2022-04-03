# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

import collections
import itertools
import json
import logging
import sqlite3
import time

import requests, requests.adapters
import urllib3.util

from ..util import classes, events

class APIError(OSError):
    """The logs.tf API returned a failure"""
    def __init__(self, msg):
        super().__init__("logs.tf API request failed: %s".format(msg))

def fetch_players_logids(s, players=None, since=0, count=None, offset=0, limit=1000):
    """Fetch some logids from logs.tf.

    Any network or parsing are caught and logged.

    :param requests.Session s: Session to use
    :param players: Steam ids that fetched log ids must include
    :type players: iterable of SteamIDs
    :param int since: Unix time of the earliest logs ids to fetch
    :param int count: Number of log ids to fetch consider; may be reduced by since
    :param int offset: Number of logs to skip
    :param int limit: Largest page to fetch at once
    :return: The fetched log ids
    :rtype: iterable of ints
    """

    # Number of logids yielded (up to a maximum of count)
    yielded = 0
    # Total number of logids available to fetch
    total = None
    # The lowest logid we've seen. We assume new logs will all have higher logids.
    last_logid = None

    try:
        while total is None or offset < total:
            params = { 'offset': offset, 'limit': limit }
            if players:
                params['player'] = ",".join(str(player) for player in players)

            resp = s.get("https://logs.tf/api/v1/log", params=params)
            resp.raise_for_status()
            log_list = resp.json()
            if not log_list['success']:
                raise APIError(log_list['error'])

            total = log_list['total']
            for log in log_list['logs']:
                offset += 1
                if last_logid and log['id'] >= last_logid:
                    continue
                elif log['date'] >= since:
                    last_logid = log['id']
                    yield log['id'], log['date']

                    yielded += 1
                    if count is not None and yielded >= count:
                        return
                else:
                    # We are now into older logs. There could be some more logs with older logids
                    # but newer dates, but these are not too common. Continue parsing the current
                    # page, but don't fetch any more pages.
                    offset = total
    except OSError:
        logging.exception("Could not fetch log list")
    except (ValueError, KeyError):
        logging.exception("Could not parse log list")

class Fetcher:
    """Generic abstraction of different ways to fetch logs"""
    def __init__(self, **kwargs):
        pass

    def fetch_logids(self):
        """Fetch log ids, to be passed to ``fetch_log``

        :return: log ids to fetch
        :rtype: iterable of int
        """
        return iter(())

    def fetch_log(self, logid):
        """Fetch and parse one log

        :param int logid: The log's id
        :return: The parsed log or None
        """
        None

class ListFetcher(Fetcher):
    """Fetcher for a list of log ids for logs to get from logs.tf"""
    def __init__(self, logids=None, **kwargs):
        """Create a ``ListFetcher``

        :param logids: List of log ids
        :type logids: iteratable of ints
        """

        self.s = requests.Session()
        retries = urllib3.util.Retry(total=4, backoff_factor=0.1,
                                     status_forcelist=(requests.codes.too_many,))
        self.s.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))
        self.logids = logids if logids is not None else iter(())
        super().__init__(**kwargs)

    def get_logids(self):
        return self.logids

    def get_log(self, logid):
        try:
            url = "https://logs.tf/api/v1/log/{}".format(logid)
            resp = self.s.get(url)
            resp.raise_for_status()
            log = resp.json()
            if not log['success']:
                raise APIError(log['error'])
            return log
        except OSError:
            logging.exception("Could not fetch log %s", logid)
        except (ValueError, KeyError):
            logging.exception("Could not parse log %s", logid)

class ReverseFetcher(ListFetcher):
    """Fetch logs in reverse order from some maximum"""
    def __init__(self, **kwargs):
        """Create a ``ReverseFetcher``

        :param max: Max log
        :type logs: (int, str)
        """

        super().__init__(**kwargs)

    def get_logids(self):
        try:
            resp = self.s.get("https://logs.tf/api/v1/log")
            resp.raise_for_status()
            log_list = resp.json()
            if not log_list['success']:
                raise APIError(log_list['error'])

            return range(log_list['logs'][0]['id'] + 1, 0, -1)
        except OSError:
            logging.exception("Could not fetch log list")
        except (ValueError, KeyError):
            logging.exception("Could not parse log list")
        return iter(())

class BulkFetcher(ListFetcher):
    """Fetcher for parameters of logs to get from logs.tf"""
    def __init__(self, players=None, since=None, count=None, offset=None, **kwargs):
        """Create a ``ListFetcher``

        :param players: Steam ids that fetched log ids must include
        :type players: iterable of SteamIDs
        :param int since: Unix time of the earliest logs ids to fetch
        :param int count: Number of log ids to fetch
        """

        self.players = players
        self.since = since.timestamp()
        self.count = count
        self.offset = offset
        super().__init__(**kwargs)

    def get_logids(self):
        return fetch_players_logids(self.s, players=self.players, since=self.since,
                                    count=self.count, offset=self.offset)

class FileFetcher(Fetcher):
    """Fetcher for logs from local files"""
    def __init__(self, logs=None, **kwargs):
        """Create a ``FileFetcher``

        :param logs: Log ids and their filenames
        :type logs: (int, str)
        """

        self.logs = logs
        super().__init__(**kwargs)

    def get_logids(self):
        return self.logs.keys()

    def get_log(self, logid):
        with open(self.logs[logid]) as logfile:
            return json.load(logfile)

class CloneLogsFetcher(Fetcher):
    """Fetcher for SQLite databases created with clone_logs"""
    def __init__(self, db=None, **kwargs):
        """Create a ``CloneLogsFetcher``

        :param db: Name of the database
        :type db: str
        """

        self.c = sqlite3.connect(db)
        self.c.row_factory = sqlite3.Row

        # Add some indices for better performance
        for table in ('chat', 'heal_spread', 'player', 'player_weapon', 'round'):
            self.c.execute("CREATE INDEX IF NOT EXISTS {0}_pkey ON {0} (log_id)".format(table))

        super().__init__(**kwargs)

    def date_colspec(self, column='date'):
        return "cast(strftime('%s', {}, 'utc') AS INT)".format(column)

    def get_logids(self):
        return self.c.execute("SELECT id, {} FROM log".format(self.date_colspec()))

    def get_log(self, logid):
        class_keys = [('heavy', 'heavyweapons') if cls == 'heavy' else cls for cls in classes]
        def extract(row, keys, format_string='{}'):
            ret = {}
            global cur_row
            cur_row = row
            for key in keys:
                try:
                    ret[key[1]] = row[format_string.format(key[0])]
                except IndexError:
                    try:
                        ret[key] = row[format_string.format(key)]
                    except IndexError:
                        logging.error("No such key %s", key)
                        raise

            return ret

        ret = {
            'version': 3,
        }
        log = self.c.execute("""SELECT
                                    {} AS date,
                                    *
                                FROM log
                                WHERE id = ?;""".format(self.date_colspec()), (logid,)).fetchone()
        ret['info'] = extract(log, (
            'date',
            'title',
            'map',
            ('duration',               'total_length'),
            ('has_real_damage',        'hasRealDamage'),
            ('has_weapon_damage',      'hasWeaponDamage'),
            ('has_accuracy',           'hasAccuracy'),
            ('has_medkit_pickups',     'hasHP'),
            ('has_medkit_pickups',     'hasHP'),
            ('has_medkit_health',      'hasHP_real'),
            ('has_headshot_kills',     'hasHS'),
            ('has_headshot_hits',      'hasHS_hit'),
            ('has_backstabs',          'hasBS'),
            ('has_point_captures',     'hasCP'),
            ('has_sentries_built',     'hasSB'),
            ('has_damage_taken',       'hasDT'),
            ('has_airshots',           'hasAS'),
            ('has_heals_received',     'hasHR'),
            ('has_intel_captures',     'hasIntel'),
            ('scoring_attack_defense', 'AD_scoring'),
        ))
        ret['info']['uploader'] = extract(log, (('steam_id', 'id'), 'name', 'info'), 'uploader_{}')
        team_keys = ('score', 'kills', 'deaths', ('damage', 'dmg'), 'charges', 'drops',
                     ('first_caps', 'firstcaps'), 'caps')
        ret['teams'] = {
            'Red': extract(log, team_keys, 'red_{}'),
            'Blue': extract(log, team_keys, 'blu_{}'),
        }

        ret['rounds'] = []
        rounds = self.c.execute("""SELECT
                                       {} AS start_time,
                                       *
                                   FROM round
                                   WHERE log_id = ?
                                   ORDER BY idx ASC;""".format(self.date_colspec('start')),
                                (logid,))
        for round in rounds:
            tmp = extract(round, ('start_time',
                                  'winner',
                                  ('first_cap', 'firstcap'),
                                  ('duration', 'length')))
            round_team_keys = ('score', 'kills', ('damage', 'dmg'), ('charges', 'ubers'))
            tmp['team'] = {}
            tmp['team']['Red'] = extract(round, round_team_keys, 'red_{}')
            tmp['team']['Blue'] = extract(round, round_team_keys, 'blu_{}')
            ret['rounds'].append(tmp)

        ret['players'] = {}
        ret['names'] = {}
        for prop in events:
            ret[prop] = collections.defaultdict(dict)
        players = self.c.execute("SELECT * FROM player WHERE log_id = ?;", (logid,))
        for player in players:
            steamid = player['steam_id']
            ret['names'][steamid] = player['name']
            ret['players'][steamid] = extract(player, (
                'team',
                'kills',
                'deaths',
                'assists',
                'suicides',
                ('damage',             'dmg'),
                ('damage_real',        'dmg_real'),
                ('damage_taken',       'dt'),
                ('damage_taken_real',  'dt_real'),
                ('heals_received',     'hr'),
                ('longest_killstreak', 'lks'),
                ('airshots',           'as'),
                ('charges',            'ubers'),
                'drops',
                ('medkit_pickup',      'medkits'),
                ('medkit_health',      'medkits_hp'),
                'backstabs',
                ('headshot_kills',     'headshots'),
                ('headshots',          'headshots_hit'),
                'sentries',
                ('point_captures',     'cpc'),
                ('intel_captures',     'ic'),
            ))

            ubertypes = {}
            if player['charges_uber']:
                ubertypes['medigun'] = player['charges_uber']
            if player['charges_kritzkrieg']:
                ubertypes['kritzkrieg'] = player['charges_kritzkrieg']
            if any(ubertypes.values()):
                ret['players'][steamid]['ubertypes'] = ubertypes

            medic_stats = extract(player, (
                'advantages_lost',
                'biggest_advantage_lost',
                'deaths_within_20s_after_uber',
                ('deaths_with_95_uber', 'deaths_with_95_99_uber'),
                ('average_time_before_healing', 'avg_time_before_healing'),
                ('average_time_before_using', 'avg_time_before_using'),
                ('average_charge_length', 'avg_uber_length'),
            ))
            if any(medic_stats.values()):
                ret['players'][steamid]['medicstats'] = medic_stats

            ret['players'][steamid]['class_stats'] = []
            for cls in classes:
                tmp = extract(player, (('time', 'total_time'), 'kills', 'assists', 'deaths',
                                       ('damage', 'dmg')),
                              '{}_as_' + ('heavy' if cls == 'heavyweapons' else cls))
                if not any(tmp.values()):
                    continue

                tmp['type'] = cls
                weapons = self.c.execute("""SELECT
                                                *
                                            FROM player_weapon
                                            WHERE log_id = ?
                                                AND steam_id = ?
                                                AND class = ?;""", (logid, steamid, cls))
                tmp['weapon'] = {
                        weapon['weapon']: extract(weapon, ('kills', ('damage', 'dmg'),
                                                           ('average_damage', 'avg_dmg'),
                                                           'shots', 'hits'))
                        for weapon in weapons
                }

                ret['players'][steamid]['class_stats'].append(tmp)

            for prop, event in events.items():
                for cls in classes:
                    val = player['{}_{}s'.format('heavy' if cls == 'heavyweapons' else cls, event)]
                    if val:
                        ret[prop][steamid][cls] = val

        heals = self.c.execute("SELECT * FROM heal_spread WHERE log_id = ?", (logid,))
        ret['healspread'] = collections.defaultdict(dict)
        for heal in heals:
            ret['healspread'][heal['healer_steam_id']][heal['target_steam_id']] = heal['heal_amount']

        chat = self.c.execute("SELECT * FROM chat WHERE log_id = ? ORDER BY idx ASC", (logid,))
        ret['chat'] = [extract(msg, (('steam_id', 'steamid'), 'name', ('message', 'msg')))
                       for msg in chat]

        return ret
