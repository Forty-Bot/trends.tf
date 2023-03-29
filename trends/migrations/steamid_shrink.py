# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from ..sql import db_connect, db_init, delete_logs
from ..importer.cli import init_logging

def alter_cols(cur, table, *cols):
    if not cols:
        cols = ('steamid64',)

    clauses = ", ".join(f"ALTER {col} TYPE INT USING ({col} & 4294967295)" for col in cols)
    cur.execute(f"ALTER TABLE {table} {clauses};")
    if 'steamid64' in cols:
        cur.execute(f"ALTER TABLE {table} RENAME steamid64 TO playerid;")
    logging.info(f"ALTER TABLE {table} TYPE")

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

        cur.execute("""CREATE TEMP TABLE bad_players AS
                       SELECT steamid64
                       FROM player
                       WHERE steamid64 >> 32 != x'1100001'::INT;""")
        logging.info("CREATE TEMP TABLE bad_players")
        cur.execute("""CREATE TEMP TABLE to_delete AS
                       SELECT logid
                       FROM player_stats
                       JOIN bad_players USING (steamid64)
                       GROUP BY logid;""")
        logging.info("CREATE TEMP TABLE to_delete")
        delete_logs(cur)
        cur.execute("DELETE FROM player WHERE steamid64 IN (SELECT steamid64 FROM bad_players);")
        logging.info("DELETE players")
        cur.execute("COMMIT;")
        logging.info("COMMIT")

        cur.execute("BEGIN;")
        logging.info("BEGIN")

        ('player_stats_backing', 'player_stats_steamid64_fkey')
        for table, name in (
            ('log', 'uploader'),
            ('player_stats_extra', 'logid_steamid64'),
            ('medic_stats', 'logid_steamid64'),
            ('heal_stats', 'logid_healer'),
            ('heal_stats', 'logid_healee'),
            ('class_stats', 'logid_steamid64'),
            ('weapon_stats', 'logid_steamid64_classid'),
            ('event_stats', 'logid_steamid64'),
            ('chat', 'steamid64'),
        ):
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_{name}_fkey;")
            logging.info(f"ALTER TABLE {table} DROP CONSTRAINT {table}_{name}_fkey;")
        cur.execute("""ALTER TABLE player_stats_backing
                       DROP CONSTRAINT player_stats_steamid64_fkey;""")
        logging.info("ALTER TABLE player_stats DROP CONSTRAINT player_stats_steamid64_fkey")

        cur.execute("DROP MATERIALIZED VIEW leaderboard_cube;")
        logging.info("DROP MATERIALIZED VIEW leaderboard_cube")
        for view in ('player_stats', 'heal_stats_given', 'heal_stats_received'):
            cur.execute(f"DROP VIEW {view};")
            logging.info(f"DROP VIEW {view}")

        cur.execute("ALTER TABLE player ADD new_steamid64 BIGINT;")
        logging.info("ALTER TABLE player ADD new_steamid64")
        cur.execute("UPDATE player SET new_steamid64 = steamid64;")
        logging.info("UPDATE player")
        cur.execute("ALTER TABLE player ALTER new_steamid64 SET NOT NULL;")
        logging.info("ALTER TABLE player NOT NULL")
        cur.execute("CREATE UNIQUE INDEX player_steamid64_key ON player (new_steamid64);")
        logging.info("CREATE UNIQUE INDEX player_steamid64_key")
        alter_cols(cur, 'player')
        cur.execute("ALTER TABLE player RENAME new_steamid64 TO steamid64;")
        logging.info("ALTER TABLE player RENAME")
        cur.execute("SELECT max(playerid) FROM player;")
        cur.execute(f"CREATE SEQUENCE player_playerid_seq AS INT START {cur.fetchone()[0]}")
        logging.info("CREATE SEQUENCE player_playerid_seq")
        cur.execute("ALTER TABLE player ALTER playerid SET DEFAULT nextval('player_playerid_seq');")
        logging.info("ALTER TABLE player ALTER playerid SET DEFAULT")

        alter_cols(cur, 'log', 'uploader')
        alter_cols(cur, 'player_stats_backing')
        alter_cols(cur, 'player_stats_extra')
        alter_cols(cur, 'medic_stats')
        alter_cols(cur, 'heal_stats', 'healer', 'healee')
        alter_cols(cur, 'class_stats')
        alter_cols(cur, 'weapon_stats')
        alter_cols(cur, 'event_stats')
        alter_cols(cur, 'chat')
        cur.execute("""UPDATE demo
                       SET players = (SELECT
                               array_agg(player & 4294967295)
                           FROM unnest(players) AS player
                       );""")
        logging.info("UPDATE demo")
        cur.execute("ALTER TABLE demo ALTER players TYPE INT[];")
        logging.info("ALTER TABLE demo")

        add_fkey(cur, 'log', 'player', 'uploader', 'playerid')
        add_fkey(cur, 'player_stats_backing', 'player', 'playerid')
        add_fkey(cur, 'player_stats_extra', 'player_stats_backing', 'logid, playerid')
        add_fkey(cur, 'medic_stats', 'player_stats_backing', 'logid, playerid')
        add_fkey(cur, 'heal_stats', 'player_stats_backing', 'logid, healer', 'logid, playerid')
        add_fkey(cur, 'heal_stats', 'player_stats_backing', 'logid, healee', 'logid, playerid')
        add_fkey(cur, 'class_stats', 'player_stats_backing', 'logid, playerid')
        add_fkey(cur, 'weapon_stats', 'class_stats', 'logid, playerid, classid')
        add_fkey(cur, 'event_stats', 'player_stats_backing', 'logid, playerid')
        add_fkey(cur, 'chat', 'player', 'playerid')

        cur.execute("COMMIT;")

if __name__ == "__main__":
    migrate()
