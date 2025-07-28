# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022, 25 Sean Anderson <seanga2@gmail.com>

from contextlib import contextmanager, closing
from datetime import datetime
import os
import shutil
import subprocess
import time

import pytest
from testing.postgresql import Postgresql

import trends
from trends.sql import db_connect, db_schema, db_init

@contextmanager
def memcached(tmpdir):
    socket = tmpdir / "sock"
    server = subprocess.Popen((shutil.which("memcached"), "-s", socket))
    while not socket.exists():
        time.sleep(0.001)
        if server.poll() is not None:
            raise RuntimeError(f"memcached exited early with code {server.returncode}")

    try:
        yield str(socket)
    finally:
        server.terminate()
        if server.wait():
            raise RuntimeError(f"memcached exited with non-zero code {server.returncode}")

@contextmanager
def caplog_session(request):
    request.node.add_report_section = lambda *args: None
    logging_plugin = request.config.pluginmanager.getplugin('logging-plugin')
    for _ in logging_plugin.pytest_runtest_setup(request.node):
       yield pytest.LogCaptureFixture(request.node, _ispytest=True)

@contextmanager
def database():
    postgres_args = Postgresql.DEFAULT_SETTINGS['postgres_args']
    postgres_args += " -c full_page_writes=off"
    with Postgresql(postgres_args=postgres_args) as database:
        with closing(db_connect(database.url())) as c:
            with open(f"{os.path.dirname(trends.__file__)}/bloom.sql") as bloom:
                c.cursor().execute(bloom.read())
            db_schema(c.cursor())
            db_init(c)
        yield database

def import_logs(url, mc, *logids):
    with db_connect(url) as c:
        logfiles = { logid: f"{os.path.dirname(__file__)}/logs/log_{logid}.json"
                     for logid in logids }
        fetcher = trends.importer.fetch.FileFetcher(logs=logfiles)
        trends.importer.logs.import_logs(c, mc, fetcher, False)

class SinceEpoch:
    since = datetime.fromtimestamp(0)

def import_demos(url, mc, *demoids):
    with db_connect(url) as c:
        demofiles = (f"{os.path.dirname(__file__)}/demos/demo_{demoid}.json" for demoid in demoids)
        fetcher = trends.importer.fetch.DemoFileFetcher(demos=demofiles)
        trends.importer.demos.import_demos(c, fetcher)

    with db_connect(url) as c:
        c.cursor().execute("ANALYZE;")
        trends.importer.link_demos.link_logs(SinceEpoch, c, mc)

def import_etf2l(url, mc, *matchids, link=True):
    def filter(c, results):
        for result in results:
            if result['id'] in matchids:
                yield result

    with db_connect(url) as c:
        fetcher = trends.importer.fetch.ETF2LFileFetcher(
            results=f"{os.path.dirname(__file__)}/etf2l/results.json",
            xferdir=f"{os.path.dirname(__file__)}/etf2l/")
        trends.importer.etf2l.import_etf2l(c, mc, fetcher, filter)
        if link:
            c.cursor().execute("ANALYZE;")
            trends.importer.link_matches.link_matches(SinceEpoch, c, mc)

def import_rgl(url, mc, *matchids, link=True):
    def filter(c, m):
        yield from matchids

    with db_connect(url) as c:
        fetcher = trends.importer.fetch.RGLFileFetcher(dir=f"{os.path.dirname(__file__)}/rgl")
        trends.importer.rgl.import_rgl(c, mc, fetcher, filter=filter)
        if link:
            c.cursor().execute("ANALYZE;")
            trends.importer.link_matches.link_matches(SinceEpoch, c, mc)

def refresh(url, mc):
    with db_connect(url) as c:
        c.cursor().execute("ANALYZE;")
        trends.importer.refresh.refresh(None, c, mc)
