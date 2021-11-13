# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up the backend (the import scripts)

{% set prefix = "/srv/uwsgi/trends" %}

/etc/systemd/system/log_import.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Import logs from logs.tf
        
        [Service]
        Type=oneshot
        ExecStart={{ prefix }}/bin/trends_importer -vv logs bulk -c 1000 postgres:///trends
        User=daemon

/etc/systemd/system/log_import.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Import from logs.tf every 5 minutes
        
        [Timer]
        OnCalendar=*:0/5
        
        [Install]
        WantedBy=timers.target

/etc/systemd/system/player_import.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Import players from steam
        
        [Service]
        Type=simple
        EnvironmentFile=/etc/default/trends
        ExecStart={{ prefix }}/bin/trends_importer players -k ${STEAMKEY} -w 1 random postgres:///trends
        User=daemon
        Restart=on-failure
        
        [Install]
        WantedBy=multi-user.target

/etc/systemd/system/leaderboard_refresh.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Refresh leaderboard
        
        [Service]
        Type=oneshot
        ExecStart=/usr/bin/psql -c 'REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard_cube' postgres:///trends
        User=daemon

/etc/systemd/system/leaderboard_refresh.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Daily leaderboard refresh
        
        [Timer]
        OnCalendar=7:00
        
        [Install]
        WantedBy=timers.target

backend_services:
  module.run:
    - name: service.systemctl_reload
    - onchanges:
      - /etc/systemd/system/log_import.service
      - /etc/systemd/system/log_import.timer
      - /etc/systemd/system/player_import.service
      - /etc/systemd/system/leaderboard_refresh.service
      - /etc/systemd/system/leaderboard_refresh.timer

log_import.timer:
  service.running:
    - enable: True
    - require:
      - backend_services

player_import.service:
  service.running:
    - enable: True
    - require:
      - backend_services

leaderboard_refresh.timer:
  service.running:
    - enable: True
    - require:
      - backend_services