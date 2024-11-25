# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import contextlib

import pylibmc
import sentry_sdk

_sentinel = object()

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
            value = super().get(key, _sentinel)
            if value is _sentinel:
                span.set_data('cache.hit', False)
                return default
            else:
                span.set_data('cache.hit', True)
                return value

    def get_multi(self, keys):
        keys = list(keys)
        with sentry_sdk.start_span('cache.get', 'get_multi', keys) as span:
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
