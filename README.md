# trends.tf

Source code for [trends.tf](https://trends.tf/)

## Getting started

Create a new virtualenv and activate it

```
$ virtualenv venv
$ . venv/bin/activate
```

Then install this package to fetch dependencies

```
$ pip install -e .
```

### Database setup

In addition, you will need to install PostgreSQL (e.g. via `apt-get postgresql-server`). You must
increase `max_locks_per_transaction` to 256 by editing `postgresql.conf` (usually found in
`/etc/postgresql/<postgres version>/main/`). Then, restart postgres by running

```
# systemctl restart postgresql
```

In addition, you may need to create a cluster (as the `postgres` user)

```
[postgres]$ initdb -D /var/lob/postgres/data
```

Once you have created a cluster, add a user (for best results use the same username as your Unix
user).

```
[postgres]$ createuser --interactive <your user>
```

and create a database

```
[postgres]$ createdb -O <your user> trends
```

### Importing logs

To import logs starting with the most recent log, run

```
$ import_logs reverse -vv postgresql:///<your database>
```

This will run until you have imported every log, but you can kill it at any time. Logs are committed
every minute or so. To import logs only for a particular user, run

```
$ import_logs bulk -vvp <your steamid> postgresql:///<your database>
```

For more information, consult the output of `./import.py -h`.

### Running the site

To host the site for development, run

```
$ FLASK_ENV=development trends
```

The default database is `logs.db`, but can be configured by creating a file like

```
$ DATABASE=<some location>
```

and running the server like

```
$ FLASK_ENV=development CONF=<your config file> trends
```
