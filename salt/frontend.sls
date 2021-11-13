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
    - pkgs:
      {% if grains.os_family == 'Debian' %}
      - libpq-dev
      - python3-dev
      - python3
      - virtualenv
      {% else %}
      - base-devel
      - python
      - python-virtualenv
      {% endif %}
    - refresh: False

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
      # Massive hack, sorry!
      site_packages: /srv/uwsgi/trends/lib/{{ grains.pythonpath[4].split("/") | last }}/site-packages
      uwsgi_socket: {{ uwsgi_socket }}
    - require:
      - nginx

/etc/nginx/sites-enabled/default:
  file.absent:
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
    - onchanges:
      - /etc/nginx
    - require:
      - certbot
      - /srv/uwsgi/trends
      - nginx_service
      - uwsgi_service
