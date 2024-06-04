# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2024 Sean Anderson <seanga2@gmail.com>

import logging
import sys

import psycopg2.extras

from ..importer.cli import init_logging
from ..sql import db_connect
from ..steamid import SteamID
from ..util import chunk

def migrate(database):
    init_logging(logging.DEBUG)
    with db_connect(database) as c:
        with c.cursor() as cur:
            logging.info("BEGIN")
            cur.execute("BEGIN");
            logging.info("CREATE TABLE killstreak")
            cur.execute("""
                CREATE TABLE killstreak (
                    logid INT NOT NULL,
                    playerid INT NOT NULL,
                    time INT NOT NULL,
                    kills INT NOT NULL CHECK (kills > 0),
                    PRIMARY KEY (playerid, logid, time)
                );""")

            with c.cursor(name='streaks') as streaks:
                streaks.execute("""
                    SELECT
                       logid,
                       streak -> 'steamid' AS steamid,
                       streak -> 'time' AS time,
                       streak -> 'streak' AS kills
                    FROM (SELECT
                           logid,
                           json_array_elements(data -> 'killstreaks') AS streak
                        FROM log_json
                    ) AS killstreak;""")
                for streaks in chunk(streaks, streaks.itersize):
                    values = []
                    for streak in streaks:
                        try:
                            values.append((streak[0], SteamID(streak[1]), streak[2], streak[3]))
                        except ValueError:
                            continue
                    logging.info("INSERT killstreak")
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO killstreak (
                            logid,
                            playerid,
                            time,
                            kills
                        ) SELECT
                            logid,
                            playerid,
                            time,
                            killstreak.kills
                        FROM (VALUES %s) AS killstreak (logid, steamid64, time, kills)
                        JOIN player USING (steamid64)
                        JOIN player_stats USING (logid, playerid)
                        ON CONFLICT DO NOTHING;""",
                        values, "(%s, %s, %s, %s)")
            
            logging.info("ALTER TABLE")
            cur.execute("""
                ALTER TABLE killstreak
                ADD FOREIGN KEY (logid, playerid)
                REFERENCES player_stats_backing (logid, playerid);""")
            logging.info("COMMIT")
            cur.execute("COMMIT;")

if __name__ == "__main__":
    migrate(sys.argv[1])
