# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
from dateutil import tz
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

def get_filters(args):
    ret = {}

    # We need the or None to turn false-y values into NULLs
    ret['class'] = args.get('class', None, str) or None
    ret['format'] = args.get('format', None, str) or None
    map = args.get('map', None, str)
    ret['map'] = "%{}%".format(map) if map else None
    title = args.get('title', None, str)
    ret['title'] = "%{}%".format(title) if title else None
    ret['players'] = tuple(args.getlist('steamid64', int)) or (None,)

    timezone = args.get('timezone', tz.UTC, tz.gettz)
    def parse_date(name):
        date = args.get(name, None, datetime.fromisoformat)
        if date:
            date = date.replace(tzinfo=timezone).astimezone(tz.UTC)
            return (date.date().isoformat(), date.timestamp())
        return (None, None)

    (ret['date_from'], ret['date_from_ts']) = parse_date('date_from')
    (ret['date_to'], ret['date_to_ts']) = parse_date('date_to')

    return ret

# These are common filter clauses which can be added to any query
common_clauses = \
    """AND (format = %(format)s OR %(format)s ISNULL)
       AND (map ILIKE %(map)s OR %(map)s ISNULL)
       AND (time >= %(date_from_ts)s::BIGINT OR %(date_from_ts)s ISNULL)
       AND (time <= %(date_to_ts)s::BIGINT OR %(date_to_ts)s ISNULL)"""

def get_order(args, column_map, default_column, default_dir='desc'):
    column = args.get('sort', None, str)
    if column not in column_map.keys():
        column = default_column

    dir_map = {'desc': "DESC", 'asc': "ASC"}
    dir = args.get('sort_dir', None, str)
    if dir not in dir_map.keys():
        dir = default_dir

    return ({ 'sort': column, 'sort_dir': dir },
            "{} {}".format(column_map[column], dir_map[dir]))
