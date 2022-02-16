# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import flask
import werkzeug.exceptions

from .common import get_logs, get_players
from .util import get_db, get_pagination

api = flask.Blueprint('api', __name__)

@api.errorhandler(werkzeug.exceptions.HTTPException)
def json_handler(error):
    return flask.jsonify(error={
        'code': error.code,
        'name': error.name,
        'description': error.description,
    }), error.code

@api.after_request
def do_cache(resp):
    resp.add_etag()
    resp.cache_control.max_age = 300
    return resp

@api.route('/logs')
def logs():
    return flask.jsonify(logs=[dict(log) for log in get_logs()])

@api.route('/maps')
def maps():
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
    q = flask.request.args.get('q', '', str)
    return flask.jsonify(players=[dict(player) for player in get_players(q)])
