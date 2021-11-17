# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import json
import logging

import psycopg2.extras
import zstandard

from ..util import chunk

def create_ad_parser(sub):
    ad = sub.add_parser("ad", help="Import A/D scoring data from existing logs")
    ad.set_defaults(importer=import_ad)

def extract_ad(c):
    dctx = zstandard.ZstdDecompressor()
    cur = c.cursor(name='ad', withhold=True)

    cur.execute("""SELECT
                       logid,
                       data
                   FROM log_json
                   JOIN log USING (logid)
                   WHERE ad_scoring ISNULL""")
    for log in cur:
        try:
            yield log[0], json.loads(dctx.decompress(log[1]))['info']['AD_scoring']
        except (IndexError, KeyError):
            logging.exception("Could not parse log %s", logid)

def import_ad(args, c):
    cur = c.cursor()

    for logs in chunk(extract_ad(c), 1000):
        cur.execute("BEGIN;")
        psycopg2.extras.execute_values(cur,
            """UPDATE log
               SET ad_scoring = data.ad
               FROM (VALUES %s) AS data (logid, ad)
               WHERE log.logid = data.logid;""", logs)
        cur.execute("COMMIT;")
        logging.info("Imported chunk")
