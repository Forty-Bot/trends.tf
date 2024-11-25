# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
import logging

def create_refresh_parser(sub):
    link = sub.add_parser("refresh", help="Refresh materialized views")
    link.set_defaults(importer=refresh)

def refresh(args, c, mc):
    with c.cursor() as cur:
        for view in ('leaderboard_cube', 'medic_cube', 'map_popularity'):
            logging.info(f"REFRESH {view}")
            cur.execute("BEGIN;")
            cur.execute("SELECT pg_advisory_xact_lock(%s::REGCLASS::BIGINT);", (view,))
            cur.execute(
                f"""UPDATE materialized_view
                    SET last_updated = now()
                    WHERE oid = %s::REGCLASS;""", (view,))
            cur.execute(f"REFRESH MATERIALIZED VIEW {view}")
            cur.execute("COMMIT;")
