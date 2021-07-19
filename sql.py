# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask
import os
import psycopg2, psycopg2.extras
import psycopg2.extensions

from steamid import SteamID

def db_connect(url):
    """Setup a database connection

    :param str url: Database to connect to
    :return: A database connection
    :rtype: sqlite.Connection
    """

    psycopg2.extensions.register_adapter(SteamID, psycopg2.extensions.AsIs)
    c = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
    return c

def db_init(c):
    with open("{}/schema.sql".format(os.path.dirname(__file__))) as schema:
        c.cursor().execute(schema.read())

def get_db():
    if not getattr(flask.g, 'db_conn', None):
        flask.g.db_conn = db_connect(flask.current_app.config['DATABASE'])
    return flask.g.db_conn

def put_db(exception):
    db = getattr(flask.g, 'db_conn', None)
    if db:
        db.close()
