-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

CREATE TABLE IF NOT EXISTS format (
	formatid INTEGER PRIMARY KEY,
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
	mapid INTEGER PRIMARY KEY,
	map TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS log (
	logid INTEGER PRIMARY KEY, -- SQLite won't infer a rowid alias unless the type is INTEGER
	time INT NOT NULL, -- End time
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

CREATE TABLE IF NOT EXISTS team (
	teamid INTEGER PRIMARY KEY,
	team TEXT NOT NULL UNIQUE
);

INSERT INTO team (team) VALUES ('Red'), ('Blue') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS round (
	logid INT NOT NULL REFERENCES log (logid),
	seq INT NOT NULL, -- Round number, starting at 0
	time INT, -- Unix time
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
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS name (
	nameid INTEGER PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);

-- FTS "index"
CREATE VIRTUAL TABLE IF NOT EXISTS name_fts USING fts5 (name, content=name, content_rowid=nameid);
CREATE TRIGGER IF NOT EXISTS name_insert AFTER INSERT ON name BEGIN
	INSERT INTO name_fts(rowid, name) VALUES (new.nameid, new.name);
END;
CREATE TRIGGER IF NOT EXISTS name_update AFTER UPDATE ON name BEGIN
	INSERT INTO name_fts (name_fts, rowid) VALUES ('delete', old.nameid);
	INSERT INTO name_fts (rowid, name) VALUES (new.nameid, new.name);
END;
CREATE TRIGGER IF NOT EXISTS name_delete AFTER DELETE ON name BEGIN
	INSERT INTO name_fts (name_fts, rowid) VALUES ('delete', old.nameid);
END;

-- Automatically updated via triggers
CREATE TABLE IF NOT EXISTS player (
	steamid64 INTEGER PRIMARY KEY,
	last_logid INT REFERENCES log (logid) NOT NULL, -- Most recent log
	last_nameid INT NOT NULL REFERENCES name (nameid) -- Most recent name
);

CREATE TABLE IF NOT EXISTS player_stats (
	logid INT REFERENCES log (logid) NOT NULL,
	steamid64 INT REFERENCES player (steamid64) NOT NULL,
	nameid INT NOT NULL REFERENCES name (nameid),
	teamid INT REFERENCES team (teamid), -- May be NULL for spectators
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
	PRIMARY KEY (steamid64, logid),
	CHECK ((dmg_real NOTNULL AND dt_real NOTNULL) OR (dmg_real ISNULL AND dt_real ISNULL))
) WITHOUT ROWID;

-- This index includes steamid64 and team so that it can be used as a covering index for the peers
-- query. This avoids a bunch of costly random reads to player_stats.
CREATE INDEX IF NOT EXISTS player_stats_peers ON player_stats (logid, steamid64, teamid);

-- Covering index for name FTS queries
CREATE INDEX IF NOT EXISTS player_stats_names ON player_stats (nameid, steamid64);

CREATE TRIGGER IF NOT EXISTS player_insert BEFORE INSERT ON player_stats BEGIN
	INSERT INTO player (steamid64, last_nameid, last_logid)
	VALUES (new.steamid64, new.nameid, new.logid)
	ON CONFLICT (steamid64) DO
		UPDATE SET
			last_nameid=new.nameid,
			last_logid=new.logid
		WHERE new.logid > last_logid;
END;

CREATE TRIGGER IF NOT EXISTS player_update AFTER UPDATE ON player_stats BEGIN
	UPDATE player SET
		last_nameid=new.nameid,
		last_logid=new.logid
	WHERE old.logid = last_logid;
END;

-- No ON DELETE because idk what to do for that

CREATE VIEW IF NOT EXISTS log_wlt AS
SELECT
	log.*,
	round.*
FROM log
JOIN (SELECT
		ps.*,
		ifnull(sum(ps.teamid = round.winner), 0) AS round_wins,
		ifnull(sum(ps.teamid != round.winner), 0) AS round_losses,
		sum(round.winner ISNULL AND round.duration >= 60) AS round_ties
	FROM round
	JOIN player_stats AS ps USING (logid)
	GROUP BY logid, steamid64
) AS round USING (logid);

CREATE TABLE IF NOT EXISTS medic_stats (
	logid INT NOT NULL,
	steamid64 INT NOT NULL,
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
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS medic_stats_logid ON medic_stats (logid);

CREATE TABLE IF NOT EXISTS heal_stats (
	logid INT NOT NULL,
	healer INT NOT NULL,
	healee INT NOT NULL,
	healing INT NOT NULL,
	PRIMARY KEY (logid, healer, healee),
	-- Should reference medic_stats, but some very old logs only report one class per player
	FOREIGN KEY (logid, healer) REFERENCES player_stats (logid, steamid64),
	FOREIGN KEY (logid, healee) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS class (
	classid INTEGER PRIMARY KEY,
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
	steamid64 INT NOT NULL,
	classid INT NOT NULL REFERENCES class (classid),
	kills INT NOT NULL,
	assists INT NOT NULL,
	deaths INT NOT NULL,
	dmg INT NOT NULL,
	duration INT NOT NULL,
	PRIMARY KEY (steamid64, logid, classid),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS weapon (
	weaponid INTEGER PRIMARY KEY,
	weapon TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS weapon_stats (
	logid INT NOT NULL,
	steamid64 INT NOT NULL,
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
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS event (
	eventid INTEGER PRIMARY KEY,
	event TEXT NOT NULL UNIQUE
);

INSERT INTO event (event) VALUES ('kill'), ('death'), ('assist') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS event_stats (
	logid INT NOT NULL,
	steamid64 INT NOT NULL,
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
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chat (
	logid INT NOT NULL,
	steamid64 INT, -- May be NULL for Console messages
	seq INT NOT NULL, -- Message sequence, starting at 0; earlier messages have lower sequences
	msg TEXT NOT NULL,
	PRIMARY KEY (logid, seq),
	FOREIGN KEY (logid, steamid64) REFERENCES player_stats (logid, steamid64)
) WITHOUT ROWID;
