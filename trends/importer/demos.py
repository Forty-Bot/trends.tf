# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import argparse
from datetime import datetime
import json
import logging

import psycopg2
import sentry_sdk

from .fetch import DemoFileFetcher, DemoListFetcher, DemoBulkFetcher
from ..steamid import SteamID
from ..sql import disable_tracing, publicize
from .. import util
from ..util import chunk

def filter_demoids(c, demoids):
    for demoids in chunk(demoids, 100):
        with c.cursor() as cur:
            psycopg2.extras.execute_values(cur,
                """SELECT
                       demoid
                   FROM (VALUES %s) AS new (demoid)
                   LEFT JOIN public.demo USING (demoid)
                   WHERE public.demo.demoid IS NULL""", ((demoid,) for demoid in demoids))
            yield from (row[0] for row in cur)

def import_demo(c, demo):
    players = []
    for player in demo['players']:
        # Probably nothing useful here
        if player['team'] not in ('red', 'blue'):
            continue

        try:
            steamid = SteamID(player['steamid'])
        except ValueError:
            continue

        c.execute("INSERT INTO name (name) VALUES (%(name)s) ON CONFLICT DO NOTHING;", player)
        c.execute("""INSERT INTO player (
                         steamid64,
                         nameid,
                         last_active
                     ) VALUES (
                         %s,
                         (SELECT nameid FROM name WHERE name = %s),
                         %s
                     ) ON CONFLICT (steamid64)
                     DO UPDATE SET
                         last_active = greatest(player.last_active, EXCLUDED.last_active);""",
                  (steamid, player['name'], demo['time']))

    demo['players'] = players
    c.execute("INSERT INTO map (map) VALUES (%(map)s) ON CONFLICT DO NOTHING;", demo)
    c.execute("""INSERT INTO demo (
                     demoid, url, server, duration, mapid, time, red_name, blue_name, red_score,
                     blue_score, players
                 ) VALUES (
                     %(id)s, %(url)s, %(server)s, %(duration)s,
                     (SELECT mapid FROM map WHERE map = %(map)s), %(time)s, %(red)s, %(blue)s,
                     %(redScore)s, %(blueScore)s, %(players)s
                 )""", demo);

def create_demos_parser(sub):
    demos = sub.add_parser("demos", help="Import demos")
    demos.set_defaults(importer=import_demos_cli)
    demo_sub = demos.add_subparsers()
    f = demo_sub.add_parser("file", help="Import from the local filesystem")
    f.set_defaults(fetcher=DemoFileFetcher)
    f.add_argument("-l", "--demo", action='append', dest='demos',
                   help="Import a demo from a file. May be specified multiple times")
    b = demo_sub.add_parser("bulk", help="Bulk import from demos.tf")
    b.set_defaults(fetcher=DemoBulkFetcher)
    b.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=None, metavar="DATE",
                   help="Only fetch demos created since DATE")
    b.add_argument("-u", "--until", type=datetime.fromisoformat,
                   default=None, metavar="DATE",
                   help="Only fetch demos created before DATE")
    b.add_argument("-N", "--new", action='store_true',
                   help="Only fetch demos created since the newest imported demo")
    b.add_argument("-O", "--old", action='store_true',
                   help="Only fetch demos created before the oldest imported demo")
    b.add_argument("-c", "--count", type=int, default=None,
                   help="Fetch up to COUNT demos, defaults to unlimited")
    b.add_argument("-p", "--page", type=int, default=1,
                   help="Start at a particular page")
    l = demo_sub.add_parser("list", help="Import a list of demos from demos.tf")
    l.set_defaults(fetcher=DemoListFetcher)
    l.add_argument("-i", "--id", action='append', type=int, metavar="DEMOID",
                   dest='demoids', help="Fetch demo DEMOID")

def import_demos_cli(args, c):
    with sentry_sdk.start_transaction(op="import", name="demos"):
        if args.new:
            with c.cursor() as cur:
                cur.execute("SELECT max(time) - 6 * 60 * 60 FROM demo;");
                args.since = cur.fetchone()[0]
        if args.old:
            with c.cursor() as cur:
                cur.execute("SELECT min(time) + 6 * 60 * 60 FROM demo;");
                args.until = cur.fetchone()[0]
        return import_demos(c, args.fetcher(**vars(args)))

tables = (('demo', 'demoid'), ('demo_player_stats', 'demoid, steamid64'))

def import_demos(c, fetcher):
    cur = c.cursor()

    # Create some temporary tables for bulk inserts
    for table in tables:
        cur.execute("""CREATE TEMP TABLE {} (
                           LIKE {} INCLUDING ALL EXCLUDING INDEXES,
                           PRIMARY KEY ({})
                       );""".format(table[0], table[0], table[1]))

    def commit():
        with sentry_sdk.start_span(op='db.transaction', description="commit"):
            cur.execute("BEGIN;")
            publicize(c, tables)
            cur.execute("COMMIT;")
            logging.info("Committed %s imported demo(s)...", count)

    count = 0
    start = datetime.now()
    for demoid in filter_demoids(c, fetcher.get_logids()):
        demo = fetcher.get_log(demoid)
        if demo is None:
            continue

        with sentry_sdk.start_span(op='db.transaction', description=f"import {demoid}"), \
             disable_tracing():
            cur.execute("BEGIN;")
            try:
                import_demo(c.cursor(), demo)
            except (IndexError, KeyError, psycopg2.errors.NumericValueOutOfRange):
                logging.exception("Could not parse demo %s", demoid)
                cur.execute("ROLLBACK;")
            except psycopg2.Error:
                logging.error("Could not import demo %s", demoid)
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

    commit()
