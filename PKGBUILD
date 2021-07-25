# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2020 Sean Anderson <seanga2@gmail.com>
# Maintainer: Sean Anderson <seanga2@gmail.com>
pkgname=trends.tf-git
pkgver=$(make --no-print-directory version)
pkgrel=1
pkgdesc="Team Fortress 2 stats and trends"
arch=('any')
url="https://trends.tf/"
license=('AGPL3' 'MIT')
depends=(
	'nginx'
	'uwsgi-plugin-python'
	'python-requests'
	'python-psycopg2'
	'python-flask'
	'python-dateutil'
	'python-zstandard'
)
makedepends=('git' 'python-setuptools')
provides=("${pkgname%-git}")
conflicts=("${pkgname%-git}")

pkgver() {
	cd "$startdir"
	printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

package() {
	cd "$startdir"
	make DESTDIR="$pkgdir/" install

	# Cache dir; user 33 is http
	install -dvm700 -o33 -g33 "$pkgdir/var/cache/nginx/"
}
