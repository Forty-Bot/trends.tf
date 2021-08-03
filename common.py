# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
from dateutil import tz

def get_filters(args):
    ret = {}

    # We need the or None to turn false-y values into NULLs
    ret['class'] = args.get('class', None, str) or None
    ret['format'] = args.get('format', None, str) or None
    map = args.get('map', None, str)
    ret['map'] = "%{}%".format(map) if map else None

    timezone = args.get('timezone', tz.UTC, tz.gettz)

    def parse_date(name):
        date = args.get(name, None, datetime.fromisoformat)
        if date:
            date.replace(tzinfo=timezone)
            return (date.date().isoformat(), date.timestamp())
        return (None, None)

    (ret['date_from'], ret['date_from_ts']) = parse_date('date_from')
    (ret['date_to'], ret['date_to_ts']) = parse_date('date_to')

    return ret

# These are common filter clauses which can be added to any query
filter_clauses = \
    """AND (class = %(class)s OR %(class)s ISNULL)
       AND (format = %(format)s OR %(format)s ISNULL)
       AND (map ILIKE %(map)s OR %(map)s ISNULL)
       AND (time >= %(date_from_ts)s::BIGINT OR %(date_from_ts)s ISNULL)
       AND (time <= %(date_to_ts)s::BIGINT OR %(date_to_ts)s ISNULL)"""
