# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022-23 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..sql import db_connect, db_init, delete_logs
from ..importer.cli import init_logging

def alter_cols(cur, table, *cols):
    if not cols:
        cols = ('teamid',)

    clauses = ", ".join(f"ALTER {col} TYPE INT USING ({col} + 100000)" for col in cols)
    cur.execute(f"ALTER TABLE {table} {clauses};")
    for col in cols:
        cur.execute(f"""
            UPDATE {table}
            SET {col} = new.new_teamid
            FROM new
            WHERE league = 'rgl' AND new.teamid = {table}.{col} - 100000;""")
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

        cur.execute("""
            CREATE TEMP TABLE new AS
            SELECT
                teamid,
                min(rgl_teamid) AS new_teamid
            FROM team_comp_backing
            WHERE league = 'rgl'
            GROUP BY league, teamid;""")
        logging.info("CREATE TABLE new")

        alter_cols(cur, 'league_team')
        alter_cols(cur, 'team_comp_backing')
        alter_cols(cur, 'team_player')
        alter_cols(cur, 'match', 'teamid2', 'teamid1')
        cur.execute("""
            UPDATE log
            SET team1_is_red = NOT team1_is_red
            FROM match
            WHERE match.league = 'rgl' AND log.league = 'rgl'
                AND log.matchid = match.matchid
                AND teamid1 >= teamid2;""")
        logging.info("UPDATE log")
        cur.execute("""
            UPDATE match
            SET teamid1 = teamid2, teamid2 = teamid1
            WHERE teamid1 >= teamid2;""");
        logging.info("UPDATE match swap teamids")
        cur.execute("ALTER TABLE match ADD CHECK (teamid1 < teamid2)");
        logging.info("ALTER TABLE match ADD CHECK")

        add_fkey(cur, 'team_comp_backing', 'league_team', 'league, teamid')
        add_fkey(cur, 'team_player', 'team_comp_backing', 'league, teamid, compid')
        add_fkey(cur, 'team_player', 'league_team', 'league, teamid')
        add_fkey(cur, 'match', 'team_comp_backing', 'league, compid, teamid1',
                 'league, compid, teamid')
        add_fkey(cur, 'match', 'team_comp_backing', 'league, compid, teamid2',
                 'league, compid, teamid')

        cur.execute("ALTER TABLE league_team ALTER teamid DROP DEFAULT");
        cur.execute("DROP SEQUENCE league_team_teamid_seq;")

        cur.execute("COMMIT;")

if __name__ == "__main__":
    migrate()
