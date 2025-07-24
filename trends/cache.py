# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020, 25 Sean Anderson <seanga2@gmail.com>

import contextlib

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

def mc_connect(servers):
    if servers:
        return TracingClient(servers.split(','), binary=True, behaviors={ 'cas': True })
    return NoopClient()

def purge_players(c, mc):
    with (sentry_sdk.start_span(op='db.transaction', description="purge"), c.cursor() as cur):
        while True:
            cur.execute("BEGIN;")
            cur.execute("""SELECT steamid64
                           FROM cache_purge_player
                           FOR UPDATE SKIP LOCKED
                           LIMIT 1000;""")
            players = tuple(row[0] for row in cur)
            if not len(players):
                return

            mc.delete_multi(f"overview_{steamid}" for steamid in players)
            cur.execute("DELETE FROM cache_purge_player WHERE steamid64 IN %s;", (players,))
            cur.execute("COMMIT;")
