# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from contextlib import contextmanager
import logging

import pytest
from testing.postgresql import Postgresql

from trends.sql import db_connect
from .create import create_test_db

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
        with caplog_session(request) as caplog:
            with caplog.at_level(logging.ERROR):
                create_test_db(database.url())
            if caplog.records:
                pytest.fail("Error creating test database")

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
    cur.execute("""
        SELECT league, coalesce(rgl_teamid, teamid)
        FROM team_comp_backing
        GROUP BY 1, 2
        LIMIT 1000;""")
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
