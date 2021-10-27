# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import flask

import common
from sql import get_db

api = flask.Blueprint('api', __name__)
api.add_url_rule("/logs", view_func=common.logs, defaults={ 'api': True })

@api.after_request
def do_cache(resp):
    resp.add_etag()
    resp.cache_control.max_age = 300
    return resp

@api.route('/maps')
def maps():
    maps = get_db().cursor()
    # We use statistics here to avoid a sequential scan on log just to order results
    maps.execute("""SELECT
                     map
                 FROM map
                 JOIN (SELECT
                         mapid,
                         count(*) AS popularity
                     FROM log
                     GROUP BY mapid
                 ) AS log USING (mapid)
                 ORDER BY popularity DESC, mapid ASC;""")
    return flask.jsonify(maps=[row[0] for row in maps])
