BEGIN;
UPDATE log
SET demoid = linked.demoid
FROM (
	SELECT logid, demo.demoid
	FROM log
	JOIN (
		SELECT logid, array_agg(steamid64) AS players
        	FROM player_stats
        	GROUP BY logid
	) AS log_players USING (logid)
	CROSS JOIN demo
	JOIN (
		SELECT demoid, array_agg(steamid64) AS players
        	FROM (
			SELECT demoid, steamid64
			FROM demo, unnest(demo.players) AS steamid64
		) AS demo_player
        	GROUP BY demoid
	) AS demo_players ON (demo_players.demoid=demo.demoid)
	WHERE (log_players.players @> demo_players.players
			OR demo_players.players @> log_players.players)
		AND log.time BETWEEN demo.time - 300 AND demo.time + 300
) AS linked
WHERE log.logid = linked.logid
	AND log.demoid ISNULL;
COMMIT;
