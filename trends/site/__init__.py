# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

from ..util import sentry_init
from .wsgi import create_app

application = create_app()
sentry_init(debug=application.debug, environment=application.env)
