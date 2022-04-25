# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import json
import logging

import psycopg2.extras
import zstandard

from .fetch import ListFetcher
from ..util import chunk

def create_json_parser(sub):
    json = sub.add_parser("json", help="Download JSON for logs already in the database")
    json.set_defaults(importer=import_json)

def pack_log(c):
    fetcher = ListFetcher()
    cctx = zstandard.ZstdCompressor()
    cur = c.cursor()

    cur.execute("""SELECT logid
                   FROM log
                   LEFT JOIN log_json USING (logid)
                   WHERE data ISNULL;""")
    for logid in cur:
        log = fetcher.get_log(logid[0])
        if log is None:
            logging.warning(f"Skipping {logid}")
        yield logid[0], cctx.compress(json.dumps(log).encode())

def import_json(args, c):
    cur = c.cursor()

    for logs in chunk(pack_log(c), 50):
        cur.execute("BEGIN;")
        psycopg2.extras.execute_values(cur, "INSERT INTO log_json (logid, data) VALUES %s;", logs)
        cur.execute("COMMIT;")
        logging.info("Committed json")
