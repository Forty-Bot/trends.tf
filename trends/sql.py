# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import os
import sys

import psycopg2, psycopg2.extras

from .steamid import SteamID

def db_connect(url, name=None, cursor_factory=None):
    """Setup a database connection

    :param str url: Database to connect to
    :return: A database connection
    :rtype: sqlite.Connection
    """

    psycopg2.extensions.register_adapter(SteamID, psycopg2.extensions.AsIs)
    psycopg2.extensions.set_wait_callback(psycopg2.extras.wait_select)
    c = psycopg2.connect(url, cursor_factory=cursor_factory or psycopg2.extras.DictCursor,
                         application_name=name or " ".join(sys.argv))
    return c

def db_init(c):
    with open("{}/schema.sql".format(os.path.dirname(__file__))) as schema:
        c.cursor().execute(schema.read())

def table_columns(c, table):
    cur = c.cursor()
    cur.execute("""SELECT
                       column_name
                   FROM information_schema.columns
                   WHERE table_catalog = current_catalog
                       AND table_schema = current_schema
                       AND table_name = %s;""", (table,))
    return (row[0] for row in cur)
