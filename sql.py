# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask
import os
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
    c.execute("PRAGMA foreign_keys = TRUE;")
    c.execute("PRAGMA temp_store = MEMORY;")
    return c

def db_init(c):
    with open("{}/schema.sql".format(os.path.dirname(__file__))) as schema:
        c.execute("PRAGMA journal_mode = WAL;")
        c.execute("PRAGMA synchronous = NORMAL;")
        c.execute("PRAGMA auto_vacuum = FULL;")
        c.executescript(schema.read())

def get_db():
    if not getattr(flask.g, 'db_conn', None):
        flask.g.db_conn = db_connect(flask.current_app.config['DATABASE'])
    return flask.g.db_conn

def put_db(exception):
    db = getattr(flask.g, 'db_conn', None)
    if db:
        db.close()
