# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import enum
import itertools
import pkg_resources

import flask
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

classes = (
    'demoman',
    'engineer',
    'heavyweapons',
    'medic',
    'pyro',
    'scout',
    'sniper',
    'soldier',
    'spy'
)

events = {
    'classkills': 'kill',
    'classdeaths': 'death',
    'classkillassists': 'assist',
}

@enum.unique
class League(str, enum.Enum):
    ETF2L = 'etf2l'
    RGL = 'rgl'

    def __str__(self):
        return self.value

def clamp(n, lower, upper):
    return max(lower, min(n, upper))

# Adapted from https://stackoverflow.com/a/8998040/5086505
def chunk(iterable, n):
    it = iter(iterable)
    while True:
        slice = itertools.islice(it, n)
        try:
            first = next(slice)
        except StopIteration:
            return
        yield itertools.chain((first,), slice)

def flask_sampler(ctx):
    if ctx['parent_sampled'] is not None:
        return float(ctx['parent_sampled'])

    if 'wsgi_environ' in ctx and ctx['wsgi_environ']['REQUEST_URI'].startswith('/log/'):
        return 0.0005

    return 0.02

def sentry_init(debug=False, **kwargs):
    try:
        version = pkg_resources.require("trends.tf")[0].version
    except pkg_resources.DistributionNotFound:
        version = None

    defaults = {
        'release': version,
        'integrations': [FlaskIntegration()],
        'traces_sampler': (lambda ctx: 1.0) if debug else flask_sampler,
        'send_default_pii': True,
    }

    return sentry_sdk.init(defaults | kwargs)
