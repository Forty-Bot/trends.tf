#!/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020-21 Sean Anderson <seanga2@gmail.com>

from distutils.command.build import build as distutils_build
import setuptools
from setuptools.command.develop import develop as setuptools_develop
import os

class build_fetch(setuptools.Command):
    def initialize_options(self):
        self.build_lib = None
        self.inplace = False
        self.package_dir = None

    def finalize_options(self):
        self.set_undefined_options('build_ext',
            ('build_lib', 'build_lib'),
            ('inplace', 'inplace'),
        )

    def run(self):
        import requests

        if self.inplace:
            build_py = self.get_finalized_command('build_py')
            vendor = f"{build_py.get_package_dir('trends.site')}/static/vendor"
        else:
            vendor = f"{self.build_lib}/trends/site/static/vendor"

        try:
            os.mkdir(vendor)
        except FileExistsError:
            pass

        ts = ["js/tom-select.popular.min.js", "css/tom-select.min.css"]
        ts += [f"{file}.map" for file in ts]
        urls = [f"https://cdn.jsdelivr.net/npm/tom-select@2.0.0/dist/{file}" for file in ts]
        urls.append("https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js")

        with requests.Session() as s:
            for url in urls:
                file = os.path.basename(url)
                etag = f".{file}.etag"
                file = os.path.join(vendor, file)
                etag = os.path.join(vendor, etag)

                print(f"Saving {url} to {file}")
                headers = {}
                try:
                    with open(etag) as e:
                        headers['If-None-Match'] = e.read()
                except FileNotFoundError:
                    pass

                resp = s.get(url, headers=headers)
                resp.raise_for_status()
                if not len(headers) or resp.status_code != requests.codes.not_modified:
                    with open(file, 'wb') as f:
                        f.write(resp.content)

                    with open(etag, 'w') as e:
                        e.write(resp.headers['etag'])

class develop(setuptools_develop):
    def run(self):
        self.reinitialize_command('build_fetch', inplace=1)
        self.run_command('build_fetch')
        super().run()

class build(distutils_build):
    sub_commands = [('build_fetch', None)] + distutils_build.sub_commands

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
    setup_requires = [
        'requests',
        'setuptools_scm',
    ],
    install_requires = [
        'flask >= 2.0',
        'mpmetrics',
        'prometheus-flask-exporter',
        'psycopg2',
        'pylibmc',
        'python-dateutil',
        'requests',
        'sentry-sdk[flask]',
        'systemd-watchdog',
        'zstandard',
    ],
    extras_require = {
        'tests': [
            'hypothesis',
            'pytest',
            'python-testing-crawler',
            'responses',
            'testing.postgresql'
        ],
    },
    cmdclass = {
        'build': build,
        'build_fetch': build_fetch,
        'develop': develop,
    },
    entry_points = {
        'console_scripts': [
            "trends_importer=trends.importer.cli:main",
        ],
    },
    include_package_data = True,
)
