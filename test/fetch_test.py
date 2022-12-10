# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2022 Sean Anderson <seanga2@gmail.com>

from datetime import datetime
import re
import json

import hypothesis
from hypothesis import given, strategies as st
import pytest
import responses, responses.registries

from trends.importer.fetch import ListFetcher, BulkFetcher, ReverseFetcher, DemoBulkFetcher

def response_200(logid):
    return responses.Response(method=responses.GET, url=f"https://logs.tf/api/v1/log/{logid}",
                              json={'success': True}, status=200)

def response_404(logid):
    return responses.Response(method=responses.GET, url=f"https://logs.tf/api/v1/log/{logid}",
                              json={'success': False, 'error': "Log not found."}, status=404)

def response_429(logid):
    return responses.Response(method=responses.GET, url=f"https://logs.tf/api/v1/log/{logid}",
                              content_type='text/html', status=429)

@responses.activate
def test_list():
    responses.add(response_200(1))
    responses.add(response_404(2))
    fetcher = ListFetcher(logids=iter((1, 2)))

    logids = fetcher.get_ids()
    assert next(logids) == 1
    assert fetcher.get_data(1)
    assert next(logids) == 2
    assert fetcher.get_data(2) is None
    with pytest.raises(StopIteration):
        next(logids)

    assert len(responses.calls) == 2

@pytest.mark.skip(reason="Waiting on https://github.com/getsentry/responses/pull/563")
#@responses.activate(registry=responses.registries.OrderedRegistry)
def test_retry():
    responses.add(response_429(1))
    responses.add(response_429(1))
    responses.add(response_429(1))
    responses.add(response_429(1))
    responses.add(response_200(1))
    responses.add(response_429(2))
    responses.add(response_429(2))
    responses.add(response_429(2))
    responses.add(response_429(2))
    responses.add(response_429(2))

    fetcher = ListFetcher()
    assert fetcher.get_data(1)
    assert fetcher.get_data(2) is None
    assert len(responses.calls) == 10

@responses.activate
def test_reverse():
    responses.add(method=responses.GET, url="https://logs.tf/api/v1/log",
                  json={'success': True, 'logs': [{'id': 10}]})

    assert ReverseFetcher().get_ids() == range(10, 0, -1)

def integers(bits):
    return st.integers(0, (1 << bits) - 1)

def timestamp_ok(dt):
    try:
        dt.timestamp()
    except:
        return False
    return True

@st.composite
def bulk_args(draw):
    logs = draw(st.dictionaries(integers(64), integers(32), min_size=10, max_size=200))
    logs = sorted(logs.items(), reverse=True)
    pagesize = draw(st.integers(1, len(logs)))
    offset = draw(st.integers(0, len(logs)))
    growth = draw(st.integers(0, pagesize - 1))
    count = draw(st.integers(1, 2 * len(logs) + 1))
    since = draw(st.none() | st.datetimes().filter(timestamp_ok))
    if since is None:
        since = datetime.fromtimestamp(0)

    return { k: v for k, v in locals().items() if k != 'draw' }

@given(args=bulk_args())
@responses.activate
def test_bulk(args):
    fetcher = BulkFetcher(**args)
    # Make a copy so we can still see the original parameters on failure
    logs = args['logs'][:]
    pagesize = args['pagesize']
    growth = args['growth']
    count = args['count']
    offset = args['offset']
    since = args['since'].timestamp()

    def get_data(request):
        offset = int(request.params['offset'])
        limit = int(request.params['limit'])

        resp_logs = logs[offset:offset+min(limit, pagesize)]
        resp = {
            'success': True,
            'results': len(resp_logs),
            'total': len(logs),
            'logs': [{ 'id': log[0], 'date': log[1] } for log in resp_logs]
        }

        for _ in range(growth):
            first = logs[0]
            logs.insert(0, (first[0] + 1, first[1] + 1))

        return 200, {'content_type': 'application/json'}, json.dumps(resp)

    responses.add_callback(method=responses.GET,
                           url=re.compile(r"https://logs.tf/api/v1/log.*"),
                           callback=get_data)

    logids = list(fetcher.get_ids())
    assert len(logids) <= count
    if not since:
        assert logids == args['logs'][offset:offset+count]

    last_logid = None
    for logid in logids:
        assert logid[1] >= since
        if last_logid is not None:
            assert logid[0] < last_logid
        last_logid = logid[0]

@st.composite
def demo_args(draw):
    demos = draw(st.lists(integers(32), min_size=10, max_size=200, unique=True))
    demos = sorted(demos, reverse=True)
    pagesize = draw(st.integers(1, 50))
    growth = draw(st.integers(0, pagesize - 1))
    count = draw(st.integers(1, 2 * len(demos) + 1))

    return { k: v for k, v in locals().items() if k != 'draw' }

@given(args=demo_args())
@responses.activate
def test_demo(args):
    # Make a copy so we can still see the original parameters on failure
    demos = args['demos'][:]
    pagesize = args['pagesize']
    growth = args['growth']
    count = args['count']
    fetcher = DemoBulkFetcher(count=count)

    def get_demo(request):
        page = int(request.params['page'])

        resp_demos = demos[(page - 1) * pagesize:page * pagesize]
        resp = [{ 'id': demo } for demo in resp_demos]

        for _ in range(growth):
            demos.insert(0, demos[0] + 1)

        return 200, {'content_type': 'application/json'}, json.dumps(resp)

    responses.add_callback(method=responses.GET,
                           url=re.compile(r"https://api.demos.tf/demos.*"),
                           callback=get_demo)

    demoids = list(fetcher.get_ids())
    assert demoids == args['demos'][:count]

    last_demoid = None
    for demoid in demoids:
        if last_demoid is not None:
            assert demoid < last_demoid
        last_demoid = demoid
