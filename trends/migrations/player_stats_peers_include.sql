CREATE INDEX CONCURRENTLY player_stats_peers2 ON player_stats (logid) INCLUDE (steamid64, teamid);
BEGIN;
DROP INDEX player_stats_peers;
ALTER INDEX player_stats_peers2 RENAME TO player_stats_peers;
COMMIT;
