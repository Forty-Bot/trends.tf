BEGIN;
DROP MATERIALIZED VIEW medic_cube;
CREATE MATERIALIZED VIEW medic_cube AS SELECT
	playerid,
	league,
	formatid,
	mapid,
	grouping(league, formatid, mapid) AS grouping,
	count(*) AS logs,
	sum(duration) AS duration,
	sum(ubers) AS ubers,
	sum(medigun_ubers) AS medigun_ubers,
	sum(kritz_ubers) AS kritz_ubers,
	sum(other_ubers) AS other_ubers,
	sum(drops) AS drops,
	sum(advantages_lost) AS advantages_lost,
	sum(avg_time_before_using * ubers) AS time_before_using,
	sum(nullelse(avg_time_before_using, ubers)) AS ubers_before_using,
	sum(avg_time_to_build * (ubers + drops)) AS time_to_build,
	sum(nullelse(avg_time_to_build, ubers + drops)) AS builds,
	sum(avg_uber_duration * ubers) AS uber_duration,
	sum(nullelse(avg_uber_duration, ubers)) AS ubers_duration,
	sum(nullelse(healing, duration)) AS healing_duration,
	sum(healing) AS healing,
	sum(healing_scout) AS healing_scout,
	sum(healing_soldier) AS healing_soldier,
	sum(healing_pyro) AS healing_pyro,
	sum(healing_demoman) AS healing_demoman,
	sum(healing_engineer) AS healing_engineer,
	sum(healing_heavyweapons) AS healing_heavyweapons,
	sum(healing_medic) AS healing_medic,
	sum(healing_sniper) AS healing_sniper,
	sum(healing_spy) AS healing_spy,
	sum(healing_enemy) AS healing_enemy,
	sum(healing_other) AS healing_other
FROM log_nodups AS log
JOIN medic_stats USING (logid)
LEFT JOIN (SELECT
		logid,
		healer AS playerid,
		sum(healing) AS healing,
		sum(CASE WHEN healer = healee THEN healing END) AS healing_self,
		sum(CASE WHEN class = 'scout' THEN healing END) AS healing_scout,
		sum(CASE WHEN class = 'soldier' THEN healing END) AS healing_soldier,
		sum(CASE WHEN class = 'pyro' THEN healing END) AS healing_pyro,
		sum(CASE WHEN class = 'demoman' THEN healing END) AS healing_demoman,
		sum(CASE WHEN class = 'engineer' THEN healing END) AS healing_engineer,
		sum(CASE WHEN class = 'heavyweapons' THEN healing END) AS healing_heavyweapons,
		sum(CASE WHEN class = 'medic' THEN healing END) AS healing_medic,
		sum(CASE WHEN class = 'sniper' THEN healing END) AS healing_sniper,
		sum(CASE WHEN class = 'spy' THEN healing END) AS healing_spy,
		sum(CASE WHEN healer_stats.team != healee_stats.team THEN healing END)
			AS healing_enemy,
		sum(CASE WHEN class ISNULL THEN healing END) AS healing_other
	FROM heal_stats
	JOIN player_stats AS healer_stats USING (logid)
	JOIN player_stats AS healee_stats USING (logid)
	LEFT JOIN class ON (classid=healee_stats.primary_classid)
	WHERE healer_stats.playerid = healer
		AND healee_stats.playerid = healee
	GROUP BY logid, healer
) AS heal_stats USING (logid, playerid)
GROUP BY playerid, CUBE (league, formatid, mapid)
ORDER BY mapid, formatid, playerid, league
WITH NO DATA;
CREATE STATISTICS medic_cube_stats (dependencies, ndistinct, mcv)
	ON league, formatid, mapid, grouping
	FROM medic_cube;
CREATE INDEX medic_grouping ON medic_cube (grouping);
CREATE INDEX medic_league ON medic_cube (league)
	WHERE grouping = b'011'::INT
		AND league NOTNULL
		AND formatid ISNULL
		AND mapid ISNULL;
CREATE INDEX medic_format ON medic_cube (formatid)
	WHERE grouping = b'101'::INT
		AND league ISNULL
		AND formatid NOTNULL
		AND mapid ISNULL;
CREATE INDEX medic_map ON medic_cube (mapid)
	WHERE grouping = b'110'::INT
		AND league ISNULL
		AND formatid ISNULL
		AND mapid NOTNULL;
CREATE INDEX medic_bloom ON medic_cube
	USING bloom (grouping, mapid, formatid, league)
	WITH (col1=1, col2=1, col3=1, col5=1);
REFRESH MATERIALIZED VIEW medic_cube;
COMMIT;
