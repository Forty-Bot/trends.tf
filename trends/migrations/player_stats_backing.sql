-- depends player_stats_classes.py

BEGIN;
CREATE FUNCTION array_sum(anyarray) RETURNS anyelement
	AS 'SELECT sum(val) FROM unnest($1) AS val'
	LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE;
ALTER TABLE player_stats RENAME TO player_stats_backing;
ALTER TABLE player_stats_backing DROP primary_classid;
CREATE VIEW player_stats AS SELECT
	player_stats_backing.*,
	CASE WHEN class_durations[1] * 1.5 > array_sum(class_durations)
		THEN classids[1]
	END AS primary_classid,
	(SELECT array_agg(class)
	 FROM unnest(classids) AS classid
	 JOIN class USING (classid)) AS classes,
	(SELECT array_agg(duration * 1.0 / array_sum(class_durations))
	 FROM unnest(class_durations) AS duration) AS class_pct
FROM player_stats_backing;
COMMIT;
