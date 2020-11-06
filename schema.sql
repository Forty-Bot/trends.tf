-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

BEGIN;

CREATE TABLE IF NOT EXISTS team (
	name TEXT PRIMARY KEY
) WITHOUT ROWID;

INSERT OR IGNORE INTO team (name) VALUES ('Red'), ('Blue');

CREATE TABLE IF NOT EXISTS log (
	logid INTEGER PRIMARY KEY, -- SQLite won't infer a rowid alias unless the type is INTEGER
	time INT NOT NULL, -- End time
	duration INT NOT NULL,
	title TEXT NOT NULL,
	map TEXT NOT NULL,
	red_score INT NOT NULL,
	blue_score INT NOT NULL,
	final_round_stalemate BOOLEAN NOT NULL,
	final_round_duration INT NOT NULL,
	CHECK (final_round_stalemate IN (TRUE, FALSE)),
	CHECK (final_round_duration <= duration)
);

CREATE INDEX IF NOT EXISTS log_time ON log (time);
CREATE INDEX IF NOT EXISTS log_map ON log (map);

CREATE TABLE IF NOT EXISTS player_stats (
	logid INT REFERENCES log (logid),
	steamid64 INT,
	name TEXT NOT NULL,
	team TEXT REFERENCES team (name), -- May be NULL for spectators
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	suicides INT,
	dmg INT NOT NULL,
	dmg_real INT, -- Damage dealt just before/after a kill, cap, or uber
	dt INT,
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
	PRIMARY KEY (logid, steamid64),
	CHECK ((dmg_real NOTNULL AND dt_real NOTNULL) OR (dmg_real ISNULL AND dt_real ISNULL))
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS player_stats_id ON player_stats (steamid64);

CREATE TABLE IF NOT EXISTS medic_stats (
	logid INT,
	steamid64 INT,
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
	PRIMARY KEY (logid, steamid64),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64),
	CHECK ((medigun_ubers ISNULL AND kritz_ubers ISNULL AND other_ubers ISNULL) OR
	       (medigun_ubers NOTNULL AND kritz_ubers NOTNULL AND other_ubers NOTNULL)),
	CHECK (medigun_ubers ISNULL OR ubers == medigun_ubers + kritz_ubers + other_ubers),
	CHECK ((advantages_lost NOTNULL AND biggest_advantage_lost NOTNULL) OR
	       (advantages_lost ISNULL AND biggest_advantage_lost ISNULL))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS heal_stats (
	logid INT,
	healer INT,
	healee INT,
	healing INT NOT NULL,
	PRIMARY KEY (logid, healer, healee),
	-- Should reference medic_stats, but some very old logs only report one class per player
	FOREIGN KEY (logid, healer) REFERENCES player_stats (logid, steamid64),
	FOREIGN KEY (logid, healee) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS class (
	name TEXT PRIMARY KEY
) WITHOUT ROWID;

INSERT OR IGNORE INTO class (name) VALUES
	('demoman'),
	('engineer'),
	('heavyweapons'),
	('medic'),
	('pyro'),
	('scout'),
	('sniper'),
	('soldier'),
	('spy');

CREATE TABLE IF NOT EXISTS class_stats (
	logid INT,
	steamid64 INT,
	class TEXT NOT NULL REFERENCES class (name),
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	duration INT NOT NULL,
	PRIMARY KEY (logid, steamid64, class),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS weapon_stats (
	logid INT,
	steamid64 INT,
	class TEXT,
	weapon TEXT,
	kills INT NOT NULL,
	dmg INT,
	avg_dmg REAL,
	shots INT,
	hits INT,
	PRIMARY KEY (logid, steamid64, class, weapon),
	FOREIGN KEY (logid, steamid64, class) REFERENCES class_stats (logid, steamid64, class),
	CHECK ((shots NOTNULL AND hits NOTNULL) OR (shots ISNULL AND hits ISNULL))
	CHECK ((dmg NOTNULL AND avg_dmg NOTNULL) OR (dmg ISNULL AND avg_dmg ISNULL))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat (
	logid INT NOT NULL,
	steamid64 INT, -- May be NULL for Console messages
	seq INT NOT NULL, -- Message sequence, starting at 0; earlier messages have lower sequences
	msg TEXT NOT NULL,
	PRIMARY KEY (logid, seq),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;

-- CREATE INDEX IF NOT EXISTS chat_player ON chat (steamid64);

COMMIT;
