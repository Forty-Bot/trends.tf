# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

from functools import wraps
from collections import namedtuple
from datetime import datetime, timedelta
from dateutil import tz
from itertools import islice
import sys

import flask
import psycopg2
from psycopg2.extras import NumericRange
import pylibmc
import werkzeug.exceptions, werkzeug.http

from ..util import clamp
from ..sql import db_connect

def last_modified(since):
    if flask.current_app.debug:
        return None

    if since is None:
        flask.g.last_modified = datetime.now(tz.UTC)
    else:
        flask.g.last_modified = datetime.fromtimestamp(since, tz.UTC)

    if not werkzeug.http.is_resource_modified(flask.request.environ,
                                              last_modified=flask.g.last_modified):
        return "", 304

def global_context(name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if name not in flask.g:
                setattr(flask.g, name, f(*args, **kwargs))
            return flask.g.get(name)
        return decorated
    return decorator

@global_context('db_conn')
def get_db():
    try:
        c = db_connect(flask.current_app.config['DATABASE'],
                       "{} {}".format(sys.argv[0], flask.request.path))
    except psycopg2.OperationalError as error:
        flask.current_app.logger.exception("Could not connect to database")
        raise werkzeug.exceptions.ServiceUnavailable() from error
    c.cursor().execute("SET statement_timeout = %s;", (flask.current_app.config['TIMEOUT'],))
    return c

def put_db(exception):
    if db := flask.g.pop('db_conn', None):
        db.close()

class NoopClient:
    def get(self, key, default=None):
        return default

    def set(self, key, value, **kwargs):
        pass

@global_context('mc_conn')
def get_mc():
    servers = flask.current_app.config['MEMCACHED_SERVERS']
    if servers:
        try:
            mc = pylibmc.Client(servers.split(','), binary=True)
            # pylibmc doesn't actually connect until we make a request. Force a connection failure
            # up front so we can log it and use a fallback client
            mc.get('connection_test')
            return mc
        except pylibmc.ConnectionError as error:
            flask.current_app.logger.exception("Could not connect to memcached")
    return NoopClient()

@global_context('filters')
def get_filter_params():
    args = flask.request.args
    params = {}

    params['class'] = args.get('class', type=str)
    params['format'] = args.get('format', type=str)
    params['league'] = args.get('league', type=str)
    params['comp'] = args.get('comp', type=str)
    params['divid'] = args.get('divid', type=int)
    params['updated'] = args.get('updated_since', type=int)
    params['min_logs'] = args.get('min_logs', type=int)
    params['dupes'] = args.get('include_dupes', 'yes', str) == 'yes'
    if val := tuple(args.getlist('steamid64', type=int)[:5]):
        players = get_db().cursor()
        players.execute("""SELECT
                               steamid64,
                               playerid,
                               avatarhash,
                               name
                           FROM player
                           JOIN name USING (nameid)
                           WHERE steamid64 IN %s;""",
                        (val,))
        params['players'] = players.fetchall()
    else:
        params['players'] = ()

    def set_like_param(name):
        if val := args.get(name, type=str):
            params[name] = "%{}%".format(val)
        else:
            params[name] = None

    set_like_param('map')
    set_like_param('title')
    set_like_param('name')

    timezone = args.get('timezone', tz.UTC, tz.gettz)
    def set_date_params(prep):
        name = f"date_{prep}"
        name_ts = f"date_{prep}_ts"
        if date := args.get(name, None, datetime.fromisoformat):
            utcdate = date.replace(tzinfo=timezone).astimezone(tz.UTC)
            params[name] = date.date().isoformat()
            params[name_ts] = int(utcdate.timestamp())
        elif timestamp := args.get(f"time_{prep}", None, int):
            params[name_ts] = timestamp
        else:
            params[name] = None
            params[name_ts] = None

    set_date_params('from')
    set_date_params('to')

    if params['date_from_ts'] and params['date_to_ts']:
        if params['date_from_ts'] <= params['date_to_ts']:
            params['date_range'] = \
                NumericRange(params['date_from_ts'], params['date_to_ts'], bounds='[]')
        else:
            params['date_range'] = NumericRange(empty=True)
    elif params['date_from_ts']:
        params['date_range'] = NumericRange(lower=params['date_from_ts'], bounds='[)')
    elif params['date_to_ts']:
        params['date_range'] = NumericRange(upper=params['date_to_ts'], bounds='(]')

    return params

def get_filter_clauses(params, *valid_columns, **column_map):
    clauses = []
    for col in valid_columns:
        column_map[col] = col

    def id_clause(column):
        if params[column] and column in column_map:
            clauses.append(f"AND {column_map[column]} = %({column})s")

    id_clause('league')
    id_clause('divid')

    def simple_clause(name, column, table=None, table_col=None):
        if not params[name]:
            return

        if name in column_map:
            clauses.append(f"AND {column_map[name]} = %({name})s")
        elif column in column_map:
            clauses.append(f"""AND {column_map[column]} = (
                                   SELECT {column}
                                   FROM {name if table is None else table}
                                   WHERE {name if table_col is None else table_col} = %({name})s
                               )""")

    simple_clause('class', 'classid')
    simple_clause('format', 'formatid')
    simple_clause('comp', 'compid', 'competition', 'name')

    if 'duplicate_of' in column_map and not params['dupes']:
        clauses.append(f"AND {column_map['duplicate_of']} ISNULL")

    if 'updated' in column_map and params['updated']:
        clauses.append(f"AND {column_map['updated']} > %(updated)s")

    if 'logs' in column_map and params['min_logs']:
        clauses.append(f"AND {column_map['logs']} >= %(min_logs)s")

    if 'primary_classid' in column_map and params['class']:
        clauses.append(f"""AND {column_map['primary_classid']} = (
                               SELECT classid
                               FROM class
                               WHERE class = %(class)s
                           )""")

    def like_clause(name):
        if name in column_map and params[name]:
            clauses.append(f"AND {column_map[name]} ILIKE %({name})s")

    like_clause('title')
    like_clause('name')
    like_clause('map')

    if 'mapid' in column_map and params['map']:
        clauses.append(f"""AND {column_map['mapid']} IN (
                               SELECT mapid
                               FROM map
                               WHERE map ILIKE %(map)s
                           )""")

    def date_clause(name, op):
        if 'time' in column_map and params[name]:
            clauses.append(f"AND {column_map['time']} {op} %({name})s::BIGINT")

    date_clause('date_from_ts', '>=')
    date_clause('date_to_ts', '<=')

    if 'date_range' in column_map and 'date_range' in params:
        clauses.append(f"AND {column_map['date_range']} && %(date_range)s")

    if 'logid' in column_map:
        for i, player in enumerate(params['players']):
            key = "player_{}".format(i)
            params[key] = player['playerid']
            clauses.append(f"""AND {column_map['logid']} IN (
                                   SELECT logid
                                   FROM player_stats
                                   WHERE playerid = %({key})s
                            )""")

    if 'playerid' in column_map and len(params['players']):
        params['playerids'] = tuple(player['playerid'] for player in params['players'])
        clauses.append(f"AND {column_map['playerid']} IN %(playerids)s")

    return "\n".join(clauses)

dir_map = {'desc': "DESC", 'asc': "ASC"}

@global_context('order')
def get_order(column_map, default_column, default_dir='desc'):
    args = flask.request.args

    column = args.get('sort', type=str)
    if column not in column_map.keys():
        column = default_column

    dir = args.get('sort_dir', type=str)
    if dir not in dir_map.keys():
        dir = default_dir

    return ({ 'sort': column, 'sort_dir': dir },
            "{} {}".format(column_map[column], dir_map[dir]))

Page = namedtuple('Page', ('limit', 'offset'))

@global_context('page')
def get_pagination(limit=100, offset=0):
    args = flask.request.args
    limit = clamp(args.get('limit', limit, int), 0, limit)
    offset = max(args.get('offset', offset, int), 0)
    return Page(limit, offset)
