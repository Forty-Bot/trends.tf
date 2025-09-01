# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020, 25 Sean Anderson <seanga2@gmail.com>

import contextlib
from functools import wraps
import logging
import secrets
import zlib

from mpmetrics import Counter
import psycopg2.extras
import pylibmc
import sentry_sdk

class NoopClient:
    def get(self, key, default=None):
        return default

    def get_multi(self, keys):
        return {}

    def set(self, key, value, *args, **kwargs):
        return False

    def set_multi(self, mapping, *args, **kwargs):
        return list(mapping.keys())

    def add(self, key, value, *args, **kwargs):
        return True

    def replace(self, key, value, *args, **kwargs):
        return False

    def gets(self, key):
        return None, None

    def cas(self, key, value, cas, time=0):
        raise pylibmc.NotFound

    def delete(self, key):
        return False

    def delete_multi(self, keys):
        return False

    def flush_all(self):
        return True

class TracingClient(pylibmc.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tracing_enabled = False

    @contextlib.contextmanager
    def _cache_span(self, op, key):
        if self._tracing_enabled:
            yield
            return

        desc = f"{op} {key}"
        sentry_sdk.add_breadcrumb(category='query', message=desc)
        with sentry_sdk.start_span(op='db.query', description=desc) as span:
            span.set_data('db.system', "memcached")
            span.set_data('db.operation', op)
            yield span

    def get(self, key, default=None):
        with self._cache_span('get', key) as span:
            value = super().get(key, self)
            return default if value is self else value

    def get_multi(self, keys):
        keys = list(keys)
        with self._cache_span('get_multi', keys) as span:
            values = super().get_multi(keys)
            return values

    def set(self, key, value, *args, **kwargs):
        with self._cache_span('set', key):
            return super().set(key, value, *args, **kwargs)

    def set_multi(self, mapping, *args, **kwargs):
        with self._cache_span('set_multi', ', '.join(mapping.values())) as span:
            return super().set_multi(mapping, *args, **kwargs)

    def add(self, key, value, *args, **kwargs):
        with self._cache_span('add', key):
            return super().add(key, value, *args, **kwargs)

    def replace(self, key, value, *args, **kwargs):
        with self._cache_span('replace', key):
            return super().replace(key, value, *args, **kwargs)

    def gets(self, key, default=None):
        with self._cache_span('gets', key) as span:
            value, cas = super().gets(key)
            if value is None and cas is None:
                return None, None
            else:
                return value, cas

    def cas(self, key, value, cas, time=0):
        with self._cache_span('cas', key):
            return super().cas(key, value, cas, time)

    def delete(self, key):
        with self._cache_span('delete', key):
            return super().delete(key)

    def delete_multi(self, keys):
        keys = list(keys)
        with self._cache_span('delete_multi', ', '.join(keys)) as span:
            self._tracing_disabled = True
            try:
                return super().delete_multi(keys)
            finally:
                self._tracing_disabled = False

    def flush_all(self):
        sentry_sdk.add_breadcrumb(category='query', message='flush_all')
        with sentry_sdk.start_span(op='db.query', description='flush_all') as span:
           span.set_data('db.system', 'memcached')
           span.set_data('db.operation', 'flush_all')
           return super().flush_all()

    def serialize(self, value):
        data, flag = super().serialize(value)
        if len(data) > 2000 and not flag & 8:
            with sentry_sdk.start_span(op='function', description='zlib.compress'):
                return zlib.compress(data), flag | 8
        return data, flag

def mc_connect(servers):
    if servers:
        return TracingClient(servers.split(','), binary=False, behaviors={ 'cas': True })
    return NoopClient()

CACHE_ACCESS = Counter('memcached_request', "Total memcached requests", ['key_template'])
CACHE_HIT = Counter('memcached_request_hit', "Successful memcached requests", ['key_template'])

def mutable(key_template, timeout=30, expire=86400):
    def decorator(f):
        @wraps(f)
        def wrapper(mc, *args, **kwargs):
            key = key_template.format(*args, **kwargs)
            with sentry_sdk.start_span(op='cache.get', description=key) as span:
                CACHE_ACCESS.labels(key_template).inc()
                span.set_data('cache.key', key)
                try:
                    val, cas = mc.gets(key)
                    if val is not None:
                        span.set_data('cache.hit', True)
                        CACHE_HIT.labels(key_template).inc()
                        return val

                    if cas is None:
                        # Add a dummy value so we can delete it if we have to purge
                        mc.add(key, None, time=timeout)

                        val, cas = mc.gets(key)
                        # Did someone else fill the cache in the meantime?
                        if val is not None:
                            span.set_data('cache.hit', True)
                            CACHE_HIT.labels(key_template).inc()
                            return val
                except pylibmc.Error:
                    logging.exception("Could not get %s", key)
                span.set_data('cache.hit', False)

            val = f(mc, *args, **kwargs)
            try:
                if cas is not None:
                    with sentry_sdk.start_span(op='cache.put', description=key) as span:
                        span.set_data('cache.key', key)
                        mc.cas(key, val, cas, time=expire)
            except pylibmc.Error:
                logging.exception("Could not set %s", key)
            return val
        return wrapper
    return decorator

def immutable(key_template, expire=86400):
    def decorator(f):
        @wraps(f)
        def wrapper(mc, *args, **kwargs):
            key = key_template.format(*args, **kwargs)
            with sentry_sdk.start_span(op='cache.get', description=key) as span:
                CACHE_ACCESS.labels(key_template).inc()
                span.set_data('cache.key', key)
                try:
                    val = mc.get(key)
                    if val is not None:
                        span.set_data('cache.hit', True)
                        CACHE_HIT.labels(key_template).inc()
                        return val
                except pylibmc.Error:
                    logging.exception("Could not get %s", key)
                span.set_data('cache.hit', False)

            val = f(mc, *args, **kwargs)
            try:
                with sentry_sdk.start_span(op='cache.put', description=key) as span:
                    span.set_data('cache.key', key)
                    mc.set(key, val, time=expire)
            except pylibmc.Error:
                logging.exception("Could not set %s", key)
            return val
        return wrapper
    return decorator

def version(mc, *args):
    return secrets.token_bytes(16)

# Not really immutable, but doesn't depend on postgres so we can update it directly
for prefix in ('logs', 'players'):
    key = f"{prefix}_version"
    vars()[key] = immutable(key, expire=0)(version)

matches_version = immutable("matches_{}_version", expire=0)(version)

def purge(c, mc, col, table, prefix, cond="TRUE"):
    with (sentry_sdk.start_span(op='db.transaction', description="purge"), c.cursor() as cur):
        while True:
            cur.execute("BEGIN;")
            cur.execute(
                f"""SELECT {col}
                    FROM {table}
                    WHERE {cond}
                    FOR UPDATE SKIP LOCKED LIMIT 1000;""")
            vals = tuple(row[0] for row in cur)
            if not vals:
                return

            mc.delete_multi(prefix + str(val) for val in vals)
            cur.execute(f"DELETE FROM {table} WHERE {cond} AND {col} IN %s;", (vals,))
            cur.execute("COMMIT;")
            logging.info("Purged %s value(s) from %s", len(vals), table)

def _update_version(mc, prefix):
    key = f"{prefix}_version"
    try:
        with sentry_sdk.start_span(op='cache.put', description=key) as span:
            span.set_data('cache.key', key)
            mc.set(key, version(mc))
    except pylibmc.Error:
        logging.exception("Could not set %s", key)

def purge_logs(c, mc):
    _update_version(mc, 'logs')
    mc.delete("index")
    purge(c, mc, 'logid', 'cache_purge_log', "log_")

def purge_matches(c, mc, league):
    _update_version(mc, f"matches_{league}")
    purge(c, mc, 'matchid', 'cache_purge_match', f"match_{league}_", f"league = '{league}'")

def purge_players(c, mc):
    _update_version(mc, 'players')
    mc.delete("index")
    purge(c, mc, 'steamid64', 'cache_purge_player', "overview_")
