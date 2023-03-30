# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

PYTHON := python3
PROD := trends.tf
PROD_PREFIX := /srv/uwsgi/trends

.PHONY: FORCE
FORCE:

export SOURCE_DATE_EPOCH := $(shell date +%s)
PACKAGE := dist/$(shell $(PYTHON) setup.py --fullname)-py3-none-any.whl
$(PACKAGE): FORCE
	$(PYTHON) setup.py $(if $(V),,-q) bdist_wheel --plat-name any

.PHONY: build
build: $(PACKAGE)

.PHONY: deploy deploy/%
deploy/%:
	git push --force ssh://$(PROD)$(PROD_PREFIX) $*:master
	ssh $(PROD) '$(PROD_PREFIX)/venv/bin/pip $(if $(V),,-q) install -Ue $(PROD_PREFIX) && \
		sudo systemctl reload uwsgi'

deploy: deploy/HEAD

.PHONY: clean
clean:
	$(PYTHON) setup.py clean --all

.PHONY: distclean
distclean: clean
	rm -f *.deb *.pkg.tar.zst
