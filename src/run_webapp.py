#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point for the onboarding Web UI + REST API.

Usage (from the repository root, same convention as ``src/__main__.py``):

    python src/run_webapp.py [env-name]

which loads ``.env.d/<env-name>.env`` (the name defaults to ``GYROBOT_ENV``) and starts a uvicorn server hosting
``webapp.main:app``. Configure the bind address/port with ``WEBAPP_HOST``
(default ``0.0.0.0``) and ``WEBAPP_PORT`` (default ``8080``).
"""
import os
import sys

import uvicorn
from backend.secret_store import environment_name, load_environment

if __name__ == '__main__':
    load_environment(environment_name(sys.argv[1] if len(sys.argv) > 1 else None))
    uvicorn.run(
        'webapp.main:app',
        host=os.environ.get('WEBAPP_HOST', '127.0.0.1'),
        port=int(os.environ.get('WEBAPP_PORT', '5709')),
        reload=True,
    )
