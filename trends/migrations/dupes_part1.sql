-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

BEGIN;

ALTER TABLE log ADD new_duplicate_of INT[]
	CHECK (new_duplicate_of = uniq(sort(new_duplicate_of)));
ALTER TABLE log ADD CHECK (logid > new_duplicate_of[#new_duplicate_of]);

CREATE TEMP TABLE dupes AS SELECT
    r2.logid AS logid,
    array_agg(DISTINCT r1.logid) AS of
FROM round AS r1
JOIN round AS r2 USING (time, duration) WHERE r2.logid > r1.logid
GROUP BY r2.logid;

UPDATE log
SET new_duplicate_of = dupes.of
FROM dupes
WHERE log.logid=dupes.logid;

CREATE INDEX IF NOT EXISTS new_log_nodups_pkey ON log (logid)
	WHERE new_duplicate_of ISNULL;

COMMIT;
