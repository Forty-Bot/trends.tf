# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from datetime import datetime
from dateutil import tz
import functools
import re
import json
import logging
import time

from psycopg2.extras import NumericRange
import sentry_sdk

from ..cache import purge_matches
from .fetch import FetchError, RGLBulkFetcher, RGLFileFetcher
from .league import *
from ..sql import db_connect
from ..steamid import SteamID
from ..util import chunk

def filter_matchids(c, matchids):
    with c.cursor() as cur:
        for matchids in chunk(matchids, 100):
            psycopg2.extras.execute_values(cur,
                """SELECT new.matchid
                   FROM (VALUES %s) AS new (matchid)
                   LEFT JOIN match ON (league = 'rgl' AND match.matchid = new.matchid)
                   WHERE match.matchid IS NULL""", ((matchid,) for matchid in matchids))
            for row in cur:
                yield row[0]

def no_filter_matchids(c, matchids):
    yield from matchids

rgl_format_map = {
    'Sixes': 'sixes',
    'NR Sixes': 'sixes',
    'P7': 'prolander',
    'Prolander': 'prolander',
    'Fresh Meat': 'prolander',
    'HL': 'highlander',
    'Highlander': 'highlander',
    'Newcomer Cup': 'sixes',
    'PASS Time': 'fours',
}

RE_NAME_FORMAT = re.compile(r"(Sixes|NR Sixes|P7|Prolander|Fresh Meat|HL|Newcomer Cup|PASS Time)")
def parse_season(season):
    try:
        fmt = rgl_format_map[season['formatName']]
    except KeyError:
        m = RE_NAME_FORMAT.search(season['name'])
        if not m:
            raise ValueError(f"Unknown format for {season['name']}")
        fmt = rgl_format_map[m.group(1)]

    return {
        'format': fmt,
        'div_tiers': { int(div): -order for div, order in season['divisionSorting'].items() },
    }

def parse_date(date):
    if date is None:
        return None
    # datetime doesn't properly parse Z as a timezone
    return int(datetime.fromisoformat(date.replace('Z', "+00:00")).timestamp())

def parse_match(result):
    # FIXME: Dirty data, dirty hacks
    if result['matchId'] == 1418:
        result['isForfeit'] = True
    elif result['matchId'] == 1419:
        result['matchDate'] = "2018-09-27T01:30:00.000Z"
    elif result['matchId'] == 6495:
        result['matchDate'] = "2020-05-04T01:30:00.000Z"
    elif result['divisionId'] == 462:
        result['divisionName'] = "Solo Queue A"
    elif result['divisionId'] == 629:
        result['divisionId'] = 603
        result['divisionName'] = "Advanced"
    elif result['divisionId'] == 642:
        result['divisionId'] = 635
        result['divisionName'] = "Invite"

    return {
        'league': 'rgl',
        'compid': result['seasonId'],
        'competition': result['seasonName'],
        'divid': result['divisionId'],
        'division': result['divisionName'],
        'teams': tuple({
            'rgl_teamid': team['teamId'],
            'score': team['points'],
        } for team in result['teams']),
        'seq': ..., # FIXME
        'round': result['matchName'],
        'matchid': result['matchId'],
        'scheduled': parse_date(result['matchDate']),
        'submitted': None,
        'forfeit': result['isForfeit'],
        'fetched': result['fetched'],
        'maps': [map['mapName'] for map in result['maps']] or None,
    }

def parse_team(team):
    updates = []
    for player in team['players']:
        updates.append({
            'player': {
                'name': player['name'],
                'steamid64': SteamID(player['steamId']),
                'avatarhash': None,
                'eu_playerid': None,
            },
            'rostered': NumericRange(
                lower=parse_date(player['joinedAt']),
                upper=parse_date(player['leftAt'])
            ),
        })
        rostered = updates[-1]['rostered']
        if rostered.upper is not None and rostered.lower is not None \
            and rostered.upper <= rostered.lower:
            logging.info("Player %s (%s) on team %s joined before they left: %s <= %s",
                         player['name'], player['steamId'], team['teamId'], player['joinedAt'],
                         player['leftAt'])
            del updates[-1] # FIXME

    return {
        'league': 'rgl',
        'rgl_teamid': team['teamId'],
        'rgl_teamids': (team['teamId'], *team['linkedTeams']),
        'compid': team['seasonId'],
        'divid': team['divisionId'],
        'end_rank': team['finalRank'],
        'fetched': team['fetched'],
        'name': team['name'],
        'avatarhash': None, # TODO
        'updates': updates,
    }

def create_rgl_parser(sub):
    rgl = sub.add_parser("rgl", help="Import rgl matches")
    rgl.set_defaults(importer=import_rgl_cli)
    rgl.add_argument("-R", "--reimport", action='store_true',
                     help="Reimport all matches, even if they are already present")
    rgl_sub = rgl.add_subparsers()
    f = rgl_sub.add_parser("file", help="Import from the local filesystem")
    f.set_defaults(fetcher=RGLFileFetcher)
    f.add_argument("dir", metavar="DIR",
                   help="Directory containing season, match, and team responses.")
    b = rgl_sub.add_parser("bulk", help="Bulk import from api.rgl.gg")
    b.set_defaults(fetcher=RGLBulkFetcher)
    b.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=datetime.fromtimestamp(0, tz.UTC), metavar="DATE",
                   help="Only fetch matches created since DATE")
    b.add_argument("-N", "--new", action='store_true',
                   help="Only fetch matches created since the newest imported rgl")
    b.add_argument("-c", "--count", type=int, default=None,
                   help="Fetch up to COUNT matches, defaults to unlimited")
    b.add_argument("-p", "--skip", type=int, default=0,
                   help="Skip the first SKIP matches")

def import_rgl_cli(args, c, mc):
    with sentry_sdk.start_transaction(op="import", name="rgl_matches"):
        if 'new' in args and args.new:
            with c.cursor() as cur:
                cur.execute(
                    """SELECT least(max(scheduled), extract(EPOCH FROM now())::BIGINT) - 6 * 60 * 60
                       FROM match
                       WHERE league = 'rgl';""");
                args.since = datetime.fromtimestamp(cur.fetchone()[0])
        return import_rgl(c, mc, args.fetcher(**vars(args)),
                          no_filter_matchids if args.reimport else filter_matchids)

def import_rgl(c, mc, fetcher, filter=filter_matchids):
    @functools.cache
    def get_season(seasonid):
        return parse_season(fetcher.get_season(seasonid))

    cur = c.cursor()
    count = 0
    for matchid in filter(c, fetcher.get_matchids()):
        try:
            result = fetcher.get_match(matchid)
            res = parse_match(result)
            if res['teams'][0]['score'] is None and res['teams'][1]['score'] is None:
                continue

            if res['divid'] == 558:
                logging.info("Skipping inter-division match")
                continue

            cur.execute("""SELECT 1
                           FROM division
                           WHERE league = 'rgl'
                               AND compid = %(compid)s
                               AND divid = %(divid)s""", res)
            for _ in cur:
                season = None
                break
            else:
                season = get_season(res['compid'])
                res['format'] = season['format']
                res['tier'] = season['div_tiers'][res['divid']]

            for team in res['teams']:
                cur.execute(
                    """SELECT teamid, coalesce(fetched, 0)
                       FROM team_comp_backing
                       WHERE rgl_teamid = %(rgl_teamid)s
                       UNION ALL
                       SELECT NULL::INT, 0;""", team)
                row = cur.fetchone()

                if row[0] is None or row[1] <= (res['scheduled'] or 0) + 12 * 60 * 60:
                    team |= parse_team(fetcher.get_team(team['rgl_teamid']))
                    # FIXME broken divs!
                    if team['divid'] != res['divid']:
                        logging.info("Bad team division %s for team %s; should be %s",
                                     team['divid'], team['rgl_teamid'], res['divid'])
                    team['divid'] = res['divid']
                else:
                    team['teamid'] = row[0]

            with sentry_sdk.start_span(op='db.transaction', description=f"import {matchid}"):
                cur.execute("BEGIN;")
                if season:
                    import_compdiv(cur, res)

                for team in res['teams']:
                    if 'league' in team:
                        import_team(cur, team)

                if res['teams'][0]['teamid'] > res['teams'][1]['teamid']:
                    res['teams'] = (res['teams'][1], res['teams'][0])
                res['teamid1'] = res['teams'][0]['teamid']
                res['teamid2'] = res['teams'][1]['teamid']
                res['score1'] = res['teams'][0]['score']
                res['score2'] = res['teams'][1]['score']
                import_match(cur, res)
                purge_matches(c, mc)
                cur.execute("COMMIT;")
        except FetchError:
            continue
        except (IndexError, KeyError, psycopg2.errors.UniqueViolation):
            logging.exception("Could not parse match %s", matchid)
            cur.execute("ROLLBACK;")
        except psycopg2.Error:
            logging.error("Could not import match %s", matchid)
            raise
        else:
            count += 1
    logging.info("Imported %s matches", count)
