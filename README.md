# trends.tf

Source code for [trends.tf](https://trends.tf/)

## Getting started

You will need

```
sqlite >= 3.33
python-requests
python-flask
python-dateutil
```

To import logs, run

```
./import.py bulk -v -p <your steamid> logs.db
```

For more information, consult the output of `./import.py -h`.

To host the site, run

```
./trends.py
```

The default database is `logs.db`, but can be configured by creating a file like

```
DATABASE=<some location>
```

and running the server like

```
CONF=<your config file> ./trends.py
```
