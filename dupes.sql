-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>
-- This sets ALL duplicates

BEGIN;

CREATE TEMP TABLE dupes AS
SELECT
	r1.logid AS logid,
	max(r2.logid) AS of
FROM round AS r1
JOIN round AS r2 USING (
	time, duration, firstcap, red_score, blue_score, red_kills, blue_kills, red_dmg, blue_dmg,
	red_ubers, blue_ubers
) WHERE r2.logid > r1.logid
GROUP BY r1.logid;

UPDATE log
SET duplicate_of=dupes.of
FROM dupes
WHERE log.logid=dupes.logid;

COMMIT;
