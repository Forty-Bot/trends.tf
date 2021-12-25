# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

from datetime import datetime, timedelta
from dateutil import tz

import flask

from .util import get_filter_params, get_filter_clauses, get_order
from ..sql import get_db

def logs(api):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    filters = get_filter_params(flask.request.args)
    filter_clauses = get_filter_clauses(filters, 'title', 'format', 'map', 'time', 'logid')
    order, order_clause = get_order(flask.request.args, {
        'logid': "logid",
        'duration': "duration",
        'date': "time",
	}, 'logid')
    logs = get_db().cursor()
    logs.execute("""SELECT
                        logid,
                        time,
                        duration,
                        title,
                        map,
                        format,
                        duplicate_of
                    FROM log
                    JOIN map USING (mapid)
                    LEFT JOIN format USING (formatid)
                    WHERE TRUE
                        {}
                    ORDER BY {}
                    LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
                { **filters, 'limit': limit, 'offset': offset })

    logs = logs.fetchall()
    if (api):
        return flask.jsonify(logs=[dict(log) for log in logs])
    else:
        return flask.render_template("logs.html", logs=logs, limit=limit, offset=offset,
                                     filters=filters, order=order)
