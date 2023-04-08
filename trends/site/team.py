# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

team = flask.Blueprint('team', __name__)

@team.route('/')
def overview(league, teamid):
    return ""
