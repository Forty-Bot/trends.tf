# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from datetime import datetime
import re
import json
import logging
import time

from psycopg2.extras import NumericRange
import sentry_sdk

from .fetch import ETF2LFileFetcher, ETF2LBulkFetcher, FetchError
from .league import *
from ..sql import db_connect
from ..steamid import SteamID
from ..util import chunk

def filter_matchids(c, results):
    with c.cursor() as cur:
        for results in chunk(results, 100):
            results = { result['id']: result for result in results }
            psycopg2.extras.execute_values(cur,
                """SELECT new.matchid
                   FROM (VALUES %s) AS new (matchid)
                   LEFT JOIN match ON (league = 'etf2l' AND match.matchid = new.matchid)
                   WHERE match.matchid IS NULL""", ((matchid,) for matchid in results.keys()))
            for row in cur:
                yield results[row[0]]

UNKNOWN_AVATAR = "https://api.etf2l.org/img/unknown_avatar_full.jpg"
RE_ETF2L_AVATAR = re.compile(r"^.*([a-z0-9]{13}\.[a-z]{3})$")
RE_STEAM_AVATAR = re.compile(r"^.*([a-z0-9]{40})(|_medium|_full)\.[a-z]{3}$")
def parse_avatar(container, regex):
    url = container['steam']['avatar']
    if not url or url == UNKNOWN_AVATAR:
        return

    avatar = regex.match(url)
    if avatar:
        return avatar.group(1)
    else:
        logging.warning("no avatar hash for %s", url)

eu_type_map = {
    '1on1': 'other',
    '1v1': 'other',
    '2on2': 'ultiduo',
    '2v2': 'ultiduo',
    '6on6': 'sixes',
    '6v6': 'sixes',
    'National 6v6 Team': 'sixes',
    'Highlander': 'highlander',
    'Highlander Open': 'highlander',
    'National Highlander Team': 'highlander',
    'Fun Team': 'other',
    '6v6 Fun Team': 'sixes',
    'LAN Team': 'other',
}

def parse_result(result):
    def parse_team(team):
        return {
            'teamid': team['id'],
            'name': str(team['name']),
            'avatarhash': parse_avatar(team, RE_ETF2L_AVATAR),
            'end_rank': None,
        }

    comp = result['competition']
    div = result['division']
    teams = (parse_team(result['clan1']), parse_team(result['clan2']))
    if teams[0]['teamid'] > teams[1]['teamid']:
        teams = (teams[1], teams[0])
        (result['r1'], result['r2']) = (result['r2'], result['r1'])

    # XXX: Dirty hack for dirty data
    if div.get('id') == 17:
        comp = {
            'id': 1,
            'name': "Season 1",
            'type': '6on6',
        }

    return {
        'league': 'etf2l',
        'compid': comp['id'],
        'competition': comp['name'],
        'format': eu_type_map[comp['type']],
        'divid': div.get('id'),
        'division': div['name'],
        'tier': div['tier'],
        'teams': teams,
        'seq': result['week'],
        'round': result['round'],
        'matchid': result['id'],
        'scheduled': result['time'],
        'submitted': None,
        'fetched': result['fetched'],
        'maps': [map for map in result.get('maps', ()) if map != 'variable'] or None,
        'score1': result['r1'],
        'score2': result['r2'],
        'forfeit': not not result['defaultwin'],
    }

def parse_xfer(xfer):
    player = xfer['who']
    ret = {
        'player': {
            'steamid64': SteamID(player['steam']['id64']),
            'eu_playerid': player['id'],
            'avatarhash': parse_avatar(player, RE_STEAM_AVATAR),
            'name': player['name'],
        },
        'fetched': xfer['fetched']
    }

    if xfer['type'] == 'joined':
        ret['rostered'] = NumericRange(lower=xfer['time'])
    elif xfer['type'] == 'left':
        ret['rostered'] = NumericRange(upper=xfer['time'])
    else:
        raise Error("TODO")
    return ret

def create_etf2l_parser(sub):
    etf2l = sub.add_parser("etf2l", help="Import etf2l matches")
    etf2l.set_defaults(importer=import_etf2l_cli)
    etf2l_sub = etf2l.add_subparsers()
    f = etf2l_sub.add_parser("file", help="Import from the local filesystem")
    f.set_defaults(fetcher=ETF2LFileFetcher)
    f.add_argument("results", metavar="RESULTS", help="File with match results")
    f.add_argument("xferdir", metavar="XFERDIR",
                   help="Directory containing team transfers named 'transfer_TEAMID_PAGE.json'")
    b = etf2l_sub.add_parser("bulk", help="Bulk import from etf2ls.tf")
    b.set_defaults(fetcher=ETF2LBulkFetcher)
    b.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=0, metavar="DATE",
                   help="Only fetch matches created since DATE")
    b.add_argument("-N", "--new", action='store_true',
                   help="Only fetch matches created since the newest imported etf2l")
    b.add_argument("-c", "--count", type=int, default=None,
                   help="Fetch up to COUNT matches, defaults to unlimited")
    b.add_argument("-p", "--page", type=int, default=1,
                   help="Start at a particular page")

def import_etf2l_cli(args, c):
    with sentry_sdk.start_transaction(op="import", name="etf2l_matches"):
        if 'new' in args and args.new:
            with c.cursor() as cur:
                cur.execute(
                    """SELECT max(fetched) - 6 * 60 * 60
                       FROM match
                       WHERE league = 'etf2l';""");
                args.since = datetime.fromtimestamp(cur.fetchone()[0])
        return import_etf2l(c, args.fetcher(**vars(args)))


def import_etf2l(c, fetcher):
    cur = c.cursor()
    count = 0
    for result in filter_matchids(c, fetcher.get_results()):
        try:
            res = parse_result(result)
            for team in res['teams']:
                team['league'] = 'etf2l'
                team['compid'] = res['compid']
                team['divid'] = res['divid']

                cur.execute(
                    """SELECT coalesce(fetched, 0)
                       FROM league_team
                       WHERE league = 'etf2l'
                           AND teamid = %(teamid)s
                       UNION ALL
                       SELECT 0;""", team)
                row = cur.fetchone()
                if row[0] <= (res['fetched'] or 0):
                    team['fetched'] = time.time()
                    team['updates'] = []
                    for xfer in fetcher.get_xfers(team['teamid'], since=row[0]):
                        try:
                            team['updates'].append(parse_xfer(xfer))
                        except ValueError:
                            pass
                else:
                    team['fetched'] = row[0]
                    team['updates'] = ()

            res['teamid1'] = res['teams'][0]['teamid']
            res['teamid2'] = res['teams'][1]['teamid']
            # sigh...
            if res['teamid1'] == res['teamid2']:
                continue

            with sentry_sdk.start_span(op='db.transaction', description=f"import {result['id']}"):
                cur.execute("BEGIN;")
                import_compdiv(cur, res)
                for team in res['teams']:
                    import_team(cur, team)
                import_match(cur, res)
                cur.execute("COMMIT;")
        except FetchError:
            continue
        except (IndexError, KeyError, psycopg2.errors.UniqueViolation):
            logging.exception("Could not parse result %s", result['id'])
            cur.execute("ROLLBACK;")
        except psycopg2.Error:
            logging.error("Could not import result %s", result['id'])
            raise
        else:
            count += 1
    logging.info("Imported %s matches", count)
