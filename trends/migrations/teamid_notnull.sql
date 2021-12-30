-- depends chat_fk_split.sql

BEGIN;
CREATE TEMP TABLE to_delete ON COMMIT DROP AS
	SELECT logid, steamid64 FROM player_stats WHERE teamid ISNULL FOR UPDATE;
DELETE FROM weapon_stats WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM class_stats WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM event_stats WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM medic_stats WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM heal_stats WHERE (logid, healer) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM heal_stats WHERE (logid, healee) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM player_stats_extra WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
DELETE FROM player_stats WHERE (logid, steamid64) IN (SELECT logid, steamid64 FROM to_delete);
ALTER TABLE player_stats ALTER teamid SET NOT NULL;
COMMIT;
