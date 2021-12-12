# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

PYTHON := python
PROD := trends.tf
PROD_PREFIX := /srv/uwsgi/trends

.PHONY: FORCE
FORCE:

export SOURCE_DATE_EPOCH := $(shell date +%s)
PACKAGE := dist/$(shell $(PYTHON) setup.py --fullname)-py3-none-any.whl
$(PACKAGE): FORCE
	$(PYTHON) setup.py -q bdist_wheel --plat-name any

.PHONY: deploy
deploy: $(PACKAGE)
	scp $< $(PROD):/tmp
	ssh $(PROD) '$(PROD_PREFIX)/bin/pip -q install /tmp/$(<F)'

.PHONY: clean
clean:
	$(PYTHON) setup.py clean --all

.PHONY: distclean
distclean: clean
	rm -f *.deb *.pkg.tar.zst
