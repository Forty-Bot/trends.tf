# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up the postgres database
# There are a lot of exceptions for Debian because it comes with "batteries included"

xfsprogs:
  pkg.installed:
    - refresh: False

{% if grains.manufacturer == "DigitalOcean" %}
  {% set db_dev = "/dev/sda" %}
{% elif grains.manufacturer == "Hetzner" %}
  {% set db_dev = "/dev/sdb" %}
{% endif %}

{{ db_dev }}:
  blockdev.formatted:
    - fs_type: xfs
    - require:
      - xfsprogs
  mount.fstab_present:
    - fs_file: /srv
    - fs_vfstype: xfs
    - fs_passno: 2
    - require:
      - blockdev: {{ db_dev }}

{% set pg_version = 13 %}
{% if grains.os_family == 'Debian' %}
{% set pg_confdir = "/etc/postgresql/13/data" %}
{% set citus_version = "10.2" %} # I have no idea why they do it like this
{% set citus = "postgresql-{}-citus-{}".format(pg_version, citus_version) %}
/usr/share/keyrings/citus.pub:
  file.managed:
    - source: https://packagecloud.io/citusdata/community/gpgkey
    - source_hash: 2a3e7e542e23194a8906d02044f99453e1ac21cc4cf404947d6e43969ce0fba5
    - use_etag: True

citus-repo:
  pkgrepo.managed:
    - name: >
        deb [signed-by=/usr/share/keyrings/citus.pub]
        https://repos.citusdata.com/community/debian/ {{ grains.oscodename }} main
    - file: /etc/apt/sources.list.d/citusdata_community.list
    - require:
      - /usr/share/keyrings/citus.pub

postgresql-common:
  pkg.installed:
    - refresh: False

/etc/postgresql-common/createcluster.d/override.conf:
  file.managed:
    - makedirs: True
    - contents: |
        create_main_cluster = false
        initdb_options = '-E UTF8'
        waldir = '/var/lib/postgres/data/pg_wal'
    - require:
      - postgresql-common
{% else %}
{% set pg_confdir = "/srv/postgres/data" %}
{% set citus = "citus" %}
{% endif %}

postgresql:
  pkg.installed:
    - pkgs:
      - postgresql
      - {{ citus }}
    - refresh: False
    - version: '{{ pg_version }}*'
    {% if grains.os_family == 'Debian' %}
    - require:
      - citus-repo
      - /etc/postgresql-common/createcluster.d/override.conf
    {% endif %}

/var/lib/postgres:
  file.directory:
    - require:
      - pkg: postgresql

/var/lib/postgres/data:
  file.directory:
    - user: postgres
    - group: postgres
    - mode: 700
    - recurse:
      - user
      - group
    - require:
      - /var/lib/postgres

/srv/postgres:
  file.directory:
    - user: postgres
    - group: postgres
    - mode: 700
    - require:
      - pkg: postgresql

/srv/postgres/data:
  file.directory:
    - user: postgres
    - group: postgres
    - mode: 700
    - recurse:
      - user
      - group
    - require:
      - /srv/postgres

initdb:
  {% if grains.os_family == 'Debian' %}
  postgres_cluster.present:
    - name: data
    - version: {{ pg_version }}
    - datadir: /srv/postgres/data
  {% else %}
  postgres_initdb.present:
    - name: /srv/postgres/data
    - runas: postgres
    - auth: peer
    - waldir: /var/lib/postgres/data/pg_wal
  {% endif %}
    - require:
      - /var/lib/postgres/data
      - file: /srv/postgres/data

pg_includedir:
  file.replace:
    - name: {{ pg_confdir }}/postgresql.conf
    - pattern: "^.?include_dir.*$"
    - repl: include_dir = 'conf.d'
    - append_if_not_found: True
    - require:
      - initdb

# Budget pgtune
{%- set connections = 18 %}
# Reserve some memory for everyone else
{%- set mem = ( grains.mem_total - 256 ) * 1024 %}
{%- set shared_buffers = (mem / 4) | int %}
{%- set work_mem = ((mem - shared_buffers) / connections / 2) | int %}
{{ pg_confdir }}/conf.d/override.conf:
  file.managed:
    - makedirs: True
    - user: postgres
    - group: postgres
    - contents: |
        max_connections = {{ connections }}
        shared_buffers = {{ shared_buffers }}kB
        work_mem = {{ work_mem }}kB
        maintenance_work_mem = {{ ((shared_buffers / 2), 2 * 1024 * 1024) | min | int }}kB
        effective_io_concurrency = 200
        wal_buffers = 16MB
        min_wal_size = 1GB
        max_wal_size = 4GB
        checkpoint_completion_target = 0.9
        random_page_cost = 2
        effective_cache_size = {{ (mem * 3 / 4) | int }}kB
        default_statistics_target = 500
        # We have a lot of backlog, so reduce this to something which will run vacuum regularly
        autovacuum_vacuum_scale_factor = 0.005
        shared_preload_libraries = 'citus, pg_stat_statements'

{% if grains.os_family == 'Debian' %}
{% set override_dir = "postgresql@.service.d" %}
{% else %}
{% set override_dir = "postgresql@.service.d" %}
{% endif %}
/etc/systemd/system/{{ override_dir }}/override.conf:
  file.managed:
    - makedirs: True
    - contents: |
        [Service]
        Restart=on-failure
{% if grains.os_family != 'Debian' %}
        Environment=PGROOT=/srv/postgres
        PIDFile=/srv/postgres/data/postmaster.pid
{% endif %}

pg_service:
  module.run:
    - name: service.systemctl_reload
    - onchanges:
      - /etc/systemd/system/{{ override_dir }}/override.conf
    - require:
      - postgresql

postgresql.service:
  service.running:
    - enable: True
    - watch:
      - initdb
    - require:
      - pg_includedir
      - {{ pg_confdir }}/conf.d/override.conf
      - pg_service

daemon:
  postgres_user.present:
    - runas: postgres
    - require:
      - postgresql.service

trends:
  postgres_database.present:
    - runas: postgres
    - owner: daemon
    - require:
      - daemon

salt://schema.sql:
  cmd.script:
    - args: -d trends
    - runas: daemon
    - require:
      - trends

restic:
  pkg.installed:
    - pkgs:
      - restic
      - zstd
    - refresh: False

/usr/local/bin/backup:
  file.managed:
    - mode: 755
    - contents: |
        #!/usr/bin/bash
        set -euo pipefail
        pg_dump --verbose -Fc -Z0 trends | zstd --rsyncable - | \
          restic backup --stdin --stdin-filename trends.dump.zst
        restic forget --prune --keep-daily 7 --keep-weekly 4 --keep-monthly 12

/etc/systemd/system/backup.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Back up database

        [Service]
        Type=oneshot
        EnvironmentFile=/etc/default/restic
        ExecStart=/usr/local/bin/backup
        User=postgres
        Slice=background.slice

/etc/systemd/system/backup.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Daily back up

        [Timer]
        OnCalendar=8:00

        [Install]
        WantedBy=timers.target

backup_service:
  module.run:
    - name: service.systemctl_reload
    - onchanges:
      - /etc/systemd/system/backup.service
      - /etc/systemd/system/backup.timer

backup.timer:
  service.running:
    - enable: True
    - require:
      - backup_service
