# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

from .comp import comp
from .team import team
from .util import get_db, get_filter_params, get_filter_clauses, get_order, get_pagination
from ..util import leagues

league = flask.Blueprint('league', __name__)
league.register_blueprint(comp, url_prefix='/comp/<int:compid>')
league.register_blueprint(team, url_prefix='/team/<int:teamid>')

@league.url_value_preprocessor
def get_league(endpoint, values):
    flask.g.league = values['league']

@league.before_request
def verify_league():
    if flask.g.league not in leagues:
        flask.abort(404)

@league.route('/comps')
def comps(league):
    limit, offset = get_pagination()
    filters = get_filter_params()
    filter_clauses = get_filter_clauses(filters, 'name', 'format', 'timespan')
    order, order_clause = get_order({
        'compid': "compid",
        'from': "comp_match.from",
        'to': "comp_match.to",
    }, 'compid')

    db = get_db()
    comps = db.cursor()
    comps.execute(
        """SELECT
               compid,
               name,
               format,
               comp_match.from,
               comp_match.to,
               coalesce(divs, ARRAY[]::JSON[]) AS divs
           FROM competition
           JOIN format USING (formatid)
           LEFT JOIN (SELECT
               league,
               compid,
               array_agg(json_build_object(
                   'divid', divid,
                   'name', division,
                   'from', div_match.from,
                   'to', div_match.to
               ) ORDER BY tier ASC, divid ASC) AS divs
               FROM division
               JOIN div_name USING (div_nameid)
               LEFT JOIN (SELECT
                       league,
                       compid,
                       divid,
                       min(scheduled) AS from,
                       max(scheduled) AS to
                   FROM match
                   GROUP BY league, compid, divid
               ) AS div_match USING (league, compid, divid)
               GROUP BY league, compid
           ) AS division USING (league, compid)
           LEFT JOIN (SELECT
                   league,
                   compid,
                   min(scheduled) AS from,
                   max(scheduled) AS to,
                   int8range(min(scheduled), max(scheduled)) AS timespan
               FROM match
               GROUP BY league, compid
           ) AS comp_match USING (league, compid)
           WHERE league = %(league)s
               {}
           ORDER BY {} NULLS LAST
           LIMIT %(limit)s OFFSET %(offset)s;""".format(filter_clauses, order_clause),
       { 'limit': limit, 'offset': offset, **filters, 'league': league, })

    return flask.render_template("league/comps.html", comps=comps.fetchall())
