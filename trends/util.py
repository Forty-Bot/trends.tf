# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import itertools

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
