-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

-- Rows will tend to be approximately clustered by logid, as import.py usually
-- works chronologically. So we need to re-cluster tables which use a primary
-- key where steamid64 comes before logid.

CLUSTER VERBOSE player_stats USING player_stats_pkey;
CLUSTER VERBOSE player_stats_extra USING player_stats_extra_pkey;
CLUSTER VERBOSE medic_stats USING medic_stats_pkey;
CLUSTER VERBOSE class_stats USING class_stats_pkey;
CLUSTER VERBOSE weapon_stats USING weapon_stats_pkey;
CLUSTER VERBOSE event_stats USING event_stats_pkey;

VACUUM FULL VERBOSE ANALYZE;
