# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>

import setuptools

setuptools.setup(
    name = 'trends.tf',
    version = '0',
    author = 'Sean Anderson',
    author_email = 'seanga2@gmail.com',
    url = 'https://trends.tf/',
    packages = ['.'],
    install_requires = [
        'psycopg2',
        'requests',
        'flask >= 2.0',
        'python-dateutil',
        'zstandard',
    ],
    entry_points = {
        'console_scripts': [
            "import_logs=importer:main",
            "trends=trends:application.run",
        ],
    },
    include_package_data = True,
)
