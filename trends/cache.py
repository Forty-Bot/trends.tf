# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020, 25 Sean Anderson <seanga2@gmail.com>

import contextlib
from functools import wraps
import logging

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

@contextlib.contextmanager
def cache_span(category, op, key):
    sentry_sdk.add_breadcrumb(type='query', category=category, message=key)
    with sentry_sdk.start_span(op=category, description=f"{op} {key}") as span:
        span.set_data('cache.operation', op)
        span.set_data('cache.key', key)
        yield span

class TracingClient(pylibmc.Client):
    def get(self, key, default=None):
        with cache_span('cache.get', 'get', key) as span:
            value = super().get(key, self)
            if value is self:
                span.set_data('cache.hit', False)
                return default
            else:
                span.set_data('cache.hit', True)
                return value

    def get_multi(self, keys):
        keys = list(keys)
        with cache_span('cache.get', 'get_multi', keys) as span:
            values = super().get_multi(keys)
            span.set_data('cache.hit', bool(values))
            return values

    def set(self, key, value, *args, **kwargs):
        with cache_span('cache.set', 'set', key):
            return super().set(key, value, *args, **kwargs)

    def set_multi(self, mapping, *args, **kwargs):
        with cache_span('cache.set', 'set_multi', list(mapping)) as span:
            return super().set_multi(mapping, *args, **kwargs)

    def add(self, key, value, *args, **kwargs):
        with cache_span('cache.set', 'add', key):
            return super().add(key, value, *args, **kwargs)

    def replace(self, key, value, *args, **kwargs):
        with cache_span('cache.set', 'replace', key):
            return super().replace(key, value, *args, **kwargs)

    def gets(self, key, default=None):
        with cache_span('cache.get', 'gets', key) as span:
            value, cas = super().gets(key)
            if value is None and cas is None:
                span.set_data('cache.hit', False)
                return None, None
            else:
                span.set_data('cache.hit', True)
                return value, cas

    def cas(self, key, value, cas, time=0):
        with cache_span('cache.set', 'cas', key):
            return super().cas(key, value, cas, time)

    def delete(self, key):
        with cache_span('cache.delete', 'delete', key):
            return super().delete(key)

    # delete_multi just calls delete repeatedly

    def flush_all(self):
        sentry_sdk.add_breadcrumb(type='query', category='cache.clear')
        with sentry_sdk.start_span(op='cache.clear') as span:
            return super().flush_all()

def mc_connect(servers):
    if servers:
        return TracingClient(servers.split(','), binary=True, behaviors={ 'cas': True })
    return NoopClient()

def cache_result(key_template, timeout=120, expire=86400):
    def decorator(f):
        @wraps(f)
        def wrapper(mc, *args, **kwargs):
            key = key_template.format(*args, **kwargs)
            val, cas = mc.gets(key)
            if val is not None:
                return val

            if cas is None:
                # Add a dummy value so we can delete it if we have to purge
                mc.add(key, None, time=timeout)

                val, cas = mc.gets(key)
                # Did someone else fill the cache in the meantime?
                if val is not None:
                    return val

            val = f(mc, *args, **kwargs)
            try:
                if cas is not None:
                    mc.cas(key, val, cas, time=expire)
            except pylibmc.NotFound:
                pass
            return val
        return wrapper
    return decorator

def purge(c, mc, col, table, keys):
    with (sentry_sdk.start_span(op='db.transaction', description="purge"), c.cursor() as cur):
        while True:
            cur.execute("BEGIN;")
            cur.execute(f"SELECT {col} FROM {table} FOR UPDATE SKIP LOCKED LIMIT 1000;")
            vals = tuple(row[0] for row in cur)
            if not len(vals):
                return

            for key in keys:
                mc.delete_multi(key.format(val) for val in vals)
            cur.execute(f"DELETE FROM {table} WHERE {col} IN %s;", (vals,))
            cur.execute("COMMIT;")
            logging.info("Purged %s value(s) from %s", len(vals), table)

def purge_players(c, mc):
    purge(c, mc, 'steamid64', 'cache_purge_player', ("overview_{}",))
