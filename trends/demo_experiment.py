from time import perf_counter

from .sql import db_connect

def int_to_params(x):
    params = {
        'subquery_log': x & 0x80,
        'subquery_demo': x & 0x40,
        'subquery_id': x & 0x20,
        'between_log': x & 0x10,
        'log_time': x & 0x08,
        'demo_time': x & 0x04,
        'log_id': x & 0x02,
        'demo_id': x & 0x01,
    }
    return { key: bool(val) for key, val in params.items() }

def build_query(params):
    query = [
            "EXPLAIN (ANALYZE, BUFFERS, TIMING)",
            "SELECT logid, demo.demoid",
            "FROM log"
    ]

    if params['subquery_log']:
        query.append("JOIN (SELECT")
        query.append("\t\tlogid, array_agg(steamid64) AS players")
        query.append("\tFROM player_stats")
        clauses = []
        if params['subquery_id']:
            clauses.append("logid > 3200000")
        if clauses:
            query.append("\tWHERE {}".format('\n\t\tAND '.join(clauses)))
        query.append("\tGROUP BY logid")
        query.append(") AS log_players USING (logid)")

    query.append("CROSS JOIN demo")
    if params['subquery_demo']:
        query.append("JOIN (SELECT")
        query.append("\t\tdemoid, array_agg(steamid64) AS players")
        query.append("\tFROM demo_player_stats")
        clauses = []
        if params['subquery_id']:
            clauses.append("demoid > 841000")
        if clauses:
            query.append("\tWHERE {}".format('\n\t\tAND '.join(clauses)))
        query.append("\tGROUP BY demoid")
        query.append(") AS demo_players ON (demo_players.demoid=demo.demoid)")

    log_players = "log_players.players" if params['subquery_log'] else "log.players"
    demo_players = "demo_players.players" if params['subquery_demo'] else "demo.players"
    clauses = [f"({log_players} @> {demo_players} OR {demo_players} @> {log_players})"]
    if params['between_log']:
        clauses.append("log.time BETWEEN demo.time - 300 AND demo.time + 300")
    else:
        clauses.append("demo.time BETWEEN log.time - 300 AND log.time + 300")
    if params['log_time']:
        clauses.append("log.time BETWEEN 1656150734 AND 1656301497")
    if params['demo_time']:
        clauses.append("demo.time BETWEEN 1656117787 AND 1656290307")
    if params['log_id']:
        clauses.append("logid > 3200000")
    if params['demo_id']:
        clauses.append("demo.demoid > 841000")
    query.append("WHERE {}".format("\n\tAND ".join(clauses)))
    return "{};".format("\n".join(query))

if __name__ == '__main__':
    c = db_connect("postgresql:///trends")
    cur = c.cursor()
    results = []
    print(','.join(int_to_params(0)))
    for x in range(2 ** len(int_to_params(0)) - 1, 0, -1):
        result = {}
        params = int_to_params(x)
        print(','.join(str(int(param)) for param in params.values()), end='', flush=True)
        query = build_query(params)
        cur.execute("BEGIN;")
        cur.execute("SET statement_timeout = 10000;")
        try:
            cur.execute(query)
            start = perf_counter()
            cur.execute(query)
            duration = perf_counter() - start 
        except Exception as e:
            print(",20")
            print(e)
            cur.execute("ROLLBACK;")
            continue
        print(f",{duration}")
        results.append({
            'params': params,
            'query': query,
            'duration': duration,
            'explain': "\n".join(row[0] for row in cur),
        })
        cur.execute("COMMIT;")
