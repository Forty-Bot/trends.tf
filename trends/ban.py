# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import logging
import sys

from .steamid import SteamID
from .sql import db_connect, delete_logs
from .importer.cli import init_logging

def ban_player(steamid, reason, database):
    init_logging(logging.INFO)
    with db_connect(database) as c:
        cur = c.cursor()
        cur.execute("BEGIN;")
        cur.execute("UPDATE player SET banned = TRUE, ban_reason = %s WHERE steamid64 = %s",
                    (reason, steamid))
        cur.execute("CREATE TEMP TABLE to_delete AS SELECT logid FROM log WHERE uploader = %s;",
                    (steamid,))
        delete_logs(cur)
        cur.execute("COMMIT;")

if __name__ == "__main__":
    ban_player(SteamID(sys.argv[1]), sys.argv[2], sys.argv[3])
