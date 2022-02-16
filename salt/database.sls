# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up the postgres database
# There are a lot of exceptions for Debian because it comes with "batteries included"

xfsprogs:
  pkg.installed:
    - refresh: False

{% if grains.manufacturer == "DigitalOcean" %}
  {% set db_dev = "/dev/sda" %}
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
postgresql-common:
  pkg.installed:
    - refresh: False

/etc/postgresql-common/createcluster.d/override.conf:
  file.managed:
    - makedirs: True
    - contents: |
        create_main_cluster = false
        waldir = '/var/lib/postgres/data/pg_wal'
    - require:
      - postgresql-common
{% else %}
{% set pg_confdir = "/srv/postgres/data" %}
{% endif %}

postgresql:
  pkg.installed:
    - refresh: False
    - version: '{{ pg_version }}*'
    {% if grains.os_family == 'Debian' %}
    - require:
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
{%- set connections = 20 %}
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
        shared_preload_libraries = 'pg_stat_statements'

/etc/systemd/system/postgresql.service.d/override.conf:
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
      - /etc/systemd/system/postgresql.service.d/override.conf
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
