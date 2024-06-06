BEGIN;
ALTER TABLE player_stats_extra ADD mks INT;
CREATE TEMP TABLE new AS
SELECT
	logid,
	playerid,
	max(kills) AS mks
FROM killstreak
GROUP BY logid, playerid
ORDER BY playerid, logid;
-- Force a merge join
SET enable_hashjoin = FALSE;
UPDATE player_stats_extra AS pse SET
	mks = new.mks
FROM new
WHERE pse.logid = new.logid
	AND pse.playerid = new.playerid;
SET enable_hashjoin = FALSE;
COMMIT;
