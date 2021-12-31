BEGIN;
DROP INDEX player_stats_names;
CREATE INDEX player_stats_names ON player_stats (nameid) INCLUDE (steamid64);
COMMIT;
