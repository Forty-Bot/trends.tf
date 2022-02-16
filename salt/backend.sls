# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up the backend (the import scripts)

{% set prefix = "/srv/uwsgi/trends/venv" %}

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

/etc/systemd/system/map_refresh.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Refresh map popularity

        [Service]
        Type=oneshot
        ExecStart=/usr/bin/psql -c 'REFRESH MATERIALIZED VIEW CONCURRENTLY map_popularity' postgres:///trends
        User=daemon

/etc/systemd/system/map_refresh.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Daily map popularity refresh

        [Timer]
        OnCalendar=6:45

        [Install]
        WantedBy=timers.target


/etc/systemd/system/weapon_import.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Import weapons from https://github.com/SteamDatabase/GameTracking-TF2

        [Service]
        Type=oneshot
        ExecStart={{ prefix }}/bin/trends_importer -vv weapons remote postgres:///trends
        User=daemon

/etc/systemd/system/weapon_import.timer:
  file.managed:
    - contents: |
        [Unit]
        Description=Check for item updates

        [Timer]
        OnCalendar=hourly

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
      - /etc/systemd/system/map_refresh.service
      - /etc/systemd/system/map_refresh.timer
      - /etc/systemd/system/weapon_import.service
      - /etc/systemd/system/weapon_import.timer

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

map_refresh.timer:
  service.running:
    - enable: True
    - require:
      - backend_services

weapon_import.timer:
  service.running:
    - enable: True
    - require:
      - backend_services
