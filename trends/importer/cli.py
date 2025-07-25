# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import argparse
import logging
import sys

import psycopg2

from ..cache import mc_connect
from ..sql import db_connect, db_init
from ..util import sentry_init
from .demos import create_demos_parser
from .etf2l import create_etf2l_parser
from .logs import create_logs_parser
from .link_demos import create_link_demos_parser
from .link_matches import create_link_matches_parser
from .players import create_players_parser
from .refresh import create_refresh_parser
from .rgl import create_rgl_parser
from .weapons import create_weapons_parser

def create_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    create_demos_parser(sub)
    create_etf2l_parser(sub)
    create_link_demos_parser(sub)
    create_link_matches_parser(sub)
    create_logs_parser(sub)
    create_players_parser(sub)
    create_refresh_parser(sub)
    create_rgl_parser(sub)
    create_weapons_parser(sub)
    parser.add_argument("database", default="postgresql:///trends", metavar="DATABASE",
                        help="Database URL to connect to")
    parser.add_argument("memcached", default="127.0.0.1:11211", metavar="MEMCACHED",
                        help="A comma-separated list of memcached servers to connect to")
    parser.add_argument("-v", "--verbose", action='count', default=0, dest='verbosity',
                        help=("Print additional debug information. May be specified multiple "
                              "times for increased verbosity."))

    return parser

def init_logging(verbosity):
    log_level = logging.WARNING
    if verbosity == 1:
        log_level = logging.INFO
    elif verbosity > 1:
        log_level = logging.DEBUG
    if sys.stdout.isatty():
        fmt = '[%(asctime)s] %(module)s: %(message)s'
    else:
        fmt = '%(module)s: %(message)s'
    logging.basicConfig(level=log_level, format=fmt)

def main():
    parser = create_parser()
    args = parser.parse_args()
    init_logging(args.verbosity)
    sentry_init()

    c = db_connect(args.database)
    try:
        db_init(c)
    except psycopg2.Error:
        logging.exception("Could not load schema")
        with c.cursor() as cur:
            cur.execute("ROLLBACK;")

    mc = mc_connect(args.memcached)
    mc.get("connection_test")

    args.importer(args, c, mc)
