# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020, 25 Sean Anderson <seanga2@gmail.com>

import contextlib
from functools import wraps
import logging

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

def mc_connect(servers):
    if servers:
        return TracingClient(servers.split(','), binary=False, behaviors={ 'cas': True })
    return NoopClient()

def cache_result(key_template, timeout=120, expire=86400):
    def decorator(f):
        @wraps(f)
        def wrapper(mc, *args, **kwargs):
            key = key_template.format(*args, **kwargs)
            with sentry_sdk.start_span(op='cache.get', description=key) as span:
                span.set_data('cache.key', key)
                val, cas = mc.gets(key)
                if val is not None:
                    span.set_data('cache.hit', True)
                    return val

                if cas is None:
                    # Add a dummy value so we can delete it if we have to purge
                    mc.add(key, None, time=timeout)

                    val, cas = mc.gets(key)
                    # Did someone else fill the cache in the meantime?
                    if val is not None:
                        span.set_data('cache.hit', True)
                        return val

                span.set_data('cache.hit', False)

            val = f(mc, *args, **kwargs)
            try:
                if cas is not None:
                    with sentry_sdk.start_span(op='cache.put', description=key) as span:
                        span.set_data('cache.key', key)
                        mc.cas(key, val, cas, time=expire)
            except pylibmc.NotFound:
                pass
            return val
        return wrapper
    return decorator

def purge(c, mc, cols, table, key):
    with (sentry_sdk.start_span(op='db.transaction', description="purge"), c.cursor() as cur):
        while True:
            cur.execute("BEGIN;")
            cur.execute(f"SELECT {cols} FROM {table} FOR UPDATE SKIP LOCKED LIMIT 1000;")
            vals = list(cur)
            if not vals:
                return

            mc.delete_multi(key.format(*val) for val in vals)
            psycopg2.extras.execute_values(cur,
                f"DELETE FROM {table} WHERE ROW({cols}) IN (%s);", vals)
            cur.execute("COMMIT;")
            logging.info("Purged %s value(s) from %s", len(vals), table)

def purge_logs(c, mc):
    purge(c, mc, 'logid, 0', 'cache_purge_log', "log_{}")

def purge_matches(c, mc):
    purge(c, mc, 'league, matchid', 'cache_purge_match', "match_{}_{}")

def purge_players(c, mc):
    purge(c, mc, 'steamid64, 0', 'cache_purge_player', "overview_{}")
