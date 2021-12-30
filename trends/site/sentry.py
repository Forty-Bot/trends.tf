# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import blinker
import flask
import sentry_sdk
from sentry_sdk import Hub, tracing_utils
from sentry_sdk.integrations.flask import FlaskIntegration
import pkg_resources
import psycopg2.extras

try:
    version = pkg_resources.require("trends.tf")[0].version
except pkg_resources.DistributionNotFound:
    version = None

sentry_sdk.init(
    release=version,
    integrations=[FlaskIntegration()],
    traces_sample_rate=1
)

@flask.before_render_template.connect_via(blinker.ANY)
def trace_template_start(app, template, context):
    span = sentry_sdk.Hub.current.start_span(op='render', description=template.name)
    context['span'] = span
    span.set_data('context', context)
    span.__enter__()

@flask.template_rendered.connect_via(blinker.ANY)
def trace_template_finish(app, template, context):
    context['span'].__exit__(None, None, None)

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
