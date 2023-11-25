BEGIN;
ALTER TABLE competition
ADD scheduled_from BIGINT,
ADD scheduled_to BIGINT,
ADD CHECK (equal(scheduled_from ISNULL, scheduled_to ISNULL));
CREATE TEMP TABLE new AS SELECT
	league,
	compid,
	min(scheduled) AS scheduled_from,
	max(scheduled) AS scheduled_to
FROM match
GROUP BY league, compid;
UPDATE competition AS comp
SET
	scheduled_from = new.scheduled_from,
	scheduled_to = new.scheduled_to
FROM new
WHERE comp.league = new.league AND comp.compid = new.compid;
COMMIT;
