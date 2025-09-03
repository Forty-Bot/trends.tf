# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022, 25 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..cache import mc_connect
from ..sql import db_connect, db_init, db_schema
from ..importer.cli import init_logging
from ..importer.logs import update_healing
from ..importer.refresh import refresh

def migrate():
    init_logging(logging.DEBUG)
    mc = mc_connect(sys.argv[2])
    with db_connect(sys.argv[1]) as c:
        logging.info("BEGIN")
        cur = c.cursor()
        cur.execute("BEGIN;")
        cur.execute("ALTER TABLE player_stats_backing ADD IF NOT EXISTS hsg INT;")
        cur.execute("ALTER TABLE player_stats_backing ADD IF NOT EXISTS hsr INT;")
        cur.execute("COMMIT;")
        logging.info("ALTER TABLES")

        step = 100000
        cur.execute("SELECT min(logid), max(logid) FROM log;")
        for i in range(*cur.fetchone(), step):
            update_healing(cur, bounds=(i, i + step))
            logging.info("UPDATE {}".format(i))

        for view in ('leaderboard_cube', 'medic_cube'):
            cur.execute(f"DROP MATERIALIZED VIEW {view};")
        for view in ('player_stats', 'heal_stats_given', 'heal_stats_received'):
            cur.execute(f"DROP VIEW {view};")
        logging.info("DROP VIEW")

        db_schema(cur)
        logging.info("CREATE VIEW")

        refresh(None, c, mc)

if __name__ == "__main__":
    migrate()
