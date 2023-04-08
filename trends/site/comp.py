# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2023 Sean Anderson <seanga2@gmail.com>

import flask

comp = flask.Blueprint('comp', __name__)

@comp.route('/')
def overview(league, compid):
    return ""
