# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import os
import sys

import psycopg2, psycopg2.extras

from .steamid import SteamID

try:
    from sentry_sdk import Hub, tracing_utils

    class TracingCursor(psycopg2.extras.DictCursor):
        def _log(self, query, vars, paramstyle=psycopg2.paramstyle):
            return tracing_utils.record_sql_queries(Hub.current, self, query, vars,
                                                    paramstyle, False)

        def execute(self, query, vars=None):
            with self._log(query, vars):
                super().execute(query, vars)

        def callproc(self, procname, vars=None):
            with self._log(procname, vars, paramstyle=None):
                super().callproc(procname, vars)

except ImportError:
    TracingCursor=psycopg2.extras.DictCursor

def db_connect(url, name=None):
    """Setup a database connection

    :param str url: Database to connect to
    :return: A database connection
    :rtype: sqlite.Connection
    """

    psycopg2.extensions.register_adapter(SteamID, psycopg2.extensions.AsIs)
    psycopg2.extensions.set_wait_callback(psycopg2.extras.wait_select)
    c = psycopg2.connect(url, cursor_factory=TracingCursor,
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
