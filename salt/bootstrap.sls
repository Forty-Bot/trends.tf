# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

# Set up an admin user 'sean' with sudo and ssh access, then disable root login

sudo:
  pkg.installed:
    - refresh: False

/etc/sudoers.d/wheel:
  file.managed:
    - contents: |
        %wheel ALL=(ALL) NOPASSWD: ALL
    - require:
      - sudo

wheel:
  group.present:
    - system: True

sean:
  user.present:
    - empty_password: True
    - groups:
      - wheel
      - systemd-journal
    - shell: /bin/bash
    - require:
      - wheel

ssh key:
  ssh_auth.present:
    - user: sean
    - source: salt://id_rsa.pub
    - require:
      - sean

ssh:
  pkg.installed:
    - name:
       {% if grains.os_family == 'Debian' %}
       openssh-server
       {% else %}
       openssh
       {% endif %}
    - refresh: False

sshd:
  service.running:
    - enable: True
    - require:
      - ssh

/root/.ssh/authorized_keys:
  file.absent:
    - require:
      - sshd
      - ssh key
      - /etc/sudoers.d/wheel

shadow.lock_password:
  module.run:
    - m_name: root
    - watch:
      - /root/.ssh/authorized_keys

arch:
  user.absent:
    - require:
      - sshd
