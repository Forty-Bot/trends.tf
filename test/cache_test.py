import collections

import pylibmc
import pytest

from trends.cache import cache_result

class MockClient:
    def __init__(self, responses, values):
        self.responses = responses
        self.values = values

    def _check(self, act_cmd, act_args, value=None):
        exp_cmd, exp_args, resp = self.responses.pop()
        assert act_cmd == exp_cmd
        assert act_args == exp_args
        self.values.append(value)
        if isinstance(resp, BaseException):
            raise resp
        return resp

    def gets(self, key):
        return self._check('gets', (key,))

    def add(self, key, value, time=0):
        return self._check('add', (key, time), value)

    def cas(self, key, value, cas, time=0):
        return self._check('cas', (key, cas, time), value)

class MockServer:
    def __init__(self, responses, values):
        self.responses = responses
        self.values = values

    def gets(self, key, value, cas):
        self.responses.appendleft(('gets', (key,), (value, cas)))

    def add(self, key, result, time=0):
        self.responses.appendleft(('add', (key, time), result))

    def cas(self, key, cas, result, time=0):
        self.responses.appendleft(('cas', (key, cas, time), result))

@pytest.fixture
def mock_cache():
    responses = collections.deque()
    values = []

    client = MockClient(responses, values)
    server = MockServer(responses, values)
    yield client, server

    assert not len(responses)

@cache_result('foo')
def one(mc):
    return 1

class E(Exception):
    pass

@cache_result('foo')
def error(mc):
    raise E

def test_hit(mock_cache):
    client, server = mock_cache
    server.gets('foo', 1, 0)
    assert error(client) == 1

def test_miss_fill(mock_cache):
    client, server = mock_cache
    server.gets('foo', None, None)
    server.add('foo', True, time=120)
    server.gets('foo', None, 0)
    server.cas('foo', 0, True, time=86400)
    assert one(client) == 1

def test_miss_error(mock_cache):
    client, server = mock_cache
    server.gets('foo', None, None)
    server.add('foo', True, time=120)
    server.gets('foo', None, 0)
    with pytest.raises(E):
        assert error(client)

def test_late_hit(mock_cache):
    client, server = mock_cache
    server.gets('foo', None, None)
    server.add('foo', False, time=120)
    server.gets('foo', 2, 0)
    assert one(client) == 2

def test_no_cas(mock_cache):
    client, server = mock_cache
    server.gets('foo', None, None)
    server.add('foo', True, time=120)
    server.gets('foo', None, None)
    assert one(client) == 1

def test_no_dummy(mock_cache):
    client, server = mock_cache
    server.gets('foo', None, None)
    server.add('foo', True, time=120)
    server.gets('foo', None, 0)
    server.cas('foo', 0, pylibmc.NotFound, time=86400)
    assert one(client) == 1
