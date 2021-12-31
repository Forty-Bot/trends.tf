BEGIN;
DROP INDEX player_stats_peers;
CREATE INDEX player_stats_peers ON player_stats (logid) INCLUDE (steamid64, teamid);
COMMIT;
