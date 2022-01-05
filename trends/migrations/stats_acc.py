# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..sql import db_connect, db_init
from ..importer.cli import init_logging
from ..importer.logs import update_acc

def migrate():
    init_logging(logging.DEBUG)
    with db_connect(sys.argv[1]) as c:
        logging.info("BEGIN")
        cur = c.cursor()
        cur.execute("BEGIN;")
        for table in ("player_stats", "class_stats"):
            for statement in (
                "ALTER TABLE {} ADD IF NOT EXISTS hits INT;",
                "ALTER TABLE {} ADD IF NOT EXISTS shots INT;",
                "ALTER TABLE {} ADD " \
                    "CHECK ((shots NOTNULL AND hits NOTNULL) OR (shots ISNULL AND hits ISNULL));",
            ):
                cur.execute(statement.format(table))
        cur.execute("COMMIT;")
        logging.info("ALTER TABLES")

        step = 100000
        cur.execute("SELECT min(logid), max(logid) FROM log;")
        for i in range(*cur.fetchone(), step):
            update_acc(cur, bounds=(i, i + step))
            logging.info("UPDATE {}".format(i))

if __name__ == "__main__":
    migrate()
