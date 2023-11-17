ALTER TABLE league_team DROP CONSTRAINT league_team_check;
ALTER TABLE league_team ADD CHECK (
	equal(league_team_per_comp(league), fetched ISNULL, team_nameid ISNULL)
);
ALTER TABLE league_team ALTER team_nameid DROP NOT NULL;
DROP VIEW match_pretty;
DROP VIEW match_wlt;
ALTER TABLE match ALTER score1 TYPE REAL;
ALTER TABLE match ALTER score2 TYPE REAL;
DROP INDEX match_team1;
DROP INDEX match_team2;
DROP INDEX match_comp;
CREATE INDEX match_team1 ON match (teamid1);
CREATE INDEX match_team2 ON match (teamid2);
