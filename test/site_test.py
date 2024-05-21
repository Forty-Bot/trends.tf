# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

import collections
import random
import urllib.parse

from flask.testing import EnvironBuilder
import hypothesis
from hypothesis import assume, given, strategies as st
import pytest
from python_testing_crawler import Allow, Crawler, Rule, Request
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import HTTPException
from werkzeug.urls import url_encode

from trends.steamid import SteamID
from trends.site.wsgi import create_app
from trends.util import classes, leagues

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

class RandomEndpointSelector:
    def __init__(self, client, scale):
        builder = EnvironBuilder(client.application, environ_base=client.environ_base)
        self.mapper = client.application.url_map.bind_to_environ(builder.get_environ())
        self.scale = scale
        self.remaining = collections.defaultdict(lambda: scale)

    def __call__(self, node):
        try:
            path = urllib.parse.urlsplit(node.path).path
            endpoint, arguments = self.mapper.match(path_info=path, method=node.method)
        except HTTPException:
            endpoint = ''

        if random.randrange(0, self.scale) < self.remaining[endpoint]:
            self.remaining[endpoint] -= 1
            return True
        return False

def test_crawl(client):
    crawler = Crawler(
        client=client,
        initial_paths=('/',),
        path_attrs=('href', 'src'),
        rules=(
            Rule('a', '/.*', 'GET', Request()),
            Rule('a', '.*player.*', 'GET', Allow((404,))),
            Rule('link', '/.*', 'GET', Request()),
            Rule('img', '/.*', 'GET', Request()),
        ),
        should_process_handlers=(RandomEndpointSelector(client, 20),),
    )
    crawler.crawl()

    for node in crawler.graph.map.values():
        if node.requested:
            print(node.path)

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
@hypothesis.settings(deadline=1000)
def test_filter(client, logs, players, titles, maps, names, compids, teamids, comps, divids, data):
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
            "/medics",
            "/api/v1/players",
            "/api/v1/logs",
        )),
        st.builds(lambda league, rule: rule.format(league), st.sampled_from(leagues),
            st.sampled_from((
            "/league/{}/comps",
            "/league/{}/matches",
        ))),
        st.builds(lambda compid, rule: rule.format(*compid), st.sampled_from(compids),
            st.sampled_from((
            "/league/{}/comp/{}/matches",
            "/league/{}/comp/{}/players",
        ))),
        st.builds(lambda teamid, rule: rule.format(*teamid), st.sampled_from(teamids),
            st.sampled_from((
            "/league/{}/team/{}/roster",
            "/league/{}/team/{}/matches",
            "/league/{}/team/{}/player",
        ))),
    ))

    def as_timestamp(dt):
        return dt.timestamp()

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
        ('league', data.draw(st.sampled_from(('',) + leagues))),
        ('comp', data.draw(st.sampled_from(comps))),
        ('divid', data.draw(st.sampled_from(divids))),
        ('map', data.draw(substrings(st.sampled_from([''] + maps)))),
        ('title', data.draw(substrings(st.sampled_from([''] + titles)))),
        ('name', data.draw(substrings(st.sampled_from([''] + comps)))),
        ('timezone', data.draw(st.timezone_keys())),
        ('date_to', data.draw(st.one_of(st.just(''), st.dates().map(str)))),
        ('date_from', data.draw(st.one_of(st.just(''), st.dates().map(str)))),
        ('time_to', data.draw(st.one_of(st.just(''), st.datetimes().map(as_timestamp)))),
        ('time_from', data.draw(st.one_of(st.just(''), st.datetimes().map(as_timestamp)))),
        ('updated_since', data.draw(st.one_of(st.just(''), st.datetimes().map(as_timestamp)))),
        ('include_dupes', data.draw(st.sampled_from(('', 'yes', 'no')))),
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

linked_demos = {
    2297197: 273469,
    2297225: 273477,
    2344272: 292844,
    2344306: 292859,
    2344331: 292868,
    2344354: 292885,
    2401045: 318447,
    2408458: 322265,
    2408491: 322285,
    2506954: 375937,
    2844704: 585088,
    2878546: 609093,
    2931193: 640794,
    3069780: 737954,
    3124976: 776712,
    3302963: 902137,
    3302982: 902150,
}

linked_matches = {
    2344272: ('rgl', 3412),
    2344306: ('rgl', 3412),
    2344331: ('rgl', 3412),
    2344354: ('rgl', 3412),
    2344383: ('rgl', 3412),
    2344394: ('rgl', 3412),
    2392536: ('rgl', 4664),
    2392557: ('rgl', 4664),
    2408458: ('etf2l', 77326),
    2408491: ('etf2l', 77326),
    3302963: ('etf2l', 84221),
    3302982: ('etf2l', 84221),
}

def test_linked(connection):
    cur = connection.cursor()
    cur.execute("SELECT logid, demoid FROM log WHERE demoid NOTNULL;")
    assert { logid: demoid for logid, demoid in cur } == linked_demos

    cur.execute("SELECT logid, league, matchid FROM log WHERE league NOTNULL;")
    assert { logid: (league, matchid) for logid, league, matchid in cur } == linked_matches

duplicates = {
    2344394: [2344272, 2344306, 2344354],
}

def test_dupes(connection):
    cur = connection.cursor()
    cur.execute("SELECT logid, duplicate_of FROM log WHERE duplicate_of NOTNULL")
    assert { logid: duplicate_of for logid, duplicate_of in cur } == duplicates

def test_api_logs(client):
    def get(**params):
        resp = client.get("api/v1/logs", query_string=params)
        assert resp.status_code == 200
        resp = resp.json
        return resp['logs'], resp['next_page']

    logs, next_page = get()
    valid_keys = {
        'demoid',
        'duplicate_of',
        'duration',
        'format',
        'league',
        'logid',
        'map',
        'matchid',
        'time',
        'title',
        'updated',
    }

    updated_pivot = 0
    for log in logs:
        logid = log['logid']
        assert logid is not None

        assert set(log.keys()) == valid_keys

        unupdated = True
        if logid in linked_demos:
            assert log['demoid'] == linked_demos[logid]
            unupdated = False
        else:
            assert log['demoid'] is None

        if logid in linked_matches:
            assert (log['league'], log['matchid']) == linked_matches[logid]
            unupdated = False
        else:
            assert log['league'] is None
            assert log['matchid'] is None

        if logid in duplicates:
            assert log['duplicate_of'] == duplicates[logid]
            unupdated = False
        else:
            assert log['duplicate_of'] is None

        if unupdated:
            updated_pivot = max(updated_pivot, log['updated'])

    assert logs == sorted(logs, key=lambda log: log['logid'], reverse=True)
    assert next_page is None

    def paged(**args):
        args['offset'] = 0
        if 'limit' not in args:
            args['limit'] = 10
        while True:
            logs, next_page = get(**args)
            assert len(logs) <= args['limit']
            yield from logs

            if len(logs) < args['limit']:
                assert next_page is None
                return

            args['offset'] += args['limit']
            assert next_page == f"/api/v1/logs?{url_encode(args)}"

    assert logs == list(paged())
    assert get(offset=len(logs)) == ([], None)

    for log in get(view='players')[0]:
        assert set(log.keys()) == valid_keys | { 'red', 'blue' }
        for team in ('red', 'blue'):
            team = log[team]
            if log['league'] is None:
                assert team['teamid'] is None
            else:
                assert team['teamid'] is not None

            if log['league'] == 'rgl':
                assert team['rgl_teamid'] is not None
            else:
                assert team['rgl_teamid'] is None

            assert team['score'] is not None
            for player in team['players']:
                SteamID(player)

    for by in ('logid', 'date', 'duration'):
        key = lambda log: log['time' if by == 'date' else by]
        for reverse in (True, False):
            logs, _ = get(sort=by, sort_dir='desc' if reverse else 'asc')
            assert logs == sorted(logs, key=key, reverse=reverse)

    for log in get(league="etf2l")[0]:
        assert log['league'] == "etf2l"

    for log in get(format="sixes")[0]:
        assert log['format'] == "sixes"

    for log in get(title="serveme")[0]:
        assert "serveme" in log['title']

    for log in get(map="cp")[0]:
        assert "cp" in log['map']

    for log in get(date_from='2019-11-06', timezone='America/New_York')[0]:
        assert log['time'] >= 1573016400

    for log in get(date_to='2019-11-06', timezone='America/New_York')[0]:
        assert log['time'] <= 1573016400

    for log in get(time_from=1573016400)[0]:
        assert log['time'] >= 1573016400

    for log in get(time_to=1573016400)[0]:
        assert log['time'] <= 1573016400

    for log in get(updated_since=updated_pivot)[0]:
        assert log['updated'] > updated_pivot

    for log in get(include_dupes='no')[0]:
        assert log['duplicate_of'] is None

    for log in paged(view='players', limit=1, steamid64=[76561198330799279, 76561198046130018]):
        players = log['blue']['players'] + log['red']['players']
        assert "76561198330799279" in players
        assert "76561198046130018" in players
