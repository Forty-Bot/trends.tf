# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

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

@contextlib.contextmanager
def cache_span(op, key):
    sentry_sdk.add_breadcrumb(type='query', category=op, message=key)
    with sentry_sdk.start_span(op=op) as span:
        span.set_data('cache.key', key)
        yield span

class TracingClient(pylibmc.Client):
    def get(self, key, default=None):
        with cache_span('cache.get', key) as span:
            value = super().get(key, None)
            if value is None:
                span.set_data('cache.hit', False)
                return default
            else:
                span.set_data('cache.hit', True)
                return value

    def get_multi(self, keys):
        keys = list(keys)
        with sentry_sdk.start_span('cache.get', keys) as span:
            values = super().get_multi(keys)
            span.set_data('cache.hit', bool(values))
            return values

    def set(self, key, value, *args, **kwargs):
        with cache_span('cache.set', key):
            return super().set(key, None, *args, **kwargs)

    def set_multi(self, mapping, *args, **kwargs):
        with cache_span('cache.set', list(mapping)) as span:
            return super().set_multi(mapping, *args, **kwargs)

    def add(self, key, value, *args, **kwargs):
        with cache_span('cache.set', key):
            return super().add(key, None, *args, **kwargs)

    def replace(self, key, value, *args, **kwargs):
        with cache_span('cache.set', key):
            return super().replace(key, None, *args, **kwargs)
