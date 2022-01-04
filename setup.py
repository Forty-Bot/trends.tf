#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

import setuptools

setuptools.setup(
    name = 'trends.tf',
    use_scm_version = {
        'local_scheme': lambda version: \
            version.format_choice("+{node}", "+{node}.d{time:%Y%m%d.h%H%M%S}"),
    },
    description = "Team Fortress 2 stats and trends",
    author = 'Sean Anderson',
    author_email = 'seanga2@gmail.com',
    url = 'https://trends.tf/',
    packages = ['trends'],
    license = 'AGPL-3.0-only',
    license_files = [
        'COPYING',
        'LICENSES/*',
    ],
    setup_requires = ['setuptools_scm'],
    install_requires = [
        'psycopg2',
        'requests',
        'flask >= 2.0',
        'python-dateutil',
        'zstandard',
    ],
    extras_require = {
        'cache': "pylibmc",
        'sentry': "sentry-sdk[flask]",
    },
    entry_points = {
        'console_scripts': [
            "trends_importer=trends.importer.cli:main",
        ],
    },
    include_package_data = True,
)
