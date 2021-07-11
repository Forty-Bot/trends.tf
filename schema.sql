-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

-- Compatibility functions for migration from SQLite

CREATE OR REPLACE FUNCTION ifnull(anyelement, anyelement) RETURNS anyelement
	AS 'SELECT coalesce($1, $2)'
	LANGUAGE SQL IMMUTABLE PARALLEL SAFE;

CREATE OR REPLACE FUNCTION add(FLOAT, anyelement) RETURNS FLOAT
	AS 'SELECT $1 + $2'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;

CREATE OR REPLACE AGGREGATE total(anyelement) (
	SFUNC = add,
	STYPE = FLOAT,
	INITCOND = 0.0,
	PARALLEL = SAFE
);

CREATE OR REPLACE FUNCTION concat(TEXT, anyelement) RETURNS TEXT
	AS 'SELECT coalesce($1 || '','' || $2, $1, $2)'
	LANGUAGE SQL IMMUTABLE PARALLEL SAFE;

CREATE OR REPLACE AGGREGATE group_concat(anyelement) (
	SFUNC = concat,
	STYPE = TEXT,
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

CREATE TABLE IF NOT EXISTS log (
	logid INTEGER PRIMARY KEY, -- SQLite won't infer a rowid alias unless the type is INTEGER
	time BIGINT NOT NULL, -- End time
	duration INT NOT NULL,
	title TEXT NOT NULL,
	mapid INT NOT NULL REFERENCES map (mapid),
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	formatid INT REFERENCES format (formatid),
	-- Some logs may be duplicates or subsets of another log
	duplicate_of INT REFERENCES log (logid),
	-- All duplicates must be earlier (and have smaller logids) than what they are duplicates of
	-- This prevents cycles (though it does admit chains of finite length)
	CHECK (logid < duplicate_of)
);

CREATE INDEX IF NOT EXISTS log_time ON log (time);

-- Helper index for doing reverse lookups on duplicate_of (e.g. for deletes)
CREATE INDEX IF NOT EXISTS log_duplicates ON log (duplicate_of);

CREATE TABLE IF NOT EXISTS team (
	teamid SERIAL PRIMARY KEY,
	team TEXT NOT NULL UNIQUE
);

INSERT INTO team (team) VALUES ('Red'), ('Blue') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS round (
	logid INT NOT NULL REFERENCES log (logid),
	seq INT NOT NULL, -- Round number, starting at 0
	time BIGINT, -- Unix time
	duration INT NOT NULL,
	winner INT REFERENCES team (teamid),
	firstcap INT REFERENCES team (teamid),
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

CREATE TABLE IF NOT EXISTS name (
	nameid SERIAL PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS name_fts ON name USING GIN (to_tsvector('english', name));

CREATE TABLE IF NOT EXISTS player (
	steamid64 BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS player_stats (
	logid INT REFERENCES log (logid) NOT NULL,
	steamid64 BIGINT REFERENCES player (steamid64) NOT NULL,
	nameid INT NOT NULL REFERENCES name (nameid),
	teamid INT REFERENCES team (teamid), -- May be NULL for spectators
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	dt INT,
	PRIMARY KEY (steamid64, logid)
);

-- This index includes steamid64 and team so that it can be used as a covering index for the peers
-- query. This avoids a bunch of costly random reads to player_stats.
CREATE INDEX IF NOT EXISTS player_stats_peers ON player_stats (logid, steamid64, teamid);

-- Covering index for name FTS queries
CREATE INDEX IF NOT EXISTS player_stats_names ON player_stats (nameid, steamid64);

CREATE OR REPLACE VIEW player_last AS
SELECT
	logid,
	p.steamid64,
	nameid
FROM player AS p
CROSS JOIN LATERAL (SELECT
		logid,
		nameid
	FROM player_stats AS ps
	WHERE ps.steamid64 = p.steamid64
	ORDER BY logid DESC
	LIMIT 1
) AS last;

CREATE OR REPLACE VIEW log_wlt AS
SELECT
	time,
	duration,
	title,
	mapid,
	red_score,
	blue_score,
	formatid,
	duplicate_of,
	round.*
FROM log
JOIN (SELECT
		ps.*,
		ifnull(sum((ps.teamid = round.winner)::INT), 0::BIGINT) AS round_wins,
		ifnull(sum((ps.teamid != round.winner)::INT), 0::BIGINT) AS round_losses,
		sum((round.winner ISNULL AND round.duration >= 60)::INT) AS round_ties
	FROM round
	JOIN player_stats AS ps USING (logid)
	GROUP BY ps.logid, steamid64
) AS round USING (logid);

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
	healing INT NOT NULL,
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

-- Reverse lookup index for deletes in player_stats
CREATE INDEX IF NOT EXISTS heal_stats_healee ON heal_stats (logid, healee);

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

CREATE TABLE IF NOT EXISTS weapon (
	weaponid SERIAL PRIMARY KEY,
	weapon TEXT NOT NULL UNIQUE
);

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

CREATE TABLE IF NOT EXISTS chat (
	logid INT NOT NULL,
	steamid64 BIGINT, -- May be NULL for Console messages
	seq INT NOT NULL, -- Message sequence, starting at 0; earlier messages have lower sequences
	msg TEXT NOT NULL,
	PRIMARY KEY (logid, seq),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
);

-- Reverse index for lookups by steamid64
CREATE INDEX IF NOT EXISTS chat_steamid64 ON chat (steamid64, logid);
