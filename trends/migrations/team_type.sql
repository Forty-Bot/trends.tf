BEGIN;
CREATE TYPE TEAM_TYPE AS ENUM ('Red', 'Blue');

ALTER TABLE round DROP CONSTRAINT round_winner_fkey, DROP CONSTRAINT round_firstcap_fkey;
ALTER TABLE round ALTER winner TYPE TEAM_TYPE USING (CASE winner WHEN 1 THEN 'Red'::TEAM_TYPE ELSE 'Blue'::TEAM_TYPE END);
ALTER TABLE round ALTER firstcap TYPE TEAM_TYPE USING (CASE firstcap WHEN 1 THEN 'Red'::TEAM_TYPE ELSE 'Blue'::TEAM_TYPE END);

DROP INDEX player_stats_peers;
DROP VIEW player_stats;
ALTER TABLE player_stats_backing DROP CONSTRAINT player_stats_teamid_fkey;
ALTER TABLE player_stats_backing ALTER teamid TYPE TEAM_TYPE
	USING (CASE teamid WHEN 1 THEN 'Red'::TEAM_TYPE ELSE 'Blue'::TEAM_TYPE END);
ALTER TABLE player_stats_backing RENAME teamid TO team;
CREATE INDEX player_stats_peers
	ON player_stats_backing (logid)
	INCLUDE (steamid64, team);
CREATE VIEW player_stats AS SELECT
	player_stats_backing.*,
	CASE WHEN class_durations[1] * 1.5 > array_sum(class_durations)
		THEN classids[1]
	END AS primary_classid,
	(SELECT array_agg(class)
	 FROM unnest(classids) AS classid
	 JOIN class USING (classid)) AS classes,
	(SELECT array_agg(duration * 1.0 / nullif(array_sum(class_durations), 0.0))
	 FROM unnest(class_durations) AS duration) AS class_pct
FROM player_stats_backing;


DROP TABLE team;
ALTER TYPE TEAM_TYPE RENAME TO TEAM;
COMMIT;
