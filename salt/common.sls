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
