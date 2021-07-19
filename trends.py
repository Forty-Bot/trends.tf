#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

from decimal import Decimal
import flask

from api import api
from player import player
from root import root
from sql import db_connect, db_init, get_db, put_db

class DefaultConfig:
    DATABASE = "postgresql://localhost/trends"

def json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError("Object of type '{}' is not JSON serializable" \
                    .format(type(obj).__name__))

def create_app():
    app = flask.Flask(__name__)
    app.config.from_object(DefaultConfig)
    app.config.from_envvar('CONFIG', silent=True)

    with db_connect(app.config['DATABASE']) as c:
        db_init(c)

    app.teardown_appcontext(put_db)

    app.register_blueprint(root)
    app.register_blueprint(player, url_prefix='/player/<int:steamid>')
    app.register_blueprint(api, url_prefix='/api/v1')

    app.jinja_env.policies["json.dumps_kwargs"] = { 'default': json_default }
    app.jinja_env.globals.update(zip=zip)

    return app

application = create_app()

if __name__ == '__main__':
    application.run()
