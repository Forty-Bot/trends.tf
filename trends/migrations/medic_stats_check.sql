BEGIN;
UPDATE medic_stats SET avg_time_before_healing = NULL WHERE avg_time_before_healing <= 0;
UPDATE medic_stats SET avg_time_before_using = NULL WHERE avg_time_before_using <= 0;
UPDATE medic_stats SET avg_time_to_build = NULL WHERE avg_time_to_build <= 0;
UPDATE medic_stats SET avg_uber_duration = NULL
	WHERE avg_uber_duration <= 0 OR avg_uber_duration > 8;
ALTER TABLE medic_stats
	ADD CONSTRAINT medic_stats_avg_time_before_healing_check
		CHECK (avg_time_before_healing > 0),
	ADD CONSTRAINT medic_stats_avg_time_before_using_check
		CHECK (avg_time_before_using > 0),
	ADD CONSTRAINT medic_stats_avg_time_to_build_check
		CHECK (avg_time_to_build > 0),
	ADD CONSTRAINT medic_stats_avg_uber_duration_check
		CHECK (avg_uber_duration > 0 AND avg_uber_duration <= 8);
COMMIT;
