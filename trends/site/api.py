# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import flask
import werkzeug.exceptions

from .. import cache
from .common import get_logs, search_players, logs_last_modified
from .util import get_db, get_mc, get_pagination, last_modified, view_updated
from .root import get_log

api = flask.Blueprint('api', __name__)

@api.errorhandler(werkzeug.exceptions.HTTPException)
def json_handler(error):
    return flask.jsonify(error={
        'code': error.code,
        'name': error.name,
        'description': error.description,
    }), error.code

def next_page(rows):
    args = flask.request.args.to_dict(flat=False)
    args.update(flask.request.view_args)

    limit, offset = flask.g.page
    args['limit'] = limit
    if len(rows) == limit:
        args['offset'] = offset + limit
        return flask.url_for(flask.request.endpoint, **args)

@api.route('/log/<int:logid>')
def log(logid):
    log = get_log(get_mc(), logid)

    if not log:
        return flask.abort(404)

    if resp := last_modified(log['summary']['updated'], log['version'], weak=True):
        return resp

    summary = log['summary']
    del summary['team1_is_red']
    return flask.jsonify(summary=summary)

@api.route('/logs')
def logs():
    if resp := logs_last_modified():
        return resp

    view = flask.request.args.get('view', 'basic', str)
    logs = [dict(log) for log in get_logs(view)]
    return flask.jsonify(logs=logs, next_page=next_page(logs))

@api.route('/maps')
def maps():
    if resp := view_updated('map_popularity'):
        return resp

    limit, offset = get_pagination(limit=500)
    maps = get_db().cursor()
    maps.execute(
        """SELECT map
           FROM map_popularity
           ORDER BY popularity DESC, mapid ASC
           LIMIT %s OFFSET %s;""", (limit, offset))

    return flask.jsonify(maps=[row[0] for row in maps])

@api.route('/players')
def players():
    if resp := last_modified(None, cache.players_version(get_mc())):
        return resp

    q = flask.request.args.get('q', '', str)
    return flask.jsonify(players=[dict(player) for player in search_players(q)])
