BEGIN;

CREATE TEMP TABLE new_durations AS
WITH bad_log AS (SELECT DISTINCT logid
	FROM log
	LEFT JOIN round USING (logid)
	WHERE log.duration < 0 OR round.duration < 0
) SELECT
	logid,
	coalesce(CASE WHEN log.duration + negative >= 0
		 THEN log.duration + negative END,
		 positive, 0) AS duration
FROM log
JOIN (SELECT
		logid,
		sum(CASE WHEN round.duration >= 0 THEN round.duration END) AS positive,
		sum(CASE WHEN round.duration < 0 THEN -round.duration END) AS negative
	FROM round
	JOIN bad_log USING (logid)
	GROUP BY logid
) AS round USING (logid);

CREATE TEMP TABLE new_class_durations AS
SELECT
	logid,
	playerid,
	classid,
	new.duration
FROM class_stats AS cs
JOIN log USING (logid)
JOIN new_durations AS new USING (logid)
WHERE cs.duration = log.duration;

INSERT INTO new_class_durations SELECT
	logid,
	playerid,
	classid,
	0
FROM class_stats AS cs
WHERE duration < 0;

UPDATE class_stats SET
	duration = new.duration
FROM new_durations AS new, log AS old
WHERE class_stats.logid = new.logid
	AND class_stats.logid = old.logid
	AND class_stats.duration = old.duration;

UPDATE class_stats SET
	duration = 0
WHERE duration < 0;

UPDATE log SET
	duration = new.duration
FROM new_durations AS new
WHERE log.logid = new.logid;

DELETE FROM round WHERE round.duration <= 0;
ALTER TABLE round ADD CHECK (duration > 0);
ALTER TABLE log ADD CHECK (duration >= 0);

UPDATE class_stats AS cs SET
	duration = new.duration
FROM new_class_durations AS new
WHERE cs.logid = new.logid AND cs.playerid = new.playerid AND cs.classid = new.classid;

ALTER TABLE class_stats ADD CHECK (duration >= 0);

CREATE TEMP TABLE new_player_stats AS
SELECT
	logid,
	playerid,
	array_agg(classid ORDER BY duration DESC) AS classids,
	array_agg(duration ORDER BY duration DESC) AS durations
FROM class_stats
JOIN (SELECT
		logid,
		playerid
	FROM new_class_durations
	GROUP BY logid, playerid
) AS new USING (logid, playerid)
GROUP BY logid, playerid
ORDER BY playerid, logid;

UPDATE player_stats_backing AS ps SET
	classids = new.classids,
	class_durations = new.durations
FROM new_player_stats AS new
WHERE ps.logid = new.logid
	AND ps.playerid = new.playerid;

COMMIT;
