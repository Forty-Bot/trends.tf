# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
import logging

def create_link_parser(sub):
    link = sub.add_parser("link", help="Link logs and demos")
    link.set_defaults(importer=link_logs)
    link.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=datetime.now() - timedelta(hours=8), metavar="DATE",
                   help="Only link logs created before DATE")

def link_logs(args, c):
    with c.cursor() as cur:
        since = int(args.since.timestamp())
        cur.execute("BEGIN;")
        cur.execute("SELECT min(logid) FROM log WHERE time > %s", (since,))
        min_logid = cur.fetchone()[0]
        cur.execute("""CREATE TEMP TABLE linked AS
                       SELECT
                           logid,
                           demo.demoid
                       FROM log
                       JOIN (SELECT
                               logid,
                               array_agg(playerid) AS players
                           FROM player_stats
                           WHERE logid > %s
                           GROUP BY logid
                       ) AS log_players USING (logid)
                       CROSS JOIN demo
                       WHERE (log_players.players @> demo.players
                              OR demo.players @> log_players.players)
                           AND demo.time BETWEEN log.time - 300 AND log.time + 300
                           AND demo.time > %s
                           AND log_players.players NOTNULL
                           AND demo.players NOTNULL
                           AND log.demoid ISNULL;""",
                    (min_logid, since))
        cur.execute("SELECT count(*) from linked;");
        count = cur.fetchone()[0]
        cur.execute("""UPDATE log
                       SET demoid = linked.demoid
                       FROM linked
                       WHERE log.logid = linked.logid;""")
        cur.execute("COMMIT;")
        logging.info(f"Linked {count} logs")
