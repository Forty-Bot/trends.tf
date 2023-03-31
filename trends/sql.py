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

    psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)
    psycopg2.extensions.register_adapter(SteamID, psycopg2.extensions.AsIs)
    psycopg2.extensions.set_wait_callback(psycopg2.extras.wait_select)
    return psycopg2.connect(url, cursor_factory=TracingCursor,
                            application_name=name or " ".join(sys.argv))

def _db_init(cur):
    with open("{}/schema.sql".format(os.path.dirname(__file__))) as schema:
        cur.execute(schema.read())

    # Create new partitions for log_json, if there is anything in the default partition
    cur.execute("SELECT max(logid)/100000 FROM log_json_default")
    max_part = cur.fetchone()[0]
    if max_part is None:
        return

    for i in range(max_part + 1):
        tbl = f"log_json_{i:#02}e5"
        cur.execute("BEGIN;")
        try:
            cur.execute("SELECT %s::regclass;", (tbl,))
        except psycopg2.Error:
            cur.execute("ROLLBACK;")
        else:
            cur.execute("COMMIT;")
            continue

        cur.execute("BEGIN;")
        lower = i * 1e5
        upper = (i + 1) * 1e5
        logging.info("Creating partition %s", tbl)

        cur.execute(f"CREATE TABLE {tbl} (LIKE log_json);")
        cur.execute(f"ALTER TABLE {tbl} ADD CHECK (logid >= %s AND logid < %s);", (lower, upper))
        cur.execute(f"""INSERT INTO {tbl}
                        SELECT *
                        FROM log_json_default
                        WHERE logid >= %s AND logid < %s
                        ORDER BY logid;""", (lower, upper));
        cur.execute(f"ANALYZE {tbl};")
        cur.execute(f"DELETE FROM log_json_default WHERE logid IN (SELECT logid FROM {tbl});")
        cur.execute("""ALTER TABLE log_json_default
                       ADD CONSTRAINT new_minimum CHECK (logid >= %s);""", (upper,))
        cur.execute("ALTER TABLE log_json_default DROP CONSTRAINT minimum;")
        cur.execute("ALTER TABLE log_json_default RENAME CONSTRAINT new_minimum TO minimum;")
        cur.execute(f"""ALTER TABLE log_json
                        ATTACH PARTITION {tbl}
                            FOR VALUES FROM (%s) TO (%s);""", (lower, upper))
        cur.execute("COMMIT;")

def db_init(c):
    cur = c.cursor()
    cur.execute("SELECT pg_advisory_lock(0);")
    try:
        _db_init(cur)
    finally:
        cur.execute("SELECT pg_advisory_unlock(0);")

# These need to stay in topological order to avoid foreign key trouble
# They may also be used to know what to delete on failure
# The second element of the tuple is what to order by when inserting (e.g. the primary key)
log_tables = (('log', 'logid'), ('log_json', 'logid'), ('round', 'logid, seq'),
             ('player_stats_backing', 'playerid, logid'),
             ('player_stats_extra', 'playerid, logid'),
             ('medic_stats', 'playerid, logid'),
             ('heal_stats', 'logid, healer, healee'),
             ('class_stats', 'playerid, logid, classid'),
             ('weapon_stats', 'playerid, logid, classid, weaponid'),
             ('event_stats', 'playerid, logid, eventid'), ('chat', 'logid, seq'))

def delete_logs(cur):
    # Done in reverse order as import_log
    # Don't delete log or log_json so we know not to parse this log again
    for table in log_tables[:1:-1]:
        cur.execute("""DELETE
                       FROM {}
                       WHERE logid IN (SELECT
                               logid
                           FROM to_delete
                       );""".format(table[0]))
    cur.execute("SELECT count(*) FROM to_delete;")
    logging.info("Removed %s log(s)", cur.fetchone()[0])
    cur.execute("""DELETE FROM to_delete;""")

def publicize(c, tables):
    cur = c.cursor()
    for table in tables:
        set_clause = ", ".join("{}=EXCLUDED.{}".format(col, col)
                               for col in table_columns(c, table[0]))
        cur.execute("""INSERT INTO public.{}
                       SELECT
                           *
                       FROM {}
                       ORDER BY {}
                       ON CONFLICT ({}) DO UPDATE
                       SET {};"""
                    .format(table[0], table[0], table[1], table[1], set_clause))
    for table in tables[::-1]:
        cur.execute("""DELETE FROM {};""".format(table[0]))

def table_columns(c, table):
    cur = c.cursor()
    cur.execute("""SELECT
                       column_name
                   FROM information_schema.columns
                   WHERE table_catalog = current_catalog
                       AND table_schema = current_schema
                       AND table_name = %s;""", (table,))
    return (row[0] for row in cur)
