#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import flask

from sql import db_connect

def get_db():
    if not getattr(flask.g, 'db_conn', None):
        flask.g.db_conn = db_connect(flask.current_app.config['DATABASE'])
    return flask.g.db_conn

def put_db(exception):
    db = getattr(flask.g, 'db_conn', None)
    if db:
        db.close()

class DefaultConfig:
    DATABASE = "logs.db"

def main():
    from player import player
    from root import root

    app = flask.Flask(__name__)
    app.config.from_object(DefaultConfig)
    app.config.from_envvar('CONFIG', silent=True)

    app.teardown_appcontext(put_db)

    app.register_blueprint(root)
    app.register_blueprint(player, url_prefix='/player/<int:steamid>')

    app.run()

if __name__ == '__main__':
    main()
