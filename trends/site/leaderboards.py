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
    log_clauses = get_filter_clauses(filters, logs='sum(wins + losses + ties)')

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
                               HAVING TRUE
                                   {log_clauses}
                               ORDER BY {order_clause} NULLS LAST
                               LIMIT %(limit)s OFFSET %(offset)s
                           ) AS leaderboard
                           LEFT JOIN player USING (playerid)
                           LEFT JOIN name USING (nameid)
                           ORDER BY {order_clause} NULLS LAST;""",
                        { **filters, 'grouping': grouping, 'limit': limit, 'offset': offset })
    resp = flask.make_response(flask.render_template("leaderboards/overview.html",
                               leaderboard=leaderboard.fetchall()))
    resp.cache_control.max_age = 3600
    return resp

@leaderboards.route('/medics')
def medics():
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'league', 'formatid', 'mapid')
    log_clauses = get_filter_clauses(filters, logs='sum(logs)')

    # Since we are using a cube, we need to explicitly select the NULL rows
    cube_clauses = []
    grouping = 0b0000
    for (name, column, group) in (
            ('map',    'mapid',    0b001),
            ('format', 'formatid', 0b010),
            ('league', 'league',   0b100),
    ):
        if not filters[name]:
            cube_clauses.append(f"AND {column} ISNULL")
            grouping |= group
    cube_clauses = '\n'.join(cube_clauses)

    order, order_clause = get_order({
        'logs': "logs",
        'ubers': "ubers",
        'drops': "drops",
        'ubers30': "ubers30",
        'drops30': "drops30",
        'lost30': "lost30",
        'medirate': "medirate",
        'kritzrate': "kritzrate",
        'otherrate': "otherrate",
        'droprate': "droprate",
        'avg_time_before_using': "avg_time_before_using",
        'avg_time_to_build': "avg_time_to_build",
        'avg_uber_duration': "avg_uber_duration",
        'hpm': "hpm",
        'hpm_scout': "hpm_scout",
        'hpm_soldier': "hpm_soldier",
        'hpm_pyro': "hpm_pyro",
        'hpm_demoman': "hpm_demoman",
        'hpm_engineer': "hpm_engineer",
        'hpm_heavyweapons': "hpm_heavyweapons",
        'hpm_medic': "hpm_medic",
        'hpm_sniper': "hpm_sniper",
        'hpm_spy': "hpm_spy",
        'hpm_other': "hpm_other",
        'duration': "duration",
    }, 'drops')

    db = get_db()
    medics = db.cursor()
    medics.execute(f"""SELECT
                           name,
                           avatarhash,
                           steamid64,
                           logs,
                           ubers,
                           drops,
                           ubers30,
                           drops30,
                           lost30,
                           medirate,
                           kritzrate,
                           otherrate,
                           droprate,
                           avg_time_before_using,
                           avg_time_to_build,
                           avg_uber_duration,
                           hpm,
                           hpm_scout,
                           hpm_soldier,
                           hpm_pyro,
                           hpm_demoman,
                           hpm_engineer,
                           hpm_heavyweapons,
                           hpm_medic,
                           hpm_sniper,
                           hpm_spy,
                           hpm_other,
                           duration
                       FROM (SELECT
                               playerid,
                               sum(logs) AS logs,
                               sum(ubers) AS ubers,
                               sum(drops) AS drops,
                               sum(ubers) * 30.0 * 60 / nullif(sum(duration), 0) AS ubers30,
                               sum(drops) * 30.0 * 60 / nullif(sum(duration), 0) AS drops30,
                               sum(advantages_lost) * 30.0 * 60 / nullif(sum(duration), 0) AS lost30,
                               sum(medigun_ubers) /
                                   nullif(sum(medigun_ubers + kritz_ubers + other_ubers), 0)
                                   AS medirate,
                               sum(kritz_ubers) /
                                   nullif(sum(medigun_ubers + kritz_ubers + other_ubers), 0)
                                   AS kritzrate,
                               sum(other_ubers) /
                                   nullif(sum(medigun_ubers + kritz_ubers + other_ubers), 0)
                                   AS otherrate,
                               sum(drops) / nullif(sum(ubers + drops), 0) AS droprate,
                               sum(time_before_using) /
                                   nullif(sum(ubers_before_using), 0) AS avg_time_before_using,
                               sum(time_to_build) / nullif(sum(builds), 0) AS avg_time_to_build,
                               sum(uber_duration) /
                                   nullif(sum(ubers_duration), 0) AS avg_uber_duration,
                               sum(healing) * 60.0 / nullif(sum(healing_duration), 0) AS hpm,
                               sum(healing_scout) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_scout,
                               sum(healing_soldier) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_soldier,
                               sum(healing_pyro) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_pyro,
                               sum(healing_demoman) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_demoman,
                               sum(healing_engineer) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_engineer,
                               sum(healing_heavyweapons) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_heavyweapons,
                               sum(healing_medic) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_medic,
                               sum(healing_sniper) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_sniper,
                               sum(healing_spy) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_spy,
                               sum(healing_other) * 60.0 /
                                   nullif(sum(healing_duration), 0) AS hpm_other,
                               sum(duration) AS duration
                           FROM medic_cube
                           WHERE grouping = %(grouping)s
                               {filter_clauses}
                               {cube_clauses}
                           GROUP BY playerid
                           HAVING TRUE
                               {log_clauses}
                           ORDER BY {order_clause} NULLS LAST
                           LIMIT %(limit)s OFFSET %(offset)s
                       ) AS medics
                       LEFT JOIN player USING (playerid)
                       LEFT JOIN name USING (nameid)
                       ORDER BY {order_clause} NULLS LAST;""",
                        { **filters, 'grouping': grouping, 'limit': limit, 'offset': offset })
    resp = flask.make_response(flask.render_template("leaderboards/medics.html",
                               medics=medics.fetchall()))
    resp.cache_control.max_age = 3600
    return resp
