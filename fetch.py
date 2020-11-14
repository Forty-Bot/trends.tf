# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import itertools
import json
import logging
import requests
import time

class APIError(OSError):
    """The logs.tf API returned a failure"""
    def __init__(self, msg):
        super().__init__("logs.tf API request failed: %s".format(msg))

def fetch_players_logids(s, players=None, since=0, count=None, offset=0, limit=1000):
    """Fetch some logids from logs.tf.

    Any network or parsing are caught and logged.

    :param requests.Session s: Session to use
    :param players: Steam ids that fetched log ids must include
    :type players: iterable of SteamIDs
    :param int since: Unix time of the earliest logs ids to fetch
    :param int count: Number of log ids to fetch consider; may be reduced by since
    :param int offset: Number of logs to skip
    :param int limit: Largest page to fetch at once
    :return: The fetched log ids
    :rtype: iterable of ints
    """

    # Number of logids fetched
    fetched = 0
    # logs added since we started enumerating
    extra = offset
    total = None

    try:
        while True:
            player_param = ""
            if players:
                player_param = "&player={}".format((",".join((str(player) for player in players))))
            limit_param = min(count - fetched, limit) if count is not None else limit
            url = "https://logs.tf/api/v1/log?offset={}&limit={}{}"
            url = url.format(fetched + extra, limit_param, player_param)

            resp = s.get(url)
            resp.raise_for_status()
            log_list = resp.json()
            if not log_list['success']:
                raise APIError(log_list['error'])

            for log in log_list['logs']:
                if log['date'] >= since:
                    yield log['id']
                else:
                    # Don't fetch any more pages
                    count = fetched

            # Keep track if new logs get added while we are iterating
            if total:
                extra += log_list['total'] - total
            total = log_list['total']
            if count is None:
                count = total

            fetched += log_list['results']
            if fetched >= count or fetched + extra >= total:
                break
    except OSError:
        logging.exception("Could not fetch log list")
    except (ValueError, KeyError):
        logging.exception("Could not parse log list")

class Fetcher:
    """Generic abstraction of different ways to fetch logs"""
    def __init__(self, **kwargs):
        pass

    def fetch_logids(self):
        """Fetch log ids, to be passed to ``fetch_log``

        :return: log ids to fetch
        :rtype: iterable of int
        """
        return iter(())

    def fetch_log(self, logid):
        """Fetch and parse one log

        :param int logid: The log's id
        :return: The parsed log or None
        """
        None

class ListFetcher(Fetcher):
    """Fetcher for a list of log ids for logs to get from logs.tf"""
    def __init__(self, logids=None, **kwargs):
        """Create a ``ListFetcher``

        :param logids: List of log ids
        :type logids: iteratable of ints
        """

        def retry_hook(resp, *args, **kwargs):
            """Retry a request when asked to back off

            :param requests.Response resp: The response to the request to (possibly) retry
            :return: The retried response (or ``resp`` if we give up)
            :rtype: requests.Response
            """

            if resp.status_code != requests.codes.too_many:
                return resp

            retries = getattr(resp.request, 'retries', 0)
            if retries > 4:
                return resp

            # This dance is taken from requests/auth.py
            resp.content
            resp.close()
            new_request = resp.request.copy()
            new_request.retries = retries + 1
            time.sleep(0.1 * (2 ** retries))

            new_resp = resp.connection.send(new_request, **kwargs)
            new_resp.history.append(resp)
            new_resp.request = new_request
            return new_resp

        self.s = requests.Session()
        self.s.hooks['response'].append(retry_hook)
        self.logids = logids if logids is not None else iter(())
        super().__init__(**kwargs)

    def get_logids(self):
        return self.logids

    def get_log(self, logid):
        try:
            url = "https://logs.tf/api/v1/log/{}".format(logid)
            resp = self.s.get(url)
            resp.raise_for_status()
            log = resp.json()
            if not log['success']:
                raise APIError(log['error'])
            return log
        except OSError:
            logging.exception("Could not fetch log %s", logid)
        except (ValueError, KeyError):
            logging.exception("Could not parse log %s", logid)

class BulkFetcher(ListFetcher):
    """Fetcher for parameters of logs to get from logs.tf"""
    def __init__(self, players=None, since=None, count=None, offset=None, **kwargs):
        """Create a ``ListFetcher``

        :param players: Steam ids that fetched log ids must include
        :type players: iterable of SteamIDs
        :param int since: Unix time of the earliest logs ids to fetch
        :param int count: Number of log ids to fetch
        """

        self.players = players
        self.since = since.timestamp()
        self.count = count
        self.offset = offset
        super().__init__(**kwargs)

    def get_logids(self):
        return fetch_players_logids(self.s, players=self.players, since=self.since,
                                    count=self.count, offset=self.offset)

class FileFetcher(Fetcher):
    """Fetcher for logs from local files"""
    def __init__(self, logs=None, **kwargs):
        """Create a ``FileFetcher``

        :param logs: Log ids and their filenames
        :type logs: (int, str)
        """

        self.logs = logs
        super().__init__(**kwargs)

    def get_logids(self):
        return self.logs.keys()

    def get_log(self, logid):
        with open(self.logs[logid]) as logfile:
            return json.load(logfile)
