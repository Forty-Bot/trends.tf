-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

BEGIN;

CREATE OR REPLACE VIEW log_nodups AS SELECT
	logid,
	time,
	duration,
	title,
	mapid,
	red_score,
	blue_score,
	formatid
FROM log
WHERE new_duplicate_of ISNULL;

ALTER TABLE log DROP CONSTRAINT log_check;
ALTER TABLE log DROP duplicate_of;
ALTER TABLE log RENAME new_duplicate_of TO duplicate_of;
ALTER INDEX new_log_nodups_pkey RENAME TO log_nodups_pkey;

COMMIT;
