BEGIN;
DROP MATERIALIZED VIEW leaderboard_cube;

CREATE MATERIALIZED VIEW leaderboard_cube AS SELECT
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
ORDER BY mapid, classid, formatid, playerid, league;

CREATE STATISTICS leaderboard_stats (dependencies, ndistinct, mcv)
	ON league, formatid, classid, mapid, grouping
	FROM leaderboard_cube;

CREATE INDEX leaderboard_grouping ON leaderboard_cube (grouping);

CREATE INDEX leaderboard_league ON leaderboard_cube (league)
	WHERE grouping = b'0111'::INT
		AND league NOTNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid ISNULL;
CREATE INDEX leaderboard_format ON leaderboard_cube (formatid)
	WHERE grouping = b'1011'::INT
		AND league ISNULL
		AND formatid NOTNULL
		AND classid ISNULL
		AND mapid ISNULL;
CREATE INDEX leaderboard_class ON leaderboard_cube (classid)
	WHERE grouping = b'1101'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND classid NOTNULL
		AND mapid ISNULL;
CREATE INDEX leaderboard_map ON leaderboard_cube (mapid)
	WHERE grouping = b'1110'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid NOTNULL;

-- When we have multiple filters
CREATE INDEX leaderboard_bloom ON leaderboard_cube
	USING bloom (grouping, mapid, classid, formatid, league)
	WITH (col1=1, col2=1, col3=1, col4=1, col5=1);

COMMIT;
ANALYZE VERBOSE leaderboard_cube;
