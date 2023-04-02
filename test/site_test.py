# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import random

import hypothesis
from hypothesis import assume, given, strategies as st
import pytest
from python_testing_crawler import Crawler, Rule, Request
from werkzeug.datastructures import MultiDict

from trends.site.wsgi import create_app
from trends.util import classes

@pytest.fixture(scope='session')
def app(database):
    app = create_app()
    app.config.update({
        'TESTING': True,
        'DATABASE': database.url(),
        'MEMCACHED_SERVERS': "",
    })
    return app

@pytest.fixture(scope='session')
def client(app):
    return app.test_client()

class RandomSelector:
    def __init__(self, scale):
        self.scale = scale
        self.remaining = scale

    def __call__(self, node):
        if random.randrange(0, self.scale) < self.remaining:
            self.remaining -= 1
            return True
        return False

def test_crawl(client):
    crawler = Crawler(
        client=client,
        initial_paths=('/',),
        path_attrs=('href', 'src'),
        rules=(
            Rule('a', '/.*', 'GET', Request()),
            Rule('link', '/.*', 'GET', Request()),
            Rule('img', '/.*', 'GET', Request()),
        ),
        should_process_handlers=(RandomSelector(100),),
    )
    crawler.crawl()

    for node in crawler.graph.map.values():
        if node.requested:
            print(node.path)

class PlayerPage:
    def __init__(self, endpoint):
        self.endpoint = endpoint

@st.composite
def substrings(draw, strings, min_size=0):
    s = draw(strings)
    l = len(s)
    assume(l >= min_size)
    start = draw(st.integers(0, l - min_size))
    # Integers shrink to 0, so try and shrink to the whole string
    end = l - draw(st.integers(0, l - start - min_size))
    return s[start:end]

@given(st.data())
def test_filter(client, logs, players, titles, maps, names, data):
    players = st.sampled_from(players).map(str)

    path = data.draw(st.one_of(
        st.builds(lambda steamid, rule: rule.format(steamid), players, st.sampled_from((
            "/player/{}",
            "/player/{}/logs",
            "/player/{}/maps",
            "/player/{}/peers",
            "/player/{}/trends",
            "/player/{}/totals",
            "/player/{}/weapons",
        ))),
        st.lists(st.sampled_from(logs).map(str))
            .map(lambda logs: "/log/{}".format("+".join(logs))),
        st.sampled_from((
            "/search",
            "/logs",
            "/leaderboard",
            "/api/v1/players",
            "/api/v1/logs",
        )),
    ))

    params = MultiDict([
        ('class', data.draw(st.sampled_from(('',) + classes))),
        ('format', data.draw(st.sampled_from((
            '',
            'ultiduo',
            'fours',
            'sixes',
            'prolander',
            'highlander',
            'other',
        )))),
        ('map', data.draw(substrings(st.sampled_from([''] + maps)))),
        ('title', data.draw(substrings(st.sampled_from([''] + titles)))),
        ('timezone', data.draw(st.timezone_keys())),
        ('date_to_ts', data.draw(st.one_of(st.just(''), st.datetimes().map(str)))),
        ('date_from_ts', data.draw(st.one_of(st.just(''), st.datetimes().map(str)))),
        ('q', data.draw(st.one_of(players, substrings(st.sampled_from(names))))),
    ] + [('steamid64', steamid) for steamid in data.draw(st.lists(players))])

    hypothesis.note(f"path={path} params={params}")
    assert client.get(path, query_string=params, follow_redirects=True).status_code < 500

def test_search(client, connection):
    players = connection.cursor()
    players.execute("""SELECT steamid64, name
                       FROM player_stats
                       JOIN name USING (nameid)
                       JOIN player USING (playerid)
                       LIMIT 10""")
    players = players.fetchall()

    for path in ("/search", "/api/v1/players"):
        for i in range(3):
            assert client.get(path, query_string={'q': 'x' * i}).status_code == 400

        for player in players:
            if path == "/search":
                resp = client.get(path, query_string={'q': player['steamid64']},
                                  follow_redirects=True)
                assert resp.history

            if len(player['name']) > 3:
                resp = client.get(path, query_string={'q': player['name']})
                assert str(player['steamid64']) in resp.get_data(as_text=True)
