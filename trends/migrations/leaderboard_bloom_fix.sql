BEGIN;
DROP INDEX leaderboard_league;
DROP INDEX leaderboard_format;
DROP INDEX leaderboard_class;
CREATE INDEX leaderboard_league ON leaderboard_cube (league)
	WHERE playerid NOTNULL
		AND league NOTNULL
		AND formatid ISNULL
		AND classid ISNULL
		AND mapid ISNULL
		AND grouping = b'00111'::INT;
CREATE INDEX leaderboard_format ON leaderboard_cube (formatid)
	WHERE playerid NOTNULL
		AND league ISNULL
		AND formatid NOTNULL
		AND classid ISNULL
		AND mapid ISNULL
		AND grouping = b'01011'::INT;
CREATE INDEX leaderboard_class ON leaderboard_cube (classid)
	WHERE playerid NOTNULL
		AND league ISNULL
		AND formatid ISNULL
		AND classid NOTNULL
		AND mapid ISNULL
		AND grouping = b'01101'::INT;
COMMIT;
ANALYZE VERBOSE leaderboard_cube;
