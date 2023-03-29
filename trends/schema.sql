--() { :; }; exec psql -f "$0" "$@"
-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

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
	players INT[] NOT NULL CHECK (
		array_position(players, NULL) ISNULL
		AND array_ndims(players) = 1
	)
);

CREATE INDEX IF NOT EXISTS demo_time ON demo (time) INCLUDE (demoid);

CREATE TABLE IF NOT EXISTS log (
	logid INTEGER PRIMARY KEY, -- SQLite won't infer a rowid alias unless the type is INTEGER
	time BIGINT NOT NULL, -- Upload time
	duration INT NOT NULL,
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
	formatid
FROM log
WHERE duplicate_of ISNULL;

-- For log search
CREATE INDEX IF NOT EXISTS log_title ON log USING gin (title gin_trgm_ops);

-- To filter by date
CREATE INDEX IF NOT EXISTS log_time ON log (time);

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
	duration INT NOT NULL,
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
	avg_time_before_healing REAL,
	avg_time_before_using REAL,
	avg_time_to_build REAL,
	avg_uber_duration REAL,
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
	formatid,
	classid,
	mapid,
	sum(log.duration) AS duration,
	sum((wins > losses)::INT) AS wins,
	sum((wins = losses)::INT) AS ties,
	sum((wins < losses)::INT) AS losses
FROM log_nodups AS log
JOIN player_stats_backing USING (logid)
LEFT JOIN class_stats USING (logid, playerid)
WHERE class_stats.duration * 1.5 >= log.duration
GROUP BY CUBE (playerid, formatid, classid, mapid)
ORDER BY mapid, classid, formatid, playerid
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS leaderboard_pkey
	ON leaderboard_cube (mapid, classid, formatid, playerid);

CREATE INDEX IF NOT EXISTS leaderboard_classid ON leaderboard_cube (classid, formatid);

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
