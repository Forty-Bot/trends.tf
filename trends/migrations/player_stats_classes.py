# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..sql import db_connect, db_init
from ..importer.cli import init_logging
from ..importer.logs import update_player_classes

def migrate():
    init_logging(logging.DEBUG)
    with db_connect(sys.argv[1]) as c:
        logging.info("BEGIN")
        cur = c.cursor()
        for statement in (
            "BEGIN;",
            "ALTER TABLE player_stats ADD IF NOT EXISTS classids INT[] " \
                "CHECK (array_position(classids, NULL) ISNULL " \
                       "AND array_ndims(classids) = 1);",
            "ALTER TABLE player_stats ADD IF NOT EXISTS class_durations INT[] " \
                "CHECK (array_position(class_durations, NULL) ISNULL " \
                       "AND array_ndims(class_durations) = 1);",
            "ALTER TABLE player_stats ADD " \
                "CHECK ((classids NOTNULL AND class_durations NOTNULL " \
		                 "AND array_length(classids, 1) = array_length(class_durations, 1) " \
                       ") OR (classids ISNULL AND class_durations ISNULL));",
            "COMMIT;",
        ):
            cur.execute(statement)
        logging.info("ALTER TABLE")

        step = 100000
        cur.execute("SELECT min(logid), max(logid) FROM log;")
        for i in range(*cur.fetchone(), step):
            update_player_classes(cur, bounds=(i, i + step))
            logging.info("UPDATE {}".format(i))

if __name__ == "__main__":
    migrate()
