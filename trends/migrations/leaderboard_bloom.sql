BEGIN;

DROP MATERIALIZED VIEW leaderboard_cube;
CREATE MATERIALIZED VIEW leaderboard_cube AS SELECT
	playerid,
	league,
	formatid,
	primary_classid AS classid,
	mapid,
	grouping(playerid, league, formatid, primary_classid, mapid) AS grouping,
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
GROUP BY CUBE (playerid, league, formatid, classid, mapid)
ORDER BY mapid, classid, formatid, playerid, league;

-- To help out the query planner
CREATE STATISTICS IF NOT EXISTS leaderboard_stats (dependencies, ndistinct, mcv)
	ON league, formatid, classid, mapid, grouping
	FROM leaderboard_cube;

-- When we have no filters (or nothing better)
CREATE INDEX IF NOT EXISTS leaderboard_grouping ON leaderboard_cube (grouping);

-- When we have a single filter
CREATE INDEX IF NOT EXISTS leaderboard_league ON leaderboard_cube (league)
	WHERE playerid NOTNULL
		AND league NOTNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid ISNULL
		AND grouping = b'01110'::INT;
CREATE INDEX IF NOT EXISTS leaderboard_format ON leaderboard_cube (formatid)
	WHERE playerid NOTNULL
		AND league ISNULL
		AND formatid NOTNULL
		AND classid ISNULL
		AND mapid ISNULL
		AND grouping = b'01101'::INT;
CREATE INDEX IF NOT EXISTS leaderboard_class ON leaderboard_cube (classid)
	WHERE playerid NOTNULL
		AND league ISNULL
		AND formatid ISNULL
		AND classid NOTNULL
		AND mapid ISNULL
		AND grouping = b'01011'::INT;
CREATE INDEX IF NOT EXISTS leaderboard_map ON leaderboard_cube (mapid)
	WHERE playerid NOTNULL
		AND league ISNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid NOTNULL
		AND grouping = b'00111'::INT;

-- When we have multiple filters
CREATE INDEX IF NOT EXISTS leaderboard_bloom ON leaderboard_cube
	USING bloom (grouping, mapid, classid, formatid, league)
	WITH (col1=1, col2=1, col3=1, col4=1, col5=1)
	WHERE playerid NOTNULL;

COMMIT;

ANALYZE VERBOSE leaderboard_cube;
