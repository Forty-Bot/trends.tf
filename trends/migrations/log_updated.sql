BEGIN;
ALTER TABLE log ADD updated BIGINT;
CREATE TABLE new AS SELECT
	logid,
	greatest(log.time, demo.time, match.fetched) AS updated
FROM log
LEFT JOIN demo USING (demoid)
LEFT JOIN match USING (league, matchid);
UPDATE log SET
	updated = new.updated
FROM new
WHERE log.logid = new.logid;
ALTER TABLE log ALTER updated SET NOT NULL;
ALTER TABLE log ADD CHECK (updated >= time);
CREATE INDEX log_updated ON log (updated);
COMMIT;
VACUUM VERBOSE ANALYZE log;
