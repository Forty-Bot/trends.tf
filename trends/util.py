# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import itertools
import pkg_resources

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

def sentry_init():
    try:
        version = pkg_resources.require("trends.tf")[0].version
    except pkg_resources.DistributionNotFound:
        version = None

    return sentry_sdk.init(
        release=version,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.15,
        send_default_pii=True,
    )
