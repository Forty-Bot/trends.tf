-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

ALTER TABLE player ADD eu_playerid INT UNIQUE;
ALTER TABLE log ADD league LEAGUE;
ALTER TABLE log ADD matchid INT;
ALTER TABLE log ADD team1_is_red BOOL;
ALTER TABLE log ADD FOREIGN KEY (league, matchid) REFERENCES match (league, matchid);
ALTER TABLE log ADD CHECK (equal(league ISNULL, matchid ISNULL, team1_is_red ISNULL));
CREATE INDEX IF NOT EXISTS log_match ON log (league, matchid);
