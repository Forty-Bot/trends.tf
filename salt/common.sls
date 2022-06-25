# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

update_system:
  pkg.uptodate:
    - refresh: True
{% if grains.os_family != 'Debian' %}
    - require:
      - kernel-modules-hook

# Prevent pacman from removing modules for the running kernel
kernel-modules-hook:
  pkg.installed:
    - refresh: False
{% endif %}

vim:
  pkg.installed:
    - refresh: False
    - require:
      - update_system

remove default packages:
  pkg.purged:
    - pkgs:
      - nano
      - zfs-fuse
    - refresh: False
    - require:
      - vim

/etc/profile.d/editor.sh:
  file.managed:
    - mode: 755
    - contents: |
        #!/bin/sh

        export EDITOR=vim
        export VISUAL=vim
    - require:
      - vim

{% set swapfile = "/var/swapfile" %}
{% set swapsize = grains["mem_total"] * 2 %}

# Based on https://serverfault.com/a/865797
/var/swapfile:
  cmd.run:
    - name: |
        swapon --show=NAME --noheadings | grep -q "^{{ swapfile }}$" && swapoff {{ swapfile }}
        rm -f {{ swapfile }}
        fallocate -l {{ swapsize }}M {{ swapfile }}
        chmod 0600 {{ swapfile }}
        mkswap {{ swapfile }}
    - unless: bash -c '[[ $(($(stat -c %s {{ swapfile }}) / 1024**2)) = {{ swapsize }} ]]'
  mount.swap:
    - persist: true
    - require:
      - cmd: /var/swapfile
