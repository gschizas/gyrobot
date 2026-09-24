#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point for the onboarding Web UI + REST API.

Usage (from the repository root, same convention as ``src/__main__.py``):

    python src/run_webapp.py <env-name>

which loads ``.env.d/<env-name>.env`` and starts a uvicorn server hosting
``webapp.main:app``. Configure the bind address/port with ``WEBAPP_HOST``
(default ``0.0.0.0``) and ``WEBAPP_PORT`` (default ``8080``).
"""
import os
import sys

import uvicorn
from dotenv import load_dotenv

if __name__ == '__main__':
    if len(sys.argv) > 1:
        load_dotenv(dotenv_path=f'.env.d/{sys.argv[1]}.env', override=True)
    else:
        print("Usage: python src/run_webapp.py <env-name>")
        sys.exit(1)
    uvicorn.run(
        'webapp.main:app',
        host=os.environ.get('WEBAPP_HOST', '127.0.0.1'),
        port=int(os.environ.get('WEBAPP_PORT', '5709')),
        reload=False,
    )
