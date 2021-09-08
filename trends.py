#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

from decimal import Decimal
import gettext

import flask
import werkzeug.routing

from api import api
from player import player
from root import root
from sql import db_connect, db_init, get_db, put_db

class DefaultConfig:
    DATABASE = "postgresql:///trends"
    TIMEOUT = 60000

def json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError("Object of type '{}' is not JSON serializable" \
                    .format(type(obj).__name__))

def create_app():
    app = flask.Flask(__name__)
    app.config.from_object(DefaultConfig)
    app.config.from_envvar('CONFIG', silent=True)

    app.teardown_appcontext(put_db)
    app.add_template_filter(any)
    app.add_template_filter(all)

    app.jinja_options['trim_blocks'] = True
    app.jinja_options['lstrip_blocks'] = True
    app.jinja_env.policies["json.dumps_kwargs"] = { 'default': json_default }
    app.jinja_env.globals.update(zip=zip)
    app.jinja_env.add_extension('jinja2.ext.do')
    app.jinja_env.add_extension('jinja2.ext.i18n')
    app.jinja_env.install_null_translations(newstyle=True)

    app.register_blueprint(root)
    app.register_blueprint(player, url_prefix='/player/<int:steamid>')
    app.register_blueprint(api, url_prefix='/api/v1')

    return app

application = create_app()

@application.template_filter('duration')
def duration_filter(timestamp):
    mm, ss = divmod(timestamp, 60)
    hh, mm = divmod(mm, 60)
    dd, hh = divmod(hh, 24)
    if dd:
        return "{:.0f} day{}, {:.0f}:{:02.0f}:{:02.0f}" \
               .format(dd, "s" if dd > 1 else "", hh, mm, ss)
    elif hh:
        return "{:.0f}:{:02.0f}:{:02.0f}".format(hh, mm, ss)
    else:
        return "{:.0f}:{:02.0f}".format(mm, ss)

@application.template_filter('avatar')
def avatar_filter(hash, size='full'):
    if not hash:
        return ''
    url = "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/avatars/{}/{}{}.jpg"
    return url.format(hash[0:2], hash, {
            'small': '',
            'medium': '_medium',
            'full': '_full',
        }[size])

@application.template_filter()
def anynone(iterable):
    for item in iterable:
        if item is None:
            return False
    return True

if __name__ == '__main__':
    application.run()
