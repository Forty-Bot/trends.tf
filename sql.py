# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import sqlite3
from steamid import SteamID

def db_connect(url):
    """Setup a database connection

    :param str url: Database to connect to
    :return: A database connection
    :rtype: sqlite.Connection
    """

    sqlite3.register_adapter(SteamID, str)
    c = sqlite3.connect(url, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = TRUE");
    return c
