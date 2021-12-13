# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up the frontend (nginx+uwsgi)

uwsgi:
  user.present:
    - home: /srv/uwsgi
    - createhome: False
    - system: True
    - shell: /usr/bin/nologin
  postgres_user.present:
    - runas: postgres
    - require:
      - user: uwsgi

/srv/uwsgi:
  file.directory:
    - user: uwsgi
    - group: uwsgi
    - dir_mode: 755
    - require:
      - user: uwsgi

{% set uwsgi_privs = (
  ("trends", "database", "CONNECT"),
  ("public", "schema", "USAGE"),
  ("ALL", "table", "SELECT"),
) %}
{% for name, type, priv in uwsgi_privs %}
uwsgi_{{ name }}_privs:
  postgres_privileges.present:
    - name: uwsgi
    - object_name: {{ name }}
    - object_type: {{ type }}
    - privileges:
      - {{ priv }}
    - maintenance_db: trends
    - user: daemon
{% endfor %}

# TODO: ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO uwsgi;

{% if grains.os_family == 'Debian' %}
 {% set python = "python3" %}
 {% set uwsgi_socket = "/run/uwsgi/app/trends/socket" %}
 {% set uwsgi_service = "uwsgi.service" %}
 {% set uwsgi_config = "/etc/uwsgi/apps-enabled/trends.ini" %}
{% else %}
 {% set python = "python" %}
 {% set uwsgi_socket = "/run/uwsgi/trends.sock" %}
 {% set uwsgi_service = "uwsgi@trends.socket" %}
 {% set uwsgi_config = "/etc/uwsgi/trends.ini" %}
{% endif %}

virtualenv:
  pkg.installed:
    - refresh: False
    - pkgs:
{% if grains.os_family == 'Debian' %}
      - libpq-dev
      - python3-dev
      - python3
      - virtualenv
{% else %}
      - python
      - python-virtualenv
    - require:
      - base-devel

base-devel:
  pkg.group_installed:
    - refresh: False
{% endif %}

/srv/uwsgi/trends:
  file.directory:
    - user: sean
  virtualenv.managed:
    - user: sean
    - require:
      - virtualenv

uwsgi_installed:
  pkg.installed:
    - refresh: False
    - pkgs:
      - uwsgi
      - uwsgi-plugin-{{ python }}

uwsgi_config:
  file.managed:
    - name: {{ uwsgi_config }}
    - source: salt://trends.ini
    - template: jinja
    - defaults:
      socket: {{ uwsgi_socket }}
      python: {{ python }}

uwsgi_service:
  service.running:
    - name: {{ uwsgi_service }}
    - enable: True
    - reload: True
    - requires:
      - /srv/uwsgi/trends
      - uwsgi_installed
      - uwsgi_config

# Metrics
netdata:
  pkg.installed:
    - refresh: False
  postgres_user.present:
    - runas: postgres
    - require:
      - pkg: netdata

psycopg2:
  pkg.installed:
{% if grains.os_family == 'Debian' %}
    - name: python3-psycopg2
{% else %}
    - name: python-psycopg2
{% endif %}
    - refresh: False

/etc/netdata/.opt-out-from-anonymous-statistics:
  file.managed:
    - require:
      - netdata

/etc/netdata/netdata.conf:
  file.managed:
    - contents: |
        [global]
          run as user = netdata
          access log = none

          memory mode = dbengine
          page cache size = 32
          dbengine multihost disk space = 4096

          process scheduling policy = idle
          OOM score = 1000

        [web]
          web files owner = root
{% if grains.os_family == 'Debian' %}
          web files group = root
{% else %}
          web files group = netdata
{% endif %}
          bind to = unix:/run/netdata/netdata.sock
    - require:
      - netdata

/etc/netdata/python.d/web_log.conf:
  file.managed:
    - contents: |
        nginx_log:
          name: 'nginx'
          path: '/var/log/nginx/access.log'
          histogram: [1,10,100,1000]
    - require:
      - netdata

/etc/netdata/python.d/postgres.conf:
  file.managed:
    - contents: |
        socket:
          name: 'local'
          user: 'netdata'
          database: 'trends'
    - require:
      - netdata

netdata.service:
  service.running:
    - enable: True
    - reload: True
    - requires:
      - netdata
      - psycopg2
      - /etc/netdata/.opt-out-from-anonymous-statistics
      - /etc/netdata/netdata.conf
      - /etc/netdata/python.d/web_log.conf
      - /etc/netdata/python.d/postgres.conf

certbot:
  pkg.installed:
    - refresh: False

certbot.timer:
  service.running:
    - enable: True
    - require:
      - certbot
{% if grains.os_family != 'Debian' %}
      - certbot_service

# Arch doesn't provide a certbot service, so create it ourself
/etc/systemd/system/certbot.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Let's Encrypt renewal
        
        [Service]
        Type=oneshot
        ExecStart=/usr/bin/certbot renew --quiet --agree-tos

/etc/systemd/system/certbot.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Twice daily renewal of Let's Encrypt's certificates
        
        [Timer]
        OnCalendar=0/12:00:00
        RandomizedDelaySec=1h
        Persistent=true
        
        [Install]
        WantedBy=timers.target

certbot_service:
  module.run:
    - name: service.systemctl_reload
    - onchanges:
      - /etc/systemd/system/certbot.service
      - /etc/systemd/system/certbot.timer
{% endif %}

nginx:
  pkg.installed:
    - refresh: False

/etc/nginx:
  file.recurse:
    - source: salt://etc/nginx
    - template: jinja
    - defaults:
      os: {{ grains.os_family }}
      certdir: /etc/letsencrypt/live/trends.tf
      # Massive hack, sorry!
      site_packages: /srv/uwsgi/trends/lib/{{ grains.pythonpath[4].split("/") | last }}/site-packages
      uwsgi_socket: {{ uwsgi_socket }}
    - require:
      - nginx

/etc/nginx/sites-enabled/default:
  file.absent:
    - require:
      - nginx

/etc/nginx/ca.crt:
  file.managed:
    - source: salt://ca.crt
    - require:
      - nginx

/etc/systemd/system/nginx.service.d/override.conf:
  file.managed:
    - makedirs: True
    - contents: |
        [Unit]
        After={{ uwsgi_service }}

nginx_service:
  module.run:
    - name: service.systemctl_reload
    - onchanges:
      - /etc/systemd/system/nginx.service.d/override.conf

nginx.service:
  service.running:
    - enable: True
    - reload: True
    - require:
      - certbot
      - /srv/uwsgi/trends
      - nginx_service
      - uwsgi_service
      - netdata.service
