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

nano:
  pkg.purged:
    - refresh: False
    - require:
      - vim
