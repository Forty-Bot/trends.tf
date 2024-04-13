BEGIN;
ALTER TABLE team_player
	ALTER CONSTRAINT team_player_league_teamid_fkey DEFERRABLE,
	ALTER CONSTRAINT team_player_league_teamid_compid_fkey DEFERRABLE;
ALTER TABLE match
	ALTER CONSTRAINT match_league_compid_teamid1_fkey DEFERRABLE,
	ALTER CONSTRAINT match_league_compid_teamid2_fkey DEFERRABLE;
COMMIT;
