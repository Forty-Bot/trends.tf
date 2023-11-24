# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022-23 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..sql import db_connect, db_init, delete_logs
from ..importer.cli import init_logging

def alter_cols(cur, table, *cols):
    if not cols:
        cols = ('teamid',)

    for col in cols:
        cur.execute(f"""
            UPDATE {table}
            SET {col} = {col} - 100000
            WHERE league != 'rgl';""")
    logging.info(f"UPDATE TABLE {table}")

def add_fkey(cur, table_from, table_to, cols_from, cols_to=None):
    if cols_to is None:
        cols_to = cols_from
    cur.execute(f"""
        ALTER TABLE {table_from}
        ADD FOREIGN KEY ({cols_from}) REFERENCES {table_to} ({cols_to});""")
    logging.info(f"ALTER TABLE {table_from} REFERENCES {table_to}")

def migrate():
    init_logging(logging.DEBUG)
    with db_connect(sys.argv[1]) as c:
        cur = c.cursor()
        cur.execute("BEGIN;")
        logging.info("BEGIN")

        for table, name in (
            ('team_comp_backing', 'league_teamid'),
            ('team_player', 'league_teamid'),
            ('team_player', 'league_teamid_compid'),
            ('match', 'league_compid_teamid1'),
            ('match', 'league_compid_teamid2'),
        ):
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_{name}_fkey;")
            logging.info(f"ALTER TABLE {table} DROP CONSTRAINT {table}_{name}_fkey;")
        cur.execute("ALTER TABLE match DROP CONSTRAINT match_check;")

        for view in ('match_pretty', 'match_wlt', 'team_comp'):
            cur.execute(f"DROP VIEW {view};")
            logging.info(f"DROP VIEW {view}")

        alter_cols(cur, 'league_team')
        alter_cols(cur, 'team_comp_backing')
        alter_cols(cur, 'team_player')
        alter_cols(cur, 'match', 'teamid2', 'teamid1')

        add_fkey(cur, 'team_comp_backing', 'league_team', 'league, teamid')
        add_fkey(cur, 'team_player', 'team_comp_backing', 'league, teamid, compid')
        add_fkey(cur, 'team_player', 'league_team', 'league, teamid')
        add_fkey(cur, 'match', 'team_comp_backing', 'league, compid, teamid1',
                 'league, compid, teamid')
        add_fkey(cur, 'match', 'team_comp_backing', 'league, compid, teamid2',
                 'league, compid, teamid')

        cur.execute("COMMIT;")

if __name__ == "__main__":
    migrate()
