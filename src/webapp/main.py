"""FastAPI application wiring: Web UI + REST API for onboarding.

Run via ``python src/run_webapp.py <env-name>`` (loads ``.env.d/<env-name>.env``,
same convention as ``src/__main__.py``), or point any ASGI server
(e.g. ``uvicorn webapp.main:app``) at this module after loading the required
environment variables yourself.

Required environment variables:

* ``WEBAPP_SESSION_SECRET`` -- signs the Web UI session cookie.
* ``WEBAPP_JWT_SECRET`` -- signs REST API OAuth2 access tokens.
* ``LDAP_SERVER_URL`` / ``LDAP_BIND_DN_TEMPLATE`` -- Web UI LDAP authentication.
* ``OAUTH2_CLIENTS_CONFIGURATION`` (optional, default ``config/oauth2_clients.yml``)
  -- REST API client_id/client_secret registry.
* ``APPROVAL_DATABASE_URL`` / ``PERMISSIONS_DATABASE_URL`` -- required by the
  underlying ``onboard``/``offboard`` commands (see ``commands/onboarding``).
"""
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from webapp.bootstrap import ensure_commands_imported
from webapp.config import session_secret
from webapp.routers import api, web

ensure_commands_imported()

app = FastAPI(
    title='GyroBot Onboarding Interface',
    description='Web UI (LDAP-authenticated) and REST API (OAuth2 client-credentials) '
               'for the onboard/offboard chat bot commands.',
)
app.add_middleware(SessionMiddleware, secret_key=session_secret())

app.include_router(web.router)
app.include_router(api.router)
