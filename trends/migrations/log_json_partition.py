# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import json
import logging
import sys

import psycopg2.extras, psycopg2.extensions
import zstandard

from ..sql import db_connect, db_init
from ..importer.cli import init_logging
from ..util import chunk

def extract_json(c):
    dctx = zstandard.ZstdDecompressor()
    cur = c.cursor()
    with c.cursor(name='json', withhold=True) as cur:
        cur.itersize = 100
        cur.execute("""SELECT
                           logid,
                           log_json.data
                       FROM log_json
                       LEFT JOIN log_json_new USING (logid)
                       WHERE log_json_new.logid ISNULL
                       ORDER BY logid;""")
        logging.info("Executed")
        for log in cur:
            yield log[0], json.loads(dctx.decompress(log[1]))

def migrate(database):
    init_logging(logging.INFO)
    with db_connect(database) as c:
        cur = c.cursor()

        logging.info("Creating partitions")
        cur = c.cursor()
        cur.execute("BEGIN;")
        cur.execute("""CREATE TABLE IF NOT EXISTS log_json_new (
                           logid INTEGER PRIMARY KEY,
                           data JSON NOT NULL
                       ) PARTITION BY RANGE (logid);""")
        cur.execute("SELECT max(logid) FROM log_json;")
        max_logid = cur.fetchone()[0]
        for i in range(round((max_logid + 1e5) / 1e5)):
            cur.execute("""CREATE TABLE IF NOT EXISTS log_json_{:#02}e5
                           PARTITION OF log_json_new
                           FOR VALUES FROM (%s) TO (%s);""".format(i),
                        (i * 1e5, (i + 1) * 1e5))
        cur.execute("CREATE TABLE IF NOT EXISTS log_json_default PARTITION OF log_json_new DEFAULT;")
        cur.execute("COMMIT;")

        logging.info("Inserting data")
        for logs in chunk(extract_json(c), 1000):
            logs = list(logs)
            cur.execute("BEGIN;")
            psycopg2.extras.execute_values(cur,
                "INSERT INTO log_json_new (logid, data) VALUES %s;", logs)
            cur.execute("COMMIT;")
            logging.info(f"Imported chunk {logs[0][0]}")

        logging.info("Dropping and committing")
        cur.execute("BEGIN;")
        cur.execute("DROP TABLE log_json;")
        cur.execute("ALTER TABLE log_json_new RENAME TO log_json;")
        cur.execute("COMMIT;")

if __name__ == "__main__":
    migrate(sys.argv[1])
