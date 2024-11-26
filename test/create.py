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
    with db_connect(url) as c:
        mc = mc_connect(memcached)
        cur = c.cursor()
        db_schema(cur)
        db_init(c)

        logfiles = { logid: f"{os.path.dirname(__file__)}/logs/log_{logid}.json"
            for logid in (
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
                2344394,
                2392536,
                2392557,
                2401045,
                2408458,
                2408491,
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
                3302963,
                3302982,
                3384488,
            )
        }
        trends.importer.logs.import_logs(c, mc, FileFetcher(logs=logfiles), False)

    with db_connect(url) as c:
        demofiles = (f"{os.path.dirname(__file__)}/demos/demo_{demoid}.json" for demoid in (
            273469,
            273477,
            292844,
            292859,
            292868,
            292885,
            318447,
            322265,
            322285,
            375937,
            585088,
            609093,
            640794,
            737954,
            776712,
            902137,
            902150,
        ))
        trends.importer.demos.import_demos(c, DemoFileFetcher(demos=demofiles))

    with db_connect(url) as c:
        fetcher = ETF2LFileFetcher(results=f"{os.path.dirname(__file__)}/etf2l/results.json",
                                   xferdir=f"{os.path.dirname(__file__)}/etf2l/")
        trends.importer.etf2l.import_etf2l(c, mc, fetcher)

    with db_connect(url) as c:
        dir = f"{os.path.dirname(__file__)}/rgl"
        trends.importer.rgl.import_rgl(c, RGLFirstFetcher(dir=dir))
        trends.importer.rgl.import_rgl(c, RGLSecondFetcher(dir=dir),
                                       filter=trends.importer.rgl.no_filter_matchids)
    with db_connect(url) as c:
        cur = c.cursor()
        cur.execute("ANALYZE;")
        class args:
            since = datetime.fromtimestamp(0)
        trends.importer.link_demos.link_logs(args, c, mc)
        trends.importer.link_matches.link_matches(args, c, mc)
        cur.execute("ANALYZE;")
        # A second time to test partitioning log_json
        db_init(c)
        trends.importer.refresh.refresh(None, c, mc)

if __name__ == '__main__':
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"Usage: {sys.argv[0]} <database url> [<memcached urls>]", file=sys.stderr)
        sys.exit(1)

    create_test_db(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "")
