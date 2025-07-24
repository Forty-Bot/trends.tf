#!/usr/bin/env python3

from datetime import datetime
import os
import sys

from trends.cache import mc_connect
import trends.importer.demos
import trends.importer.logs
import trends.importer.etf2l
import trends.importer.link_demos
import trends.importer.link_matches
import trends.importer.refresh
import trends.importer.rgl
from trends.importer.fetch import DemoFileFetcher, ETF2LFileFetcher, FileFetcher, RGLFileFetcher
from trends.sql import db_connect, db_init, db_schema

from . import util

# Pretend these two teams aren't linked so we can test combining them
class RGLFirstFetcher(RGLFileFetcher):
    def get_team(self, teamid):
        ret = super().get_team(teamid)
        if teamid == 5574:
            ret['linkedTeams'] = []
            ret['fetched'] = 1
        if teamid == 4882:
            ret['linkedTeams'] = []
            ret['fetched'] = 1
        return ret

class RGLSecondFetcher(RGLFileFetcher):
    def get_matchids(self):
        yield 4664

def create_test_db(url, memcached):
    # We use separate connections for importing because we use temporary tables which will alias
    # other queries.
    mc = mc_connect(memcached)
    with db_connect(url) as c:
        cur = c.cursor()
        db_schema(cur)
        db_init(c)

    util.import_logs(url, mc,
        30099,
        2297197,
        2297225,
        2297265,
        2344272,
        2344306,
        2344331,
        2344354,
        2344383,
        2344394,
        2392536,
        2392557,
        2401045,
        2408458,
        2408491,
        2426167,
        2426192,
        2500876,
        2506954,
        2600722,
        2818814,
        2844704,
        2878546,
        2931193,
        3027588,
        3069780,
        3124976,
        3192416,
        3200287,
        3302963,
        3302982,
        3384488,
    )

    util.import_demos(url, mc,
        273469,
        273477,
        292844,
        292859,
        292868,
        292885,
        318447,
        322265,
        322285,
        331371,
        375937,
        585088,
        609093,
        640794,
        737954,
        776712,
        902137,
        902150,
    )

    util.import_etf2l(url, mc,
            1,
            2,
           10,
           34,
           51,
           53,
          812,
         7976,
         7977,
        14773,
        34005,
        77318,
        77326,
        84221,
        88524,
    )

    util.import_rgl(url, mc,
         3009,
         3058,
         3099,
         3412,
         4664,
        26935,
    )

    util.refresh(url, mc)

if __name__ == '__main__':
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"Usage: {sys.argv[0]} <database url> [<memcached urls>]", file=sys.stderr)
        sys.exit(1)

    create_test_db(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "")
