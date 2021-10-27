# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask

from sql import get_db
from util import get_filters, get_order

def logs(api):
    limit = flask.request.args.get('limit', 100, int)
    offset = flask.request.args.get('offset', 0, int)
    filters = get_filters(flask.request.args)
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
                        format
                    FROM log
                    JOIN map USING (mapid)
                    LEFT JOIN format USING (formatid)
                    LEFT JOIN (SELECT
                            logid
                        FROM player_stats
                        WHERE steamid64 IN %(players)s
                        GROUP BY logid
                    ) AS ps USING (logid)
                    WHERE (ps.logid NOTNULL OR %(players)s ISNULL)
                        AND (title ILIKE %(title)s OR %(title)s ISNULL)
                        AND (format = %(format)s OR %(format)s ISNULL)
                        AND (map ILIKE %(map)s OR %(map)s ISNULL)
                        AND (time >= %(date_from_ts)s::BIGINT OR %(date_from_ts)s ISNULL)
                        AND (time <= %(date_to_ts)s::BIGINT OR %(date_to_ts)s ISNULL)
                    ORDER BY {}
                    LIMIT %(limit)s OFFSET %(offset)s;""".format(order_clause),
                { **filters, 'limit': limit, 'offset': offset })

    logs = logs.fetchall()
    if (api):
        return flask.jsonify(logs=[dict(log) for log in logs])
    else:
        return flask.render_template("logs.html", logs=logs, limit=limit, offset=offset,
                                     filters=filters, order=order)
