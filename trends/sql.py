# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import contextlib
import logging
import os
import sys

import psycopg2, psycopg2.extras
from sentry_sdk import Hub, tracing_utils

from .steamid import SteamID

tracing_disabled = False

@contextlib.contextmanager
def disable_tracing():
    global tracing_disabled
    tracing_disabled = True
    yield
    tracing_disabled = False

class TracingCursor(psycopg2.extras.DictCursor):
    def _log(self, query, vars, paramstyle=psycopg2.paramstyle):
        if tracing_disabled:
            return contextlib.nullcontext()
        return tracing_utils.record_sql_queries(Hub.current, self, query, vars,
                                                paramstyle, False)

    def execute(self, query, vars=None):
        with self._log(query, vars):
            super().execute(query, vars)

    def callproc(self, procname, vars=None):
        with self._log(procname, vars, paramstyle=None):
            super().callproc(procname, vars)

def db_connect(url, name=None):
    """Setup a database connection

    :param str url: Database to connect to
    :return: A database connection
    :rtype: sqlite.Connection
    """

    psycopg2.extensions.register_adapter(SteamID, psycopg2.extensions.AsIs)
    psycopg2.extensions.set_wait_callback(psycopg2.extras.wait_select)
    return psycopg2.connect(url, cursor_factory=TracingCursor,
                            application_name=name or " ".join(sys.argv))

def db_init(c):
    with open("{}/schema.sql".format(os.path.dirname(__file__))) as schema:
        c.cursor().execute(schema.read())

# These need to stay in topological order to avoid foreign key trouble
# They may also be used to know what to delete on failure
# The second element of the tuple is what to order by when inserting (e.g. the primary key)
tables = (('log', 'logid'), ('log_json', 'logid'), ('round', 'logid, seq'),
          ('player_stats_backing', 'steamid64, logid'),
          ('player_stats_extra', 'steamid64, logid'),
          ('medic_stats', 'steamid64, logid'),
          ('heal_stats', 'logid, healer, healee'),
          ('class_stats', 'steamid64, logid, classid'),
          ('weapon_stats', 'steamid64, logid, classid, weaponid'),
          ('event_stats', 'steamid64, logid, eventid'), ('chat', 'logid, seq'))

def delete_logs(cur):
    # Done in reverse order as import_log
    # Don't delete log or log_json so we know not to parse this log again
    for table in tables[:1:-1]:
        cur.execute("""DELETE
                       FROM {}
                       WHERE logid IN (SELECT
                               logid
                           FROM to_delete
                       );""".format(table[0]))
    cur.execute("SELECT count(*) FROM to_delete;")
    logging.info("Removed %s log(s)", cur.fetchone()[0])
    cur.execute("""DELETE FROM to_delete;""")

def table_columns(c, table):
    cur = c.cursor()
    cur.execute("""SELECT
                       column_name
                   FROM information_schema.columns
                   WHERE table_catalog = current_catalog
                       AND table_schema = current_schema
                       AND table_name = %s;""", (table,))
    return (row[0] for row in cur)
