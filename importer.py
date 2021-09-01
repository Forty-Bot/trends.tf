#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import argparse
import logging

from sql import db_connect, db_init
from import_logs import import_logs, create_logs_parser

def create_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    create_logs_parser(sub)
    parser.add_argument("database", default="postgresql:///trends", metavar="DATABASE",
                        help="Database URL to connect to")
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
    logging.basicConfig(level=log_level, format='[%(asctime)s] %(module)s: %(message)s')

def main():
    parser = create_parser()
    args = parser.parse_args()
    init_logging(args.verbosity)

    c = db_connect(args.database)
    db_init(c)

    args.importer(args, c)

if __name__ == '__main__':
    main()
