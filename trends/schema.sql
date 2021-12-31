--() { :; }; exec psql -f "$0" "$@"
-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS tsm_system_rows;

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

CREATE TABLE IF NOT EXISTS map (
	mapid SERIAL PRIMARY KEY,
	map TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS map_names ON map USING gin (map gin_trgm_ops);

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
	duplicate_of INT REFERENCES log (logid),
	-- All duplicates must be earlier (and have smaller logids) than what they are duplicates of
	-- This prevents cycles (though it does admit chains of finite length)
	CHECK (logid < duplicate_of)
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

-- The original json, zstd compressed
CREATE TABLE IF NOT EXISTS log_json (
	logid INTEGER PRIMARY KEY REFERENCES log (logid),
	data BYTEA NOT NULL
);

CREATE TABLE IF NOT EXISTS team (
	teamid SERIAL PRIMARY KEY,
	team TEXT NOT NULL UNIQUE
);

INSERT INTO team (team) VALUES ('Red'), ('Blue') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS round (
	logid INT NOT NULL REFERENCES log (logid),
	seq INT NOT NULL, -- Round number, starting at 0
	duration INT NOT NULL,
	winner INT REFERENCES team (teamid),
	PRIMARY KEY (logid, seq)
);

CREATE TABLE IF NOT EXISTS round_extra (
	logid INT NOT NULL,
	seq INT NOT NULL,
	time BIGINT,
	firstcap INT REFERENCES team (teamid),
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	red_kills INT NOT NULL,
	blue_kills INT NOT NULL,
	red_dmg INT NOT NULL,
	blue_dmg INT NOT NULL,
	red_ubers INT NOT NULL,
	blue_ubers INT NOT NULL,
	PRIMARY KEY (logid, seq),
	FOREIGN KEY (logid, seq) REFERENCES round (logid, seq)
);

CREATE TABLE IF NOT EXISTS name (
	nameid SERIAL PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS name_tgrm ON name USING GIN (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS player (
	steamid64 BIGINT PRIMARY KEY,
	nameid INT NOT NULL REFERENCES name (nameid),
	avatarhash TEXT,
	last_active BIGINT NOT NULL
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

CREATE TABLE IF NOT EXISTS player_stats (
	logid INT REFERENCES log (logid) NOT NULL,
	steamid64 BIGINT REFERENCES player (steamid64) NOT NULL,
	nameid INT NOT NULL REFERENCES name (nameid),
	teamid INT NOT NULL REFERENCES team (teamid),
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	dt INT,
	wins INT NOT NULL DEFAULT 0, -- rounds won
	losses INT NOT NULL DEFAULT 0, -- rounds lost
	ties INT NOT NULL DEFAULT 0, -- rounds tied
	primary_classid INT REFERENCES class (classid), -- Class played more than 2/3 of the time
	PRIMARY KEY (steamid64, logid)
);

-- This index includes steamid64 and team so that it can be used as a covering index for the peers
-- query. This avoids a bunch of costly random reads to player_stats.
CREATE INDEX IF NOT EXISTS player_stats_peers ON player_stats (logid) INCLUDE (steamid64, teamid);

-- Covering index for name FTS queries
CREATE INDEX IF NOT EXISTS player_stats_names ON player_stats (nameid) INCLUDE (steamid64);

CREATE TABLE IF NOT EXISTS player_stats_extra (
	logid INT NOT NULL,
	steamid64 BIGINT NOT NULL,
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
	PRIMARY KEY (steamid64, logid),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64),
	CHECK ((dmg_real NOTNULL AND dt_real NOTNULL) OR (dmg_real ISNULL AND dt_real ISNULL))
);

CREATE TABLE IF NOT EXISTS medic_stats (
	logid INT NOT NULL,
	steamid64 BIGINT NOT NULL,
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
	PRIMARY KEY (steamid64, logid),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64),
	CHECK ((medigun_ubers ISNULL AND kritz_ubers ISNULL AND other_ubers ISNULL) OR
	       (medigun_ubers NOTNULL AND kritz_ubers NOTNULL AND other_ubers NOTNULL)),
	CHECK (medigun_ubers ISNULL OR ubers = medigun_ubers + kritz_ubers + other_ubers),
	CHECK ((advantages_lost NOTNULL AND biggest_advantage_lost NOTNULL) OR
	       (advantages_lost ISNULL AND biggest_advantage_lost ISNULL))
);

-- For logs page
CREATE INDEX IF NOT EXISTS medic_stats_logid ON medic_stats (logid);

CREATE TABLE IF NOT EXISTS heal_stats (
	logid INT NOT NULL,
	healer BIGINT NOT NULL,
	healee BIGINT NOT NULL,
	healing INT NOT NULL,
	PRIMARY KEY (logid, healer, healee),
	-- Should reference medic_stats, but some very old logs only report one class per player
	FOREIGN KEY (logid, healer) REFERENCES player_stats (logid, steamid64),
	FOREIGN KEY (logid, healee) REFERENCES player_stats (logid, steamid64)
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
	healer AS steamid64,
	sum(healing) AS healing
FROM heal_stats
GROUP BY logid, healer;

CREATE OR REPLACE VIEW heal_stats_received AS SELECT
	logid,
	healee AS steamid64,
	sum(healing) AS healing
FROM heal_stats
GROUP BY logid, healee;

CREATE TABLE IF NOT EXISTS class_stats (
	logid INT NOT NULL,
	steamid64 BIGINT NOT NULL,
	classid INT NOT NULL REFERENCES class (classid),
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	duration INT NOT NULL,
	PRIMARY KEY (steamid64, logid, classid),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
);

-- For logs page
CREATE INDEX IF NOT EXISTS class_stats_logid ON class_stats (logid);

CREATE STATISTICS IF NOT EXISTS class_stats (ndistinct)
ON logid, steamid64
FROM class_stats;

CREATE MATERIALIZED VIEW IF NOT EXISTS leaderboard_cube AS SELECT
	steamid64,
	formatid,
	classid,
	mapid,
	sum(log.duration) AS duration,
	sum((wins > losses)::INT) AS wins,
	sum((wins = losses)::INT) AS ties,
	sum((wins < losses)::INT) AS losses
FROM log_nodups AS log
JOIN player_stats USING (logid)
LEFT JOIN class_stats USING (logid, steamid64)
WHERE class_stats.duration * 1.5 >= log.duration
GROUP BY CUBE (steamid64, formatid, classid, mapid)
ORDER BY mapid, classid, formatid, steamid64
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS leaderboard_pkey
	ON leaderboard_cube (mapid, classid, formatid, steamid64);

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
	steamid64 BIGINT NOT NULL,
	classid INT NOT NULL,
	weaponid INT NOT NULL REFERENCES weapon (weaponid),
	kills INT NOT NULL,
	dmg INT,
	avg_dmg REAL,
	shots INT,
	hits INT,
	PRIMARY KEY (steamid64, logid, classid, weaponid),
	FOREIGN KEY (logid, steamid64, classid) REFERENCES class_stats (logid, steamid64, classid),
	CHECK ((shots NOTNULL AND hits NOTNULL) OR (shots ISNULL AND hits ISNULL)),
	CHECK ((dmg NOTNULL AND avg_dmg NOTNULL) OR (dmg ISNULL AND avg_dmg ISNULL))
);

CREATE STATISTICS IF NOT EXISTS weapon_stats (ndistinct)
ON logid, steamid64, classid
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
	steamid64 BIGINT NOT NULL,
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
	PRIMARY KEY (steamid64, logid, eventid),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
);

-- For logs page
CREATE INDEX IF NOT EXISTS event_logid ON event_stats (logid);

CREATE TABLE IF NOT EXISTS chat (
	logid INT NOT NULL REFERENCES log (logid),
	steamid64 BIGINT REFERENCES player (steamid64), -- May be NULL for Console messages
	seq INT NOT NULL, -- Message sequence, starting at 0; earlier messages have lower sequences
	msg TEXT NOT NULL,
	PRIMARY KEY (logid, seq)
);

-- Reverse index for lookups by steamid64
-- Don't index NULLs since we don't generally want to look them up.
--CREATE INDEX IF NOT EXISTS chat_steamid64 ON chat (steamid64, logid) WHERE steamid64 NOTNULL;
