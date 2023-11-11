BEGIN;
CREATE TEMP TABLE linked AS
SELECT
	logid,
	demo.demoid
FROM log
JOIN (SELECT
		logid,
		array_agg(playerid) AS players
	FROM player_stats
	GROUP BY logid
) AS log_players USING (logid)
CROSS JOIN demo
WHERE (log_players.players @> demo.players
		OR demo.players @> log_players.players)
	AND demo.time BETWEEN log.time - 300 AND log.time + 300
	AND log_players.players NOTNULL
	AND demo.players NOTNULL
	AND log.demoid ISNULL;
UPDATE log
SET demoid = linked.demoid
FROM linked
WHERE log.logid = linked.logid;
COMMIT;
