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
import subprocess
import os

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware

from webapp.bootstrap import ensure_commands_imported
from webapp.config import session_secret
from webapp.routers import api, permissions, web

hostname = subprocess.check_output(["hostname"]).decode().strip()
print(f"Starting FastAPI application on host: {hostname}...")

ensure_commands_imported()


def _register_notification_sender():
    """Let commands run from the web/API post to the chat platform (e.g. the approvals notify channel)."""
    from backend import notifications
    from chat import get_notification_sender
    try:
        bot_name = os.environ.get('BOT_NAME', 'bot').split()[0]
        notifications.set_sender(get_notification_sender(bot_name))
    except Exception as e:
        print(f"Chat notifications disabled for the web application: {e}")


_register_notification_sender()

root_path = os.environ.get('WEBAPP_ROOT_PATH', '/eurobot/')
allowed_hosts = os.environ.get('WEBAPP_ALLOWED_HOSTS', '').split(',')

app = FastAPI(
    title='GyroBot Onboarding Interface',
    description='Web UI (LDAP-authenticated) and REST API (OAuth2 client-credentials) '
               'for the onboard/offboard chat bot commands.',
    root_path=root_path
)
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[hostname, "localhost"] + allowed_hosts)
app.add_middleware(SessionMiddleware, secret_key=session_secret())

app.include_router(web.router)
app.include_router(permissions.router)
app.include_router(api.router)
