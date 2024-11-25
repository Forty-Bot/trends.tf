# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
import logging

def create_link_matches_parser(sub):
    link = sub.add_parser("link_matches", help="Link logs and matches")
    link.set_defaults(importer=link_matches)
    link.add_argument("-s", "--since", type=datetime.fromisoformat,
                   default=datetime.now() - timedelta(days=7), metavar="DATE",
                   help="Only link logs created before DATE")

def link_matches(args, c, mc):
    with c.cursor() as cur:
        since = int(args.since.timestamp())
        cur.execute("BEGIN;")
        cur.execute(
            """CREATE TEMP TABLE log_teams AS SELECT
                   logid,
                   time,
                   red,
                   blue
               FROM log
               JOIN (SELECT
                       logid,
                       array_agg(playerid) AS red
                   FROM player_stats
                   WHERE team = 'Red'
                   GROUP BY logid
               ) AS red USING (logid)
               JOIN (SELECT
                       logid,
                       array_agg(playerid) AS blue
                   FROM player_stats
                   WHERE team = 'Blue'
                   GROUP BY logid
               ) AS blue USING (logid)
               WHERE league ISNULL AND time > %s;""", (since,))
        cur.execute("CREATE INDEX log_teams_time ON log_teams (time);")
        cur.execute("ANALYZE log_teams;")

        cur.execute(
            """CREATE TEMP TABLE log_matches AS SELECT
                   logid,
                   league,
                   matchid,
                   #(match1.players & log.red) + #(match2.players & log.blue) >
                       #(match1.players & log.blue) + #(match2.players & log.red) AS team1_is_red
               FROM (SELECT
                       match.league,
                       matchid,
                       match.compid,
                       scheduled AS time,
                       array_agg(playerid) AS players
                   FROM match
                   JOIN team_player AS tp ON (
                       tp.league = match.league
                       AND tp.teamid = match.teamid1
                       AND tp.rostered @> match.scheduled
                   ) WHERE scheduled > %s
                   GROUP BY match.league, matchid, match.compid, match.scheduled
               ) AS match1
               JOIN (SELECT
                       match.league,
                       matchid,
                       array_agg(playerid) AS players
                   FROM match
                   JOIN team_player AS tp ON (
                       tp.league = match.league
                       AND tp.teamid = match.teamid2
                       AND tp.rostered @> match.scheduled
                   ) GROUP BY match.league, matchid
               ) AS match2 USING (league, matchid)
               JOIN competition USING (league, compid)
               JOIN format USING (formatid)
               CROSS JOIN log_teams AS log
               WHERE log.time BETWEEN match1.time - 12 * 60 * 60 AND match1.time + 12 * 60 * 60
                   AND (#(match1.players & (log.red | log.blue)) >= format.players / 3
                        AND #(match2.players & (log.red | log.blue)) >= format.players / 3)
                   AND #((log.red | log.blue) - match1.players - match2.players) <=
                         format.players / 3;""", (since,))

        cur.execute("SELECT count(*) from log_matches;");
        count = cur.fetchone()[0]
        cur.execute("""UPDATE log SET
                           league = log_matches.league,
                           matchid = log_matches.matchid,
                           updated = greatest(extract(EPOCH FROM now())::BIGINT, log.updated + 1),
                           team1_is_red = log_matches.team1_is_red
                       FROM log_matches
                       WHERE log.logid = log_matches.logid;""")
        cur.execute("COMMIT;")
        logging.info(f"Linked {count} logs")
