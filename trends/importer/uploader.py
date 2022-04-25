# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import json
import logging

import psycopg2.extras
import zstandard

from ..steamid import SteamID
from ..util import chunk

def create_uploader_parser(sub):
    uploader= sub.add_parser("uploader", help="Populate the uploader field from existing logs")
    uploader.set_defaults(importer=import_uploader)

def extract_uploader(c):
    dctx = zstandard.ZstdDecompressor()
    with c.cursor(name='uploader', withhold=True) as cur:
        cur.execute("""SELECT
                           logid,
                           data
                       FROM log_json
                       JOIN log USING (logid)
                       WHERE uploader ISNULL;""")
        for log in cur:
            try:
                uploader = json.loads(dctx.decompress(log[1]))['info']['uploader']
                yield log[0], SteamID(uploader['id']), uploader['name']
            except (IndexError, KeyError, TypeError):
                logging.exception("Could not parse log %s", log[0])

def import_uploader(args, c):
    cur = c.cursor()

    for logs in chunk(extract_uploader(c), 1000):
        logs = list(logs)
        cur.execute("BEGIN;")
        psycopg2.extras.execute_values(cur,
            """INSERT INTO name (name)
               VALUES %s
               ON CONFLICT DO NOTHING;""", ((log[2],) for log in logs))
        psycopg2.extras.execute_values(cur,
            """INSERT INTO player (steamid64, nameid)
               SELECT
                   steamid64,
                   (SELECT nameid FROM name WHERE name = data.name)
               FROM (VALUES %s) AS data (logid, steamid64, name)
               GROUP BY steamid64, data.name
               ON CONFLICT DO NOTHING;""", logs)
        psycopg2.extras.execute_values(cur,
            """UPDATE log
               SET uploader = data.uploader,
                   uploader_nameid = (SELECT nameid FROM name WHERE name = data.name)
               FROM (VALUES %s) AS data (logid, uploader, name)
               WHERE log.logid = data.logid;""", logs)
        cur.execute("COMMIT;")
        logging.info("Imported chunk")
