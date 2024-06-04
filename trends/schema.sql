--() { :; }; exec psql -f "$0" "$@"
-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020-23 Sean Anderson <seanga2@gmail.com>

CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS intarray;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS tsm_system_rows;

-- Numeric sort
CREATE COLLATION IF NOT EXISTS numeric (provider = icu, locale = 'en-u-kn-true');

-- Compute the sum of an array
CREATE OR REPLACE FUNCTION array_sum(anyarray) RETURNS anyelement
	AS 'SELECT sum(val) FROM unnest($1) AS val'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

-- The conjunctive counterpart to coalesce()
CREATE OR REPLACE FUNCTION nullelse(anyelement, anycompatible) RETURNS anycompatible
	AS 'SELECT CASE WHEN $1 NOTNULL THEN $2 END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

-- True IFF all values are equal
CREATE OR REPLACE FUNCTION equal(variadic anyarray) RETURNS BOOL
	AS 'SELECT every(comparison)
	    FROM (SELECT coalesce(val = lag(val, 1, val) over (), FALSE) AS COMPARISON
		  FROM unnest($1) AS vals(val)
	    ) AS comparisons'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE FUNCTION range_max2(anyrange, anyrange) RETURNS anyrange
	AS 'SELECT CASE WHEN $1 < $2 THEN $2 ELSE $1 END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE AGGREGATE range_max(anyrange) (
	SFUNC = range_max2,
	STYPE = anyrange,
	PARALLEL = SAFE
);

-- Compatibility functions for migration from SQLite

CREATE OR REPLACE FUNCTION add(FLOAT, anyelement) RETURNS FLOAT
	AS 'SELECT $1 + $2'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE AGGREGATE total(anyelement) (
	SFUNC = add,
	STYPE = FLOAT,
	INITCOND = 0.0,
	PARALLEL = SAFE
);

CREATE TABLE IF NOT EXISTS name (
	nameid SERIAL PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS name_tgrm ON name USING GIN (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS player (
	playerid SERIAL PRIMARY KEY,
	steamid64 BIGINT NOT NULL UNIQUE,
	nameid INT NOT NULL REFERENCES name (nameid),
	avatarhash TEXT,
	-- May be NULL if the player has only spectated or uploaded
	last_active BIGINT,
	-- Whether the user is banned from uploading
	banned BOOL NOT NULL DEFAULT FALSE,
	ban_reason TEXT,
	eu_playerid INT,
	CHECK (ban_reason NOTNULL = banned)
);

CREATE TABLE IF NOT EXISTS format (
	formatid SERIAL PRIMARY KEY,
	format TEXT NOT NULL UNIQUE,
	players INT
);

INSERT INTO format (format, players) VALUES
	('ultiduo', 4),
	('fours', 8),
	('sixes', 12),
	('prolander', 14),
	('highlander', 18),
	('other', NULL)
ON CONFLICT DO NOTHING;

DO $$ BEGIN
	CREATE TYPE TEAM AS ENUM ();
EXCEPTION WHEN duplicate_object THEN
	NULL;
END $$;

ALTER TYPE TEAM ADD VALUE IF NOT EXISTS 'Red';
ALTER TYPE TEAM ADD VALUE IF NOT EXISTS 'Blue';
COMMIT;

CREATE TABLE IF NOT EXISTS map (
	mapid SERIAL PRIMARY KEY,
	map TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS map_names ON map USING gin (map gin_trgm_ops);

DO $$ BEGIN
	CREATE TYPE LEAGUE AS ENUM ();
EXCEPTION WHEN duplicate_object THEN
	NULL;
END $$;

ALTER TYPE LEAGUE ADD VALUE IF NOT EXISTS 'etf2l';
ALTER TYPE LEAGUE ADD VALUE IF NOT EXISTS 'rgl';
COMMIT;

CREATE OR REPLACE FUNCTION league_div_optional(league LEAGUE) RETURNS BOOL
	AS 'SELECT CASE league WHEN ''etf2l'' THEN TRUE ELSE FALSE END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE FUNCTION league_time_optional(league LEAGUE) RETURNS BOOL
	AS 'SELECT CASE league WHEN ''etf2l'' THEN TRUE ELSE FALSE END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE FUNCTION league_round_optional(league LEAGUE) RETURNS BOOL
	AS 'SELECT CASE league WHEN ''etf2l'' THEN TRUE ELSE FALSE END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE FUNCTION league_team_per_comp(league LEAGUE) RETURNS BOOL
	AS 'SELECT CASE league WHEN ''rgl'' THEN TRUE ELSE FALSE END'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE TABLE IF NOT EXISTS competition (
	league LEAGUE NOT NULL,
	compid INT NOT NULL,
	formatid INT NOT NULL REFERENCES format (formatid),
	name TEXT NOT NULL,
	scheduled_from BIGINT,
	scheduled_to BIGINT,
	CHECK (equal(scheduled_from ISNULL, scheduled_to ISNULL)),
	PRIMARY KEY (league, compid)
);

CREATE TABLE IF NOT EXISTS div_name (
	div_nameid SERIAL PRIMARY KEY,
	division TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS division (
	league LEAGUE NOT NULL,
	compid INT NOT NULL,
	divid INT NOT NULL,
	div_nameid INT REFERENCES div_name (div_nameid),
	tier INT, -- Lower is better, starting at 0
	-- Not really the primary key, but necessary for the FK from team_comp
	PRIMARY KEY (league, compid, divid),
	FOREIGN KEY (league, compid) REFERENCES competition (league, compid)
);

-- For div_round, but also because we expect this in the first place
CREATE UNIQUE INDEX IF NOT EXISTS division_divid_unique ON division (league, divid);

CREATE TABLE IF NOT EXISTS team_name (
	team_nameid SERIAL PRIMARY KEY,
	team TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS team_names ON team_name USING gin (team gin_trgm_ops);

CREATE TABLE IF NOT EXISTS league_team (
	league LEAGUE NOT NULL,
	-- This is a surrogate key for RGL; for other leagues it is their teamid
	teamid INT NOT NULL,
	team_nameid INT REFERENCES team_name (team_nameid),
	avatarhash TEXT,
	-- When team_player (if not RGL) was last fetched
	fetched BIGINT,
	PRIMARY KEY (league, teamid),
	CHECK (equal(league_team_per_comp(league), fetched ISNULL, team_nameid ISNULL))
);

CREATE TABLE IF NOT EXISTS team_comp_backing (
	league LEAGUE NOT NULL,
	compid INT NOT NULL,
	teamid INT NOT NULL,
	divid INT,
	-- This is RGL's teamid; the same team will have one teamid per competition
	rgl_teamid INT UNIQUE,
	team_nameid INT REFERENCES team_name (team_nameid),
	avatarhash TEXT,
	-- When team_player (RGL only) was last fetched
	fetched BIGINT,
	end_rank INT,
	PRIMARY KEY (league, teamid, compid),
	FOREIGN KEY (league, teamid) REFERENCES league_team (league, teamid),
	FOREIGN KEY (league, compid) REFERENCES competition (league, compid),
	FOREIGN KEY (league, compid, divid) REFERENCES division (league, compid, divid),
	CHECK ((league = 'rgl') = (rgl_teamid NOTNULL)),
	CHECK (equal(league_team_per_comp(league), team_nameid NOTNULL, fetched NOTNULL)),
	CHECK (league_team_per_comp(league) OR avatarhash ISNULL),
	CHECK (league_div_optional(league) OR (divid NOTNULL))
);

CREATE OR REPLACE VIEW team_comp AS SELECT
	league,
	compid,
	teamid,
	divid,
	rgl_teamid,
	team AS team_name,
	coalesce(tc.avatarhash, lt.avatarhash) AS avatarhash,
	coalesce(tc.fetched, lt.fetched) AS fetched
FROM league_team AS lt
JOIN team_comp_backing AS tc USING (league, teamid)
JOIN team_name ON (team_name.team_nameid = coalesce(tc.team_nameid, lt.team_nameid));

CREATE TABLE IF NOT EXISTS team_player (
	league LEAGUE NOT NULL,
	teamid INT NOT NULL,
	-- Only for RGL to disambiguate joins/leagues from different team_comps
	-- Other leagues have the same roster across competitions
	compid INT,
	playerid INT NOT NULL REFERENCES player (playerid),
	rostered INT8RANGE NOT NULL
		CHECK (lower_inc(rostered) AND NOT upper_inc(rostered) AND NOT lower_inf(rostered)),
	-- This is (half of) the primary key
	EXCLUDE USING gist (
		league WITH =,
		compid WITH =,
		teamid WITH =,
		rostered WITH &&,
		playerid WITH =
	) WHERE (compid NOTNULL),
	-- And the other half
	EXCLUDE USING gist (
		league WITH =,
		teamid WITH =,
		rostered WITH &&,
		playerid WITH =
	) WHERE (compid ISNULL),
	FOREIGN KEY (league, teamid) REFERENCES league_team (league, teamid) DEFERRABLE,
	FOREIGN KEY (league, teamid, compid)
		REFERENCES team_comp_backing (league, teamid, compid) DEFERRABLE,
	CHECK (league_team_per_comp(league) = (compid NOTNULL))
);

CREATE INDEX IF NOT EXISTS team_player_teams ON team_player (league, teamid, compid);
CREATE INDEX IF NOT EXISTS team_player_playerid ON team_player (playerid);

CREATE TABLE IF NOT EXISTS round_name (
	round_nameid SERIAL PRIMARY KEY,
	round TEXT NOT NULL UNIQUE
);

-- Two tables, as we can't have foreign keys with NULL referenced values
CREATE TABLE IF NOT EXISTS comp_round (
	league LEAGUE NOT NULL CHECK (league_div_optional(league)),
	compid INT NOT NULL,
	-- To prevent conflicts with round.seq
	round_seq INT NOT NULL,
	round_nameid INT NOT NULL REFERENCES round_name (round_nameid),
	PRIMARY KEY (league, compid, round_seq),
	FOREIGN KEY (league, compid) REFERENCES competition (league, compid)
);

CREATE TABLE IF NOT EXISTS div_round (
	league LEAGUE NOT NULL,
	divid INT NOT NULL,
	-- To prevent conflicts with round.seq
	round_seq INT NOT NULL,
	round_nameid INT NOT NULL REFERENCES round_name (round_nameid),
	PRIMARY KEY (league, divid, round_seq),
	FOREIGN KEY (league, divid) REFERENCES division (league, divid)
);

-- A completed league match
CREATE TABLE IF NOT EXISTS match (
	league LEAGUE NOT NULL,
	matchid INT NOT NULL,
	compid INT NOT NULL,
	divid INT,
	teamid1 INT NOT NULL,
	teamid2 INT NOT NULL,
	round_seq INT,
	mapids INT[] NOT NULL CHECK (mapids = uniq(sort(mapids))),
	score1 REAL NOT NULL,
	score2 REAL NOT NULL,
	forfeit BOOL NOT NULL,
	scheduled BIGINT, -- Scheduled time for the match
	submitted BIGINT, -- Time results were submitted
	fetched BIGINT NOT NULL, -- Time we fetched the results
	-- Don't reference comp_round when we have a divid
	round_compid INT GENERATED ALWAYS AS (CASE WHEN divid ISNULL THEN compid END) STORED,
	PRIMARY KEY (league, matchid),
	FOREIGN KEY (league, compid, divid) REFERENCES division (league, compid, divid),
	FOREIGN KEY (league, round_compid, round_seq)
		REFERENCES comp_round (league, compid, round_seq),
	FOREIGN KEY (league, divid, round_seq) REFERENCES div_round (league, divid, round_seq),
	FOREIGN KEY (league, compid, teamid1)
		REFERENCES team_comp_backing (league, compid, teamid) DEFERRABLE,
	FOREIGN KEY (league, compid, teamid2)
		REFERENCES team_comp_backing (league, compid, teamid) DEFERRABLE,
	CHECK (teamid1 < teamid2),
	CHECK (league_div_optional(league) OR (divid NOTNULL)),
	CHECK (league_time_optional(league) OR forfeit OR (scheduled NOTNULL)),
	CHECK (league_round_optional(league) OR (round_seq NOTNULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS match_unique_div ON match (
	league, divid, round_seq, teamid1, teamid2
) WHERE divid NOTNULL;
CREATE UNIQUE INDEX IF NOT EXISTS match_unique_comp ON match (
	league, compid, round_seq, teamid1, teamid2
) WHERE divid ISNULL;
CREATE INDEX IF NOT EXISTS match_team1 ON match (teamid1);
CREATE INDEX IF NOT EXISTS match_team2 ON match (teamid2);
CREATE INDEX IF NOT EXISTS match_time ON match (scheduled);

CREATE OR REPLACE VIEW match_wlt AS SELECT
	league,
	matchid,
	compid,
	divid,
	teamid1 AS teamid,
	teamid2 AS opponent,
	round_seq,
	mapids,
	score1 AS rounds_won,
	score2 AS rounds_lost,
	forfeit,
	scheduled,
	submitted,
	fetched,
	(score1 > score2)::INT AS win,
	(score1 < score2)::INT AS loss,
	(score1 = score2)::INT AS tie,
	1 AS our_team
FROM match
UNION ALL
SELECT
	league,
	matchid,
	compid,
	divid,
	teamid2 AS teamid,
	teamid1 AS opponent,
	round_seq,
	mapids,
	score2 AS rounds_won,
	score1 AS rounds_lost,
	forfeit,
	scheduled,
	submitted,
	fetched,
	(score2 > score1)::INT AS win,
	(score2 < score1)::INT AS loss,
	(score2 = score1)::INT AS tie,
	2 AS our_team
FROM match;

CREATE OR REPLACE VIEW match_pretty AS SELECT
	match.league,
	matchid,
	match.compid,
	competition.name AS comp,
	match.divid,
	division AS div,
	tier,
	teamid1,
	teamid2,
	tc1.team_name AS team1,
	tc2.team_name AS team2,
	round_seq,
	round,
	mapids,
	(SELECT
			array_agg(map)
		FROM map
		JOIN unnest(mapids) AS mapid USING(mapid)
	) AS maps,
	score1,
	score2,
	forfeit,
	scheduled,
	submitted,
	match.fetched
FROM match
LEFT JOIN div_round USING (league, divid, round_seq)
LEFT JOIN comp_round USING (league, compid, round_seq)
JOIN round_name ON (
    round_name.round_nameid = coalesce(div_round.round_nameid,
                                       comp_round.round_nameid)
) JOIN competition USING (league, compid)
LEFT JOIN division USING (league, divid)
LEFT JOIN div_name USING (div_nameid)
JOIN team_comp AS tc1 ON (
    tc1.league = match.league
    AND tc1.compid = match.compid
    AND tc1.teamid = match.teamid1
) JOIN team_comp AS tc2 ON (
    tc2.league = match.league
    AND tc2.compid = match.compid
    AND tc2.teamid = match.teamid2
);

CREATE TABLE IF NOT EXISTS demo (
	demoid INTEGER PRIMARY KEY,
	url TEXT NOT NULL,
	server TEXT NOT NULL,
	duration INT NOT NULL,
	mapid INT NOT NULL REFERENCES map (mapid),
	time BIGINT NOT NULL,
	red_name TEXT NOT NULL,
	blue_name TEXT NOT NULL,
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	-- There should be a foreign key here, but postgres doesn't support it
	-- See https://commitfest.postgresql.org/17/1252/
	players INT[] CHECK (
		array_position(players, NULL) ISNULL
		AND array_ndims(players) = 1
		AND array_length(players, 0) != 0
	)
);

CREATE INDEX IF NOT EXISTS demo_time ON demo (time) INCLUDE (demoid);

CREATE TABLE IF NOT EXISTS log (
	logid INTEGER PRIMARY KEY, -- SQLite won't infer a rowid alias unless the type is INTEGER
	time BIGINT NOT NULL, -- Upload time
	duration INT NOT NULL CHECK (duration >= 0),
	title TEXT NOT NULL,
	mapid INT NOT NULL REFERENCES map (mapid),
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	formatid INT REFERENCES format (formatid),
	ad_scoring BOOLEAN, -- Whether attack/defense scoring is enabled
	-- Some logs may be duplicates or subsets of another log
	duplicate_of INT[] CHECK (duplicate_of = uniq(sort(duplicate_of))),
	uploader INT REFERENCES player (playerid),
	uploader_nameid INT REFERENCES name (nameid),
	demoid INT REFERENCES demo (demoid),
	league LEAGUE,
	matchid INT,
	team1_is_red BOOL,
	updated BIGINT NOT NULL,
	FOREIGN KEY (league, matchid) REFERENCES match (league, matchid),
	CHECK ((uploader ISNULL) = (uploader_nameid ISNULL)),
	-- All duplicates must be newer (and have larger logids) than what they are duplicates of
	-- This prevents cycles (though it does admit chains of finite length)
	CHECK (logid > duplicate_of[#duplicate_of]),
	CHECK (equal(league ISNULL, matchid ISNULL, team1_is_red ISNULL))
);

-- For the below view
CREATE INDEX IF NOT EXISTS log_nodups_pkey ON log (logid)
	WHERE duplicate_of ISNULL;

CREATE OR REPLACE VIEW log_nodups AS SELECT
	logid,
	time,
	duration,
	title,
	mapid,
	red_score,
	blue_score,
	formatid,
	league,
	matchid,
	team1_is_red,
	demoid
FROM log
WHERE duplicate_of ISNULL;

CREATE INDEX IF NOT EXISTS log_title ON log USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS log_time ON log (time);
CREATE INDEX IF NOT EXISTS log_updated on log (updated, time);
CREATE INDEX IF NOT EXISTS log_map ON log (mapid);
CREATE INDEX IF NOT EXISTS log_match ON log (league, matchid);

CREATE MATERIALIZED VIEW IF NOT EXISTS map_popularity AS
SELECT
	mapid,
	popularity,
	map
FROM map
JOIN (SELECT
		mapid,
		count(*) AS popularity
	FROM log
	GROUP BY mapid
) AS map_popularity USING (mapid)
ORDER BY popularity DESC, mapid ASC
WITH NO DATA;

-- The original json, zstd compressed
CREATE TABLE IF NOT EXISTS log_json (
	logid INTEGER PRIMARY KEY REFERENCES log (logid),
	data JSON NOT NULL
) PARTITION BY RANGE (logid);

CREATE TABLE IF NOT EXISTS log_json_default
PARTITION OF log_json (
	CONSTRAINT minimum CHECK (logid >= 0)
) DEFAULT;

CREATE TABLE IF NOT EXISTS round (
	logid INT NOT NULL REFERENCES log (logid),
	seq INT NOT NULL, -- Round number, starting at 0
	duration INT NOT NULL CHECK (duration > 0),
	time BIGINT NOT NULL,
	winner TEAM,
	firstcap TEAM,
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	red_kills INT NOT NULL,
	blue_kills INT NOT NULL,
	red_dmg INT NOT NULL,
	blue_dmg INT NOT NULL,
	red_ubers INT NOT NULL,
	blue_ubers INT NOT NULL,
	PRIMARY KEY (logid, seq)
);

CREATE TABLE IF NOT EXISTS class (
	classid SERIAL PRIMARY KEY,
	class TEXT NOT NULL UNIQUE
);

INSERT INTO class (class) VALUES
	('scout'),
	('soldier'),
	('pyro'),
	('demoman'),
	('engineer'),
	('heavyweapons'),
	('medic'),
	('sniper'),
	('spy')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS player_stats_backing (
	logid INT REFERENCES log (logid) NOT NULL,
	playerid INT REFERENCES player (playerid) NOT NULL,
	nameid INT NOT NULL REFERENCES name (nameid),
	team TEAM NOT NULL,
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	dt INT,
	wins INT NOT NULL DEFAULT 0, -- rounds won
	losses INT NOT NULL DEFAULT 0, -- rounds lost
	ties INT NOT NULL DEFAULT 0, -- rounds tied
	classids INT[] CHECK (array_position(classids, NULL) ISNULL AND array_ndims(classids) = 1),
	class_durations INT[] CHECK (array_position(class_durations, NULL) ISNULL
				     AND array_ndims(class_durations) = 1),
	shots INT,
	hits INT,
	PRIMARY KEY (playerid, logid),
	CHECK ((shots ISNULL) = (hits ISNULL)),
	CHECK ((classids NOTNULL AND class_durations NOTNULL
		AND array_length(classids, 1) = array_length(class_durations, 1))
	       OR (classids ISNULL AND class_durations ISNULL))
);

-- This index includes playerid and team so that it can be used as a covering index for the peers
-- query. This avoids a bunch of costly random reads to player_stats.
CREATE INDEX IF NOT EXISTS player_stats_peers
	ON player_stats_backing (logid)
	INCLUDE (playerid, team);

-- Covering index for name FTS queries
CREATE INDEX IF NOT EXISTS player_stats_names ON player_stats_backing (nameid) INCLUDE (playerid);

CREATE OR REPLACE VIEW player_stats AS SELECT
	player_stats_backing.*,
	CASE WHEN class_durations[1] * 1.5 > array_sum(class_durations)
		THEN classids[1]
	END AS primary_classid,
	(SELECT array_agg(class)
	 FROM unnest(classids) AS classid
	 JOIN class USING (classid)) AS classes,
	(SELECT array_agg(duration * 1.0 / nullif(array_sum(class_durations), 0.0))
	 FROM unnest(class_durations) AS duration) AS class_pct
FROM player_stats_backing;

CREATE TABLE IF NOT EXISTS player_stats_extra (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	suicides INT,
	dmg_real INT, -- Damage dealt just before/after a kill, cap, or uber
	dt_real INT,
	hr INT, -- Heals Received
	lks INT NOT NULL, -- Longest KillStreak
	airshots INT, -- "as" in the json
	medkits INT, -- Medkits taken (small: 1, medium: 2, large: 4)
	medkits_hp INT, -- HP from medkits
	backstabs INT,
	headshots INT, -- headshot kills
	headshots_hit INT, -- headshot non-kills
	sentries INT, -- sentries built
	healing INT,
	cpc INT, -- Capture Point Captures
	ic INT, -- Intel Captures
	PRIMARY KEY (playerid, logid),
	FOREIGN KEY (logid, playerid) REFERENCES player_stats_backing (logid, playerid),
	CHECK ((dmg_real ISNULL) = (dt_real ISNULL))
);

CREATE TABLE IF NOT EXISTS killstreak (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	time INT NOT NULL,
	kills INT NOT NULL CHECK (kills > 0),
	PRIMARY KEY (playerid, logid, time),
	FOREIGN KEY (logid, playerid) REFERENCES player_stats_backing (logid, playerid)
);

CREATE TABLE IF NOT EXISTS medic_stats (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	ubers INT NOT NULL,
	medigun_ubers INT,
	kritz_ubers INT,
	other_ubers INT,
	drops INT NOT NULL,
	advantages_lost INT,
	biggest_advantage_lost INT,
	avg_time_before_healing REAL CHECK (avg_time_before_healing > 0),
	avg_time_before_using REAL CHECK (avg_time_before_using > 0),
	avg_time_to_build REAL CHECK (avg_time_to_build > 0),
	avg_uber_duration REAL CHECK (avg_uber_duration > 0 AND avg_uber_duration < 8),
	deaths_after_uber INT, -- within 20s
	deaths_before_uber INT, -- 95-99%
	PRIMARY KEY (playerid, logid),
	FOREIGN KEY (logid, playerid) REFERENCES player_stats_backing (logid, playerid),
	CHECK (equal(medigun_ubers ISNULL, kritz_ubers ISNULL, other_ubers ISNULL)),
	CHECK (medigun_ubers ISNULL OR ubers = medigun_ubers + kritz_ubers + other_ubers),
	CHECK ((advantages_lost ISNULL) = (biggest_advantage_lost ISNULL))
);

-- For logs page
CREATE INDEX IF NOT EXISTS medic_stats_logid ON medic_stats (logid);

CREATE TABLE IF NOT EXISTS heal_stats (
	logid INT NOT NULL,
	healer INT NOT NULL,
	healee INT NOT NULL,
	healing INT NOT NULL,
	PRIMARY KEY (logid, healer, healee),
	-- Should reference medic_stats, but some very old logs only report one class per player
	FOREIGN KEY (logid, healer) REFERENCES player_stats_backing (logid, playerid),
	FOREIGN KEY (logid, healee) REFERENCES player_stats_backing (logid, playerid)
);

-- Index for looking up people healed in logs
CREATE INDEX IF NOT EXISTS heal_stats_healee ON heal_stats (healee);

-- Index for looking up people by healer in logs
CREATE INDEX IF NOT EXISTS heal_stats_healer ON heal_stats (healer);

CREATE STATISTICS IF NOT EXISTS heal_stats (ndistinct)
ON logid, healer
FROM heal_stats;

CREATE OR REPLACE VIEW heal_stats_given AS SELECT
	logid,
	healer AS playerid,
	sum(healing) AS healing
FROM heal_stats
GROUP BY logid, healer;

CREATE OR REPLACE VIEW heal_stats_received AS SELECT
	logid,
	healee AS playerid,
	sum(healing) AS healing
FROM heal_stats
GROUP BY logid, healee;

CREATE TABLE IF NOT EXISTS class_stats (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	classid INT NOT NULL REFERENCES class (classid),
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	duration INT NOT NULL,
	shots INT,
	hits INT,
	PRIMARY KEY (playerid, logid, classid),
	FOREIGN KEY (logid, playerid) REFERENCES player_stats_backing (logid, playerid),
	CHECK ((shots ISNULL) = (hits ISNULL))
);

-- For logs page
CREATE INDEX IF NOT EXISTS class_stats_logid ON class_stats (logid);

CREATE STATISTICS IF NOT EXISTS class_stats (ndistinct)
ON logid, playerid
FROM class_stats;

CREATE MATERIALIZED VIEW IF NOT EXISTS leaderboard_cube AS SELECT
	playerid,
	league,
	formatid,
	primary_classid AS classid,
	mapid,
	grouping(league, formatid, primary_classid, mapid) AS grouping,
	sum(log.duration) AS duration,
	sum((wins > losses)::INT) AS wins,
	sum((wins = losses)::INT) AS ties,
	sum((wins < losses)::INT) AS losses,
	sum(kills) AS kills,
	sum(deaths) AS deaths,
	sum(assists) AS assists,
	sum(dmg) AS dmg,
	sum(dt) AS dt,
	sum(shots) AS shots,
	sum(hits) AS hits
FROM log_nodups AS log
JOIN player_stats USING (logid)
GROUP BY playerid, CUBE (league, formatid, classid, mapid)
ORDER BY mapid, classid, formatid, playerid, league
WITH NO DATA;

-- To help out the query planner
CREATE STATISTICS IF NOT EXISTS leaderboard_stats (dependencies, ndistinct, mcv)
	ON league, formatid, classid, mapid, grouping
	FROM leaderboard_cube;

-- When we have no filters (or nothing better)
CREATE INDEX IF NOT EXISTS leaderboard_grouping ON leaderboard_cube (grouping);

-- When we have a single filter
CREATE INDEX IF NOT EXISTS leaderboard_league ON leaderboard_cube (league)
	WHERE grouping = b'0111'::INT
		AND league NOTNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid ISNULL;
CREATE INDEX IF NOT EXISTS leaderboard_format ON leaderboard_cube (formatid)
	WHERE grouping = b'1011'::INT
		AND league ISNULL
		AND formatid NOTNULL
		AND classid ISNULL
		AND mapid ISNULL;
CREATE INDEX IF NOT EXISTS leaderboard_class ON leaderboard_cube (classid)
	WHERE grouping = b'1101'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND classid NOTNULL
		AND mapid ISNULL;
CREATE INDEX IF NOT EXISTS leaderboard_map ON leaderboard_cube (mapid)
	WHERE grouping = b'1110'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid NOTNULL;

-- When we have multiple filters
CREATE INDEX IF NOT EXISTS leaderboard_bloom ON leaderboard_cube
	USING bloom (grouping, mapid, classid, formatid, league)
	WITH (col1=1, col2=1, col3=1, col4=1, col5=1);

CREATE MATERIALIZED VIEW IF NOT EXISTS medic_cube AS SELECT
	playerid,
	league,
	formatid,
	mapid,
	grouping(league, formatid, mapid) AS grouping,
	count(*) AS logs,
	sum(duration) AS duration,
	sum(ubers) AS ubers,
	sum(medigun_ubers) AS medigun_ubers,
	sum(kritz_ubers) AS kritz_ubers,
	sum(other_ubers) AS other_ubers,
	sum(drops) AS drops,
	sum(advantages_lost) AS advantages_lost,
	sum(avg_time_before_using * ubers) AS time_before_using,
	sum(nullelse(avg_time_before_using, ubers)) AS ubers_before_using,
	sum(avg_time_to_build * (ubers + drops)) AS time_to_build,
	sum(nullelse(avg_time_to_build, ubers + drops)) AS builds,
	sum(avg_uber_duration * ubers) AS uber_duration,
	sum(nullelse(avg_uber_duration, ubers)) AS ubers_duration,
	sum(nullelse(healing, duration)) AS healing_duration,
	sum(healing) AS healing,
	sum(healing_scout) AS healing_scout,
	sum(healing_soldier) AS healing_soldier,
	sum(healing_pyro) AS healing_pyro,
	sum(healing_demoman) AS healing_demoman,
	sum(healing_engineer) AS healing_engineer,
	sum(healing_heavyweapons) AS healing_heavyweapons,
	sum(healing_medic) AS healing_medic,
	sum(healing_sniper) AS healing_sniper,
	sum(healing_spy) AS healing_spy,
	sum(healing_enemy) AS healing_enemy,
	sum(healing_other) AS healing_other
FROM log_nodups AS log
JOIN medic_stats USING (logid)
LEFT JOIN (SELECT
		logid,
		healer AS playerid,
		sum(healing) AS healing,
		sum(CASE WHEN healer = healee THEN healing END) AS healing_self,
		sum(CASE WHEN class = 'scout' THEN healing END) AS healing_scout,
		sum(CASE WHEN class = 'soldier' THEN healing END) AS healing_soldier,
		sum(CASE WHEN class = 'pyro' THEN healing END) AS healing_pyro,
		sum(CASE WHEN class = 'demoman' THEN healing END) AS healing_demoman,
		sum(CASE WHEN class = 'engineer' THEN healing END) AS healing_engineer,
		sum(CASE WHEN class = 'heavyweapons' THEN healing END) AS healing_heavyweapons,
		sum(CASE WHEN class = 'medic' THEN healing END) AS healing_medic,
		sum(CASE WHEN class = 'sniper' THEN healing END) AS healing_sniper,
		sum(CASE WHEN class = 'spy' THEN healing END) AS healing_spy,
		sum(CASE WHEN healer_stats.team != healee_stats.team THEN healing END)
			AS healing_enemy,
		sum(CASE WHEN class ISNULL THEN healing END) AS healing_other
	FROM heal_stats
	JOIN player_stats AS healer_stats USING (logid)
	JOIN player_stats AS healee_stats USING (logid)
	LEFT JOIN class ON (classid=healee_stats.primary_classid)
	WHERE healer_stats.playerid = healer
		AND healee_stats.playerid = healee
	GROUP BY logid, healer
) AS heal_stats USING (logid, playerid)
GROUP BY playerid, CUBE (league, formatid, mapid)
ORDER BY mapid, formatid, playerid, league
WITH NO DATA;

-- To help out the query planner
CREATE STATISTICS IF NOT EXISTS medic_cube_stats (dependencies, ndistinct, mcv)
	ON league, formatid, mapid, grouping
	FROM medic_cube;

-- When we have no filters (or nothing better)
CREATE INDEX IF NOT EXISTS medic_grouping ON medic_cube (grouping);

-- When we have a single filter
CREATE INDEX IF NOT EXISTS medic_league ON medic_cube (league)
	WHERE grouping = b'011'::INT
		AND league NOTNULL
		AND formatid ISNULL
		AND mapid ISNULL;
CREATE INDEX IF NOT EXISTS medic_format ON medic_cube (formatid)
	WHERE grouping = b'101'::INT
		AND league ISNULL
		AND formatid NOTNULL
		AND mapid ISNULL;
CREATE INDEX IF NOT EXISTS medic_map ON medic_cube (mapid)
	WHERE grouping = b'110'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND mapid NOTNULL;

-- When we have multiple filters
CREATE INDEX IF NOT EXISTS medic_bloom ON medic_cube
	USING bloom (grouping, mapid, formatid, league)
	WITH (col1=1, col2=1, col3=1, col5=1);

CREATE TABLE IF NOT EXISTS weapon (
	weaponid SERIAL PRIMARY KEY,
	weapon TEXT NOT NULL UNIQUE,
	name TEXT
);

CREATE OR REPLACE VIEW weapon_pretty AS SELECT
	weaponid,
	coalesce(name, initcap(replace(weapon, '_', ' '))) AS weapon
FROM weapon;

CREATE TABLE IF NOT EXISTS weapon_stats (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	classid INT NOT NULL,
	weaponid INT NOT NULL REFERENCES weapon (weaponid),
	kills INT NOT NULL,
	dmg INT,
	avg_dmg REAL,
	shots INT,
	hits INT,
	PRIMARY KEY (playerid, logid, classid, weaponid),
	FOREIGN KEY (logid, playerid, classid) REFERENCES class_stats (logid, playerid, classid),
	CHECK ((shots ISNULL) = (hits ISNULL)),
	CHECK ((dmg ISNULL) = (avg_dmg ISNULL))
);

CREATE STATISTICS IF NOT EXISTS weapon_stats (ndistinct)
ON logid, playerid, classid
FROM weapon_stats;

-- For logs page
CREATE INDEX IF NOT EXISTS weapon_stats_logid ON weapon_stats (logid);

CREATE TABLE IF NOT EXISTS event (
	eventid SERIAL PRIMARY KEY,
	event TEXT NOT NULL UNIQUE
);

INSERT INTO event (event) VALUES ('kill'), ('death'), ('assist') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS event_stats (
	logid INT NOT NULL,
	playerid INT NOT NULL,
	eventid INT REFERENCES event (eventid),
	demoman INT NOT NULL,
	engineer INT NOT NULL,
	heavyweapons INT NOT NULL,
	medic INT NOT NULL,
	pyro INT NOT NULL,
	scout INT NOT NULL,
	sniper INT NOT NULL,
	soldier INT NOT NULL,
	spy INT NOT NULL,
	PRIMARY KEY (playerid, logid, eventid),
	FOREIGN KEY (logid, playerid) REFERENCES player_stats_backing (logid, playerid)
);

-- For logs page
CREATE INDEX IF NOT EXISTS event_logid ON event_stats (logid);

CREATE TABLE IF NOT EXISTS chat (
	logid INT NOT NULL REFERENCES log (logid),
	playerid INT REFERENCES player (playerid), -- May be NULL for Console messages
	seq INT NOT NULL, -- Message sequence, starting at 0; earlier messages have lower sequences
	msg TEXT NOT NULL,
	PRIMARY KEY (logid, seq)
);

-- Reverse index for lookups by playerid
-- Don't index NULLs since we don't generally want to look them up.
--CREATE INDEX IF NOT EXISTS chat_playerid ON chat (playerid, logid) WHERE playerid NOTNULL;

CREATE TABLE IF NOT EXISTS materialized_view (
	oid OID PRIMARY KEY,
	last_updated TIMESTAMPTZ
);

INSERT INTO materialized_view (oid) VALUES
	('leaderboard_cube'::REGCLASS),
	('medic_cube'::REGCLASS),
	('map_popularity'::REGCLASS)
ON CONFLICT DO NOTHING;
