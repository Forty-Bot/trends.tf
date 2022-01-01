CREATE INDEX CONCURRENTLY player_stats_names2 ON player_stats (nameid) INCLUDE (steamid64);
BEGIN;
DROP INDEX player_stats_names;
ALTER INDEX player_stats_names2 RENAME TO player_stats_names;
COMMIT;
