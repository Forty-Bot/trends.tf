# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-24 Sean Anderson <seanga2@gmail.com>

import flask

from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination

leaderboards = flask.Blueprint('leaderboards', __name__)

@leaderboards.route('/')
def overview():
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'classid', 'league', 'formatid', 'mapid')

    # Since we are using a cube, we need to explicitly select the NULL rows
    cube_clauses = []
    grouping = 0b00000
    for (name, column, group) in (
            ('map',    'mapid',    0b0001),
            ('class',  'classid',  0b0010),
            ('format', 'formatid', 0b0100),
            ('league', 'league',   0b1000),
    ):
        if not filters[name]:
            cube_clauses.append(f"AND {column} ISNULL")
            grouping |= group
    cube_clauses = '\n'.join(cube_clauses)

    order, order_clause = get_order({
        'duration': "duration",
        'logs': "logs",
        'winrate': "winrate",
        'rating': "rating",
        'k30': "k30",
        'd30': "d30",
        'a30': "a30",
        'kd': "kd",
        'kad': "kad",
        'dpm': "dpm",
        'dtm': "dtm",
        'ddm': "ddm",
        'dr': "dr",
        'acc': "acc",
    }, 'rating')

    db = get_db()
    leaderboard = db.cursor()
    leaderboard.execute(f"""SELECT
                               name,
                               avatarhash,
                               steamid64,
                               duration,
                               logs,
                               winrate,
                               rating,
                               k30,
                               d30,
                               a30,
                               kd,
                               kad,
                               dpm,
                               dtm,
                               ddm,
                               dr,
                               acc
                           FROM (SELECT
                                   playerid,
                                   sum(duration) AS duration,
                                   sum(wins + losses + ties) AS logs,
                                   sum(0.5 * ties + wins) /
                                       sum(wins + losses + ties) AS winrate,
                                   (50 + sum(0.5 * ties + wins)) /
                                       (100 + sum(wins + losses + ties)) AS rating,
                                   sum(kills) * 30.0 * 60 / nullif(sum(duration), 0) AS k30,
                                   sum(deaths) * 30.0 * 60 / nullif(sum(duration), 0) AS d30,
                                   sum(assists) * 30.0 * 60 / nullif(sum(duration), 0) AS a30,
                                   sum(kills) * 1.0 / nullif(sum(deaths), 0) AS kd,
                                   (sum(kills) + sum(assists)) * 1.0 / nullif(sum(deaths), 0) AS kad,
                                   sum(dmg) * 60.0 / nullif(sum(duration), 0) AS dpm,
                                   sum(dt) * 60.0 / nullif(sum(duration), 0) AS dtm,
                                   (sum(dmg) - sum(dt)) * 60.0 / nullif(sum(duration), 0) AS ddm,
                                   sum(dmg) * 1.0 / nullif(sum(dt), 0) AS dr,
                                   sum(hits) * 1.0 / nullif(sum(shots), 0) AS acc
                               FROM leaderboard_cube
                               WHERE grouping = %(grouping)s
                                   {filter_clauses}
                                   {cube_clauses}
                               GROUP BY playerid
                               ORDER BY {order_clause} NULLS LAST
                               LIMIT %(limit)s OFFSET %(offset)s
                           ) AS leaderboard
                           LEFT JOIN player USING (playerid)
                           LEFT JOIN name USING (nameid)
                           ORDER BY {order_clause};""",
                        { **filters, 'grouping': grouping, 'limit': limit, 'offset': offset })
    resp = flask.make_response(flask.render_template("leaderboards/overview.html",
                               leaderboard=leaderboard.fetchall()))
    resp.cache_control.max_age = 3600
    return resp
