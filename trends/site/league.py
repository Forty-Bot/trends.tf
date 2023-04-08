# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

from .comp import comp
from .team import team

league = flask.Blueprint('league', __name__)
league.register_blueprint(comp, url_prefix='/comp/<int:compid>')
league.register_blueprint(team, url_prefix='/team/<int:teamid>')

@league.route('/comps')
def comps(league):
    return ""
