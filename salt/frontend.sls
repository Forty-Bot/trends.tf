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

memcached:
  pkg.installed:
    - refresh: False

memcached.service:
  service.running:
    - enable: True
    - reload: True
    - requires:
      - memcached

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

git:
  pkg.installed:
    - refresh: False

https://github.com/Forty-Bot/trends.tf.git:
  git.cloned:
    - target: /srv/uwsgi/trends
    - require:
      - git

/srv/uwsgi/trends:
  file.directory:
    - user: sean
    - group: sean
    - recurse:
      - user
      - group
    - require:
      - https://github.com/Forty-Bot/trends.tf.git

receive.denyCurrentBranch:
  git.config_set:
    - value: updateInstead
    - repo: /srv/uwsgi/trends
    - require:
      - https://github.com/Forty-Bot/trends.tf.git

virtualenv:
  pkg.installed:
    - refresh: False
    - pkgs:
{% if grains.os_family == 'Debian' %}
      - build-essential
      - libpq-dev
      - libmemcached-dev
      - python3-dev
      - python3
      - virtualenv
{% else %}
      - libmemcached
      - python
      - python-virtualenv
    - require:
      - base-devel

base-devel:
  pkg.group_installed:
    - refresh: False
{% endif %}

/srv/uwsgi/trends/venv:
  virtualenv.managed:
    - user: sean
    - group: sean
    - python: /usr/bin/python3
    - require:
      - virtualenv
      - file: /srv/uwsgi/trends

setuptools_scm:
  pip.installed:
    - user: sean
    - bin_env: /srv/uwsgi/trends/venv
    - require:
      - /srv/uwsgi/trends/venv

trends.tf:
  pip.installed:
    - user: sean
    - editable: /srv/uwsgi/trends
    - bin_env: /srv/uwsgi/trends/venv
    - require:
      - setuptools_scm

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
      workers: {{ grains.num_cpus * 2 }}

uwsgi_service:
  service.running:
    - name: {{ uwsgi_service }}
    - enable: True
    - reload: True
    - requires:
      - memcached
      - /srv/uwsgi/trends
      - uwsgi_installed
      - uwsgi_config

# Metrics
munin:
  pkg.installed:
    - pkgs:
      - munin
      - libcgi-fast-perl
    - refresh: False

munin_conf:
  file.managed:
    - name: /etc/munin/munin-conf.d/override.conf
    - contents: |
        html_strategy cgi
        graph_strategy cgi
        cgiurl_graph /graph
    - require:
      - munin

/etc/systemd/system/munin-graph.service:
  file.symlink:
    - target: /usr/share/doc/munin/examples/systemd-fastcgi/munin-graph.service
    - require:
      - munin_conf

/etc/systemd/system/munin-graph.socket:
  file.symlink:
    - target: /usr/share/doc/munin/examples/systemd-fastcgi/munin-graph.socket
    - require:
      - munin_conf

/var/log/munin/munin-cgi-graph.log:
  file.managed:
    - user: munin
    - group: munin
    - replace: False
    - require:
      - munin

/etc/systemd/system/munin-html.service:
  file.symlink:
    - target: /usr/share/doc/munin/examples/systemd-fastcgi/munin-html.service
    - require:
      - munin_conf

/etc/systemd/system/munin-html.socket:
  file.symlink:
    - target: /usr/share/doc/munin/examples/systemd-fastcgi/munin-html.socket
    - require:
      - munin_conf

/var/log/munin/munin-cgi-html.log:
  file.managed:
    - user: munin
    - group: munin
    - replace: False
    - require:
      - munin

munin-graph.socket:
  service.running:
    - enable: True
    - require:
      - /etc/systemd/system/munin-graph.service
      - /etc/systemd/system/munin-graph.socket
      - /var/log/munin/munin-cgi-graph.log

munin-html.socket:
  service.running:
    - enable: True
    - require:
      - /etc/systemd/system/munin-html.service
      - /etc/systemd/system/munin-html.socket
      - /var/log/munin/munin-cgi-html.log

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
      site_packages: /srv/uwsgi/trends
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

dhparam:
  cmd.run:
    - name: openssl dhparam 2048 > /etc/nginx/dhparam.pem
    - creates: /etc/nginx/dhparam.pem

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
      - munin-graph.socket
      - munin-html.socket
      - dhparam

munin_node:
  pkg.installed:
    - pkgs:
      - libcache-memcached-perl
      - libdbd-pg-perl
      - munin-node
      - munin-plugins-core
      - munin-plugins-extra
    - refresh: False
    - require:
      - nginx.service

{% set memcached_suffixes = ('rates', 'bytes', 'counters') %}
{% for suffix in ('rates', 'bytes', 'counters') %}
/etc/munin/plugins/memcached_{{ suffix }}:
  file.symlink:
    - target: /usr/share/munin/plugins/memcached_
    - require:
      - munin_node
{% endfor %}

munin_node_conf:
  file.replace:
    - name: /etc/munin/munin-node.conf
    - pattern: "^host.*$"
    - repl: host 127.0.0.1
    - append_if_not_found: True
    - require:
      - munin_node

munin-node.service:
  service.running:
    - enable: True
    - require:
      - munin_node_conf
      {% for suffix in memcached_suffixes %}
      - /etc/munin/plugins/memcached_{{ suffix }}
      {% endfor %}

{% if grains.os_family == 'Debian' %}
grafana-repo:
  pkgrepo.managed:
    - name: deb https://apt.grafana.com stable main
    - file: /etc/apt/sources.list.d/grafana.list
    - key_url: https://apt.grafana.com/gpg.key
{% endif %}

grafana-agent:
  pkg.installed:
    - refresh: False
    {% if grains.os_family == 'Debian' %}
    - require:
      - grafana-repo
    {% endif %}

/etc/grafana-agent.yaml:
  file.managed:
    - contents: |
        server:
          log_level: warn

        metrics:
          global:
            scrape_interval: 1m
            remote_write:
              - url: https://prometheus-prod-10-prod-us-central-0.grafana.net/api/prom/push
                basic_auth:
                  username: 281816
                  password_file: /etc/prometheus_pass
          wal_directory: /var/lib/grafana-agent
          configs:
            - name: flask
              scrape_configs:
                - job_name: flask
                  static_configs:
                    - targets: ['127.0.0.1']

        integrations:
          agent:
            enabled: true

grafana-agent.service:
  service.running:
    - enable: True
    - require:
      - grafana-agent
      - /etc/grafana-agent.yaml
