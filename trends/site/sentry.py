# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import sys

import blinker
import flask
import sentry_sdk
from sentry_sdk import Hub, tracing_utils
from sentry_sdk.integrations.flask import FlaskIntegration
import pkg_resources
import psycopg2.extras

@flask.before_render_template.connect_via(blinker.ANY)
def trace_template_start(app, template, context):
    span = sentry_sdk.start_span(op='render', description=template.name)
    span.set_data('context', context)
    flask.g.span = span
    span.__enter__()

@flask.template_rendered.connect_via(blinker.ANY)
def trace_template_finish(app, template, context):
    flask.g.pop('span').__exit__(None, None, None)

@flask.got_request_exception.connect_via(blinker.ANY)
def trace_template_error(app, exception):
    if span := flask.g.pop('span', None):
        span.__exit__(*sys.exc_info())

class TracingCursor(psycopg2.extras.DictCursor):
    def _log(self, query, vars, paramstyle=psycopg2.paramstyle):
        return tracing_utils.record_sql_queries(Hub.current, self, query, vars,
                                                paramstyle, False)

    def execute(self, query, vars=None):
        with self._log(query, vars):
            super().execute(query, vars)

    def callproc(self, procname, vars=None):
        with self._log(procname, vars, paramstyle=None):
            super().callproc(procname, vars)
