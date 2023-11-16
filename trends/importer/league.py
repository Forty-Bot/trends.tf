# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import psycopg2.extras

def import_compdiv(c, cd):
    """Import division and its competition
    cd should be a dict with the following keys:

    league: Internal league name ('rgl', etc.)
    compid: External API ID for the competition
    competition: Name of the competition
    format: Internal format type ('sixes', etc.)
    divid: External API ID for the division. May be None if this competition has no divisions, in
           which case division and tier will be ignored (and may be absent).
    division: Name of the division
    tier: Numeric tier of the division within the competition (for sorting)
    """

    c.execute(
        """INSERT INTO competition (league, compid, formatid, name)
           VALUES (
               %(league)s, %(compid)s,
               (SELECT formatid FROM format WHERE format = %(format)s), %(competition)s
           ) ON CONFLICT DO NOTHING;""", cd)
    if cd['divid'] is None:
        return

    c.execute("INSERT INTO div_name (division) VALUES (%(division)s) ON CONFLICT DO NOTHING;",
              cd)
    c.execute(
        """INSERT INTO division (league, compid, divid, div_nameid, tier)
           VALUES (
               %(league)s, %(compid)s, %(divid)s,
               (SELECT div_nameid FROM div_name WHERE division = %(division)s), %(tier)s
           ) ON CONFLICT DO NOTHING;""", cd)

def import_team(c, t):
    """Import a team
    The competition and division should already be imported. t should be a dict with the following
    keys:

    league: Internal league name ('rgl', etc.)
    compid: External API ID for the competition
    divid: External API ID for the division, if this competition has divisions, or None.
    name: Name of the team.
    teamid: External API team ID. Should be None for RGL, in which case this function will look up
            the internal team ID based on rgl_teamids and fill in teamid.
    rgl_teamid: RGL API team ID. Mandatory for RGL and should not be set otherwise.
    rgl_teamids: List of RGL API team IDs associated with this team (from other seasons). This
                 should include rgl_teamid. This is mandatory for RGL and should not be set
                 otherwise.
    avatarhash: Team avatar hash. The format is league-specific.
    end_rank: Final ranking of this team in the division (for sorting), or None if the competition
              is ongoing.
    fetched: Timestamp of when this team was fetched
    updates: An optional list of dicts with the following keys:
        player: A dict with the following keys:
            steamid64: SteamID of the transferring player
            name: Name of the player
            avatarhash: Avatar hash of the player, or None
            eu_playerid: ETF2L API player ID. Mandatory for ETF2L and should be None otherwise.
        rostered: NumericRange of the join/leave (unix) timestamps
    """

    teamid_col = "%(teamid)s"
    if teamids := t.get('rgl_teamids'):
        c.execute("SELECT teamid FROM team_comp WHERE rgl_teamid IN %s GROUP BY teamid",
                  (teamids,))
        if c.rowcount not in (0, 1):
            logging.warning("Too many matching teams for linked RGL teamids %s", teamids)

        if row := c.fetchone():
            t['teamid'] = row[0]
        else:
            teamid_col = "DEFAULT"

    c.execute("INSERT INTO team_name (team) VALUES (%(name)s) ON CONFLICT DO NOTHING", t)
    c.execute(
        f"""INSERT INTO league_team (league, teamid, team_nameid, avatarhash, fetched)
            VALUES (
                %(league)s, {teamid_col},
                CASE WHEN NOT league_team_per_comp(%(league)s) THEN (
                    SELECT team_nameid FROM team_name WHERE team = %(name)s
                ) END,
                CASE WHEN NOT league_team_per_comp(%(league)s) THEN %(avatarhash)s END,
                CASE WHEN NOT league_team_per_comp(%(league)s) THEN %(fetched)s END
            ) ON CONFLICT (league, teamid)
            DO UPDATE SET
                team_nameid = EXCLUDED.team_nameid,
                avatarhash = EXCLUDED.avatarhash,
                fetched = greatest(EXCLUDED.fetched, league_team.fetched)
            RETURNING teamid;""", t)
    if row := c.fetchone():
        t['teamid'] = row[0]

    t['rgl_teamid'] = t.get('rgl_teamid')
    c.execute(
        """INSERT INTO team_comp_backing (
               league, teamid, compid, divid, team_nameid, rgl_teamid, end_rank, avatarhash,
               fetched
           ) VALUES (
               %(league)s, %(teamid)s, %(compid)s, %(divid)s,
               CASE WHEN league_team_per_comp(%(league)s) THEN (
                   SELECT team_nameid FROM team_name WHERE team = %(name)s
               ) END, %(rgl_teamid)s, %(end_rank)s,
               CASE WHEN league_team_per_comp(%(league)s) THEN %(avatarhash)s END,
               CASE WHEN league_team_per_comp(%(league)s) THEN %(fetched)s END
           ) ON CONFLICT (league, teamid, compid)
           DO UPDATE SET
                divid = EXCLUDED.divid,
                team_nameid = EXCLUDED.team_nameid,
                avatarhash = EXCLUDED.avatarhash,
                end_rank = EXCLUDED.end_rank,
                fetched = greatest(EXCLUDED.fetched, team_comp_backing.fetched);""", t)

    if 'updates' in t and t['updates']:
        import_transfers(c, t)

def import_transfers(c, t):
    # Load new players...
    c.execute(
        """CREATE TEMP TABLE new_player (
               id SERIAL,
               steamid64 BIGINT,
               name TEXT,
               avatarhash TEXT,
               eu_playerid INT
           );""")
    psycopg2.extras.execute_values(c,
        "INSERT INTO new_player (steamid64, name, avatarhash, eu_playerid) VALUES %s;",
        (u['player'] for u in t['updates']),
        "(%(steamid64)s, %(name)s, %(avatarhash)s, %(eu_playerid)s)")
    # ... and remove duplicates
    c.execute(
        """DELETE FROM new_player np1
           USING new_player np2
           WHERE np1.steamid64 = np2.steamid64
               AND np2.id < np1.id""")
    c.execute("INSERT INTO name (name) SELECT name FROM new_player ON CONFLICT DO NOTHING;")
    c.execute(
        """INSERT INTO player (steamid64, nameid, avatarhash, eu_playerid) SELECT
               steamid64,
               (SELECT nameid FROM name WHERE name = new_player.name),
               avatarhash,
               eu_playerid
           FROM new_player
           ON CONFLICT (steamid64)
           DO UPDATE SET
               eu_playerid = coalesce(EXCLUDED.eu_playerid, player.eu_playerid);""")
    c.execute("DROP TABLE new_player;")

    # OK, here's the dance:
    # We need to determine the actual ranges when a player was rostered. This is effectively
    # union(intersection(ranges)), but there's no function in postgres to do this. So we are
    # going to roll our own, inspired by [1]. This is modified from the original to support
    # removing old ranges, and to support open-ended ranges without clobbering things in
    # between. That is, if we have something like
    #   [2,), (,6), [8,)
    # we want to get
    #   [2, 6), [8,)
    # and not
    #   [,)
    #
    # [1] https://dba.stackexchange.com/a/101010/219030
    c.execute(
        """CREATE TEMP TABLE old_ranges AS SELECT
               playerid,
               rostered
           FROM team_player
           WHERE league = %(league)s
               AND teamid = %(teamid)s
               AND (compid = %(compid)s OR compid ISNULL);""", t)
    psycopg2.extras.execute_values(c,
        """INSERT INTO old_ranges (playerid, rostered) SELECT
                playerid,
                rostered::INT8RANGE
            FROM (VALUES %s) AS ranges(steamid64, rostered)
            JOIN player USING (steamid64);""",
        ((u['player']['steamid64'], u['rostered']) for u in t['updates']))

    # This could probably be done as an UPDATE
    c.execute(
        """CREATE TEMP TABLE new_ranges AS SELECT
               playerid,
               rostered AS old,
               int8range(
                   min(lower(rostered)) OVER win,
                   CASE WHEN min(lower(rostered)) OVER win > max(endtime) OVER win THEN NULL ELSE
                       max(endtime) OVER win
                   END
               ) AS new
           FROM (SELECT
                   playerid,
                   rostered,
                   endtime,
                   count(next > endtime OR NULL) OVER WIN AS grp
               FROM (SELECT
                       playerid,
                       rostered,
                       lead(lower(rostered)) OVER win AS next,
                       max(upper(rostered)) OVER win AS endtime
                   FROM old_ranges
                   WINDOW win AS (
                       PARTITION BY playerid
                       ORDER BY least(lower(rostered), upper(rostered))
                   )
               ) AS a
               WINDOW win AS (
                   PARTITION BY playerid
                   ORDER BY least(lower(rostered), upper(rostered)) DESC
               )
           ) AS b
           WINDOW win AS (
               PARTITION BY playerid, grp
           );""")
    c.execute("DROP TABLE old_ranges;")

    c.execute(
        """DELETE FROM team_player
           USING new_ranges
           WHERE league = %(league)s
               AND teamid = %(teamid)s
               AND (compid = %(compid)s OR compid ISNULL)
               AND team_player.playerid = new_ranges.playerid
               AND team_player.rostered = new_ranges.old
               AND new_ranges.old != new_ranges.new;""", t)
    c.execute(
        """INSERT INTO team_player (league, teamid, compid, playerid, rostered)
           SELECT
               %(league)s,
               %(teamid)s,
               CASE WHEN league_team_per_comp(%(league)s) THEN %(compid)s END,
               playerid,
               new
           FROM new_ranges
           -- Some joins/leaves happen in the wrong order or are otherwise bogus
           WHERE new NOTNULL AND NOT isempty(new) AND NOT lower_inf(new)
           GROUP BY playerid, new
           ON CONFLICT DO NOTHING;""", t)
    c.execute("DROP TABLE new_ranges;")

def import_match(c, m):
    """Import a match transfers
    The competition, division, and teams should already be imported. m should be a dict with the
    following keys:

    league: Internal league name ('rgl', etc.)
    compid: External API ID for the competition
    divid: External API ID for the division, if this competition has divisions, or None
    matchid: External API ID for the match
    seq: Order of the round within the competition (for sorting). May be None if this competition
         doesn't have rounds, in which case round will be ignored and may be absent.
    round: Name of the round, if any
    teamid1: External/Internal team ID for the first team. Must be less than teamid2
    teamid2: External/Internal team ID for the second team. Must be greater than teamid2
    score1: Score of the first team
    score2: Score of the second team
    maps: List of maps played in the match
    forfeit: Whether this was a forfeit
    scheduled: Timestamp of when the match was scheduled to be played. Optional for ETF2L.
    submitted: Timestamp of when the match results were submitted, or None
    fetched: Timestamp of when this match was fetched
    """

    if m['seq'] is not None:
        c.execute("INSERT INTO round_name (round) VALUES (%(round)s) ON CONFLICT DO NOTHING;", m)
        col = "div" if m['divid'] else "comp"
        c.execute(
            f"""INSERT INTO {col}_round (league, {col}id, round_seq, round_nameid)
                VALUES (
                    %(league)s, %({col}id)s, %(seq)s,
                    (SELECT round_nameid FROM round_name WHERE round = %(round)s)
                ) ON CONFLICT DO NOTHING;""", m)

    c.execute("INSERT INTO map (map) SELECT unnest(%(maps)s::TEXT[]) ON CONFLICT DO NOTHING;", m)
    c.execute(
        """INSERT INTO match (
               league, matchid, compid, divid, teamid1, teamid2, round_seq, scheduled, submitted,
               mapids, score1, score2, forfeit, fetched
           ) VALUES (
               %(league)s, %(matchid)s, %(compid)s, %(divid)s, %(teamid1)s, %(teamid2)s, %(seq)s,
               %(scheduled)s, %(submitted)s,
               (SELECT
                       coalesce(array_agg(mapid ORDER BY mapid), array[]::INT[])
                   FROM map
                   WHERE map = any(%(maps)s)
               ), %(score1)s, %(score2)s, %(forfeit)s, %(fetched)s
           ) ON CONFLICT (league, matchid)
           DO UPDATE SET
               scheduled = EXCLUDED.scheduled,
               mapids = EXCLUDED.mapids,
               score1 = EXCLUDED.score1,
               score2 = EXCLUDED.score2,
               forfeit = EXCLUDED.forfeit,
               fetched = greatest(match.fetched, EXCLUDED.fetched);""", m)
