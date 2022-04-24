BEGIN;

ALTER TABLE round ADD time BIGINT;
ALTER TABLE round ADD firstcap INT REFERENCES team (teamid);
ALTER TABLE round ADD red_score INT;
ALTER TABLE round ADD blue_score INT;
ALTER TABLE round ADD red_kills INT;
ALTER TABLE round ADD blue_kills INT;
ALTER TABLE round ADD red_dmg INT;
ALTER TABLE round ADD blue_dmg INT;
ALTER TABLE round ADD red_ubers INT;
ALTER TABLE round ADD blue_ubers INT;

UPDATE round
SET
	time = round_extra.time,
	firstcap = round_extra.firstcap,
	red_score = round_extra.red_score,
	blue_score = round_extra.blue_score,
	red_kills = round_extra.red_kills,
	blue_kills = round_extra.blue_kills,
	red_dmg = round_extra.red_dmg,
	blue_dmg = round_extra.blue_dmg,
	red_ubers = round_extra.red_ubers,
	blue_ubers = round_extra.blue_ubers
FROM round_extra
WHERE round.logid = round_extra.logid
	AND round.seq = round_extra.seq;

ALTER TABLE round ALTER red_score SET NOT NULL;
ALTER TABLE round ALTER blue_score SET NOT NULL;
ALTER TABLE round ALTER red_kills SET NOT NULL;
ALTER TABLE round ALTER blue_kills SET NOT NULL;
ALTER TABLE round ALTER red_dmg SET NOT NULL;
ALTER TABLE round ALTER blue_dmg SET NOT NULL;
ALTER TABLE round ALTER red_ubers SET NOT NULL;
ALTER TABLE round ALTER blue_ubers SET NOT NULL;

DROP TABLE round_extra;
COMMIT;

VACUUM FULL VERBOSE ANALYZE round;
