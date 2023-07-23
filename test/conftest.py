# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from contextlib import contextmanager
from datetime import datetime
import os
import logging

import pytest
from testing.postgresql import Postgresql

import trends.importer.logs
import trends.importer.etf2l
import trends.importer.link_matches
from trends.importer.fetch import ETF2LFileFetcher, FileFetcher
from trends.sql import db_connect, db_init

@contextmanager
def caplog_session(request):
    request.node.add_report_section = lambda *args: None
    logging_plugin = request.config.pluginmanager.getplugin('logging-plugin')
    for _ in logging_plugin.pytest_runtest_setup(request.node):
       yield pytest.LogCaptureFixture(request.node, _ispytest=True)

@pytest.fixture(scope='session')
def database(request):
    postgres_args = Postgresql.DEFAULT_SETTINGS['postgres_args']
    postgres_args += " -c full_page_writes=off"
    with Postgresql(postgres_args=postgres_args) as database:
        # This must happen in a separate connection because we use temporary tables which will alias
        # other queries.
        with db_connect(database.url()) as c:
            db_init(c)
            cur = c.cursor()

            logfiles = { logid: f"{os.path.dirname(__file__)}/logs/log_{logid}.json"
                for logid in (
                    30099,
                    2344394,
                    2401045,
                    2408458,
                    2408491,
                    2600722,
                    2818814,
                    2844704,
                    2878546,
                    2931193,
                    3027588,
                    3069780,
                    3124976,
                    3384488,
                )
            }

            with caplog_session(request) as caplog:
                with caplog.at_level(logging.ERROR):
                    trends.importer.logs.import_logs(c, FileFetcher(logs=logfiles), False)
                if caplog.records:
                    pytest.fail("Error importing logs")

        with db_connect(database.url()) as c:
            fetcher = ETF2LFileFetcher(results=f"{os.path.dirname(__file__)}/etf2l/results.json",
                                       xferdir=f"{os.path.dirname(__file__)}/etf2l/")
            with caplog_session(request) as caplog:
                with caplog.at_level(logging.ERROR):
                    trends.importer.etf2l.import_etf2l(c, fetcher)
                if caplog.records:
                    pytest.fail("Error importing ETF2L files")

        with db_connect(database.url()) as c:
            cur = c.cursor()
            cur.execute("ANALYZE;")
            # A second time to test partitioning log_json
            db_init(c)
            cur.execute("REFRESH MATERIALIZED VIEW leaderboard_cube;")
            cur.execute("REFRESH MATERIALIZED VIEW map_popularity;")

        with db_connect(database.url()) as c:
            class args:
                since = datetime.fromtimestamp(0)
            trends.importer.link_matches.link_matches(args, c)

        yield database

@pytest.fixture(scope='session')
def connection(database):
    with db_connect(database.url()) as c:
        yield c

@pytest.fixture(scope='session')
def logs(connection):
    cur = connection.cursor()
    cur.execute("SELECT logid FROM log LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def players(connection):
    cur = connection.cursor()
    cur.execute("SELECT steamid64 FROM player LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def titles(connection):
    cur = connection.cursor()
    cur.execute("SELECT title FROM log LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def maps(connection):
    cur = connection.cursor()
    cur.execute("SELECT map FROM map LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def names(connection):
    cur = connection.cursor()
    cur.execute("SELECT name FROM name WHERE length(name) >= 3 LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def compids(connection):
    cur = connection.cursor()
    cur.execute("SELECT league, compid FROM competition LIMIT 1000;")
    return cur.fetchall()

@pytest.fixture(scope='session')
def teamids(connection):
    cur = connection.cursor()
    cur.execute("SELECT league, teamid FROM league_team LIMIT 1000;")
    return cur.fetchall()

@pytest.fixture(scope='session')
def comps(connection):
    cur = connection.cursor()
    cur.execute("SELECT name FROM competition LIMIT 1000;")
    return [row[0] for row in cur]

@pytest.fixture(scope='session')
def divids(connection):
    cur = connection.cursor()
    cur.execute("SELECT divid FROM division LIMIT 1000;")
    return [row[0] for row in cur]
