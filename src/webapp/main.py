"""FastAPI application wiring: Web UI + REST API for onboarding.

Run via ``python src/run_webapp.py <env-name>`` (loads ``.env.d/<env-name>.env``,
same convention as ``src/__main__.py``), or point any ASGI server
(e.g. ``uvicorn webapp.main:app``) at this module after loading the required
environment variables yourself.

Required environment variables:

* ``WEBAPP_SESSION_SECRET`` -- signs the Web UI session cookie.
* ``WEBAPP_JWT_SECRET`` -- signs REST API OAuth2 access tokens.
* ``LDAP_SERVER`` / ``LDAP_USERNAME_PATTERN`` (and optionally ``LDAP_AUTHENTICATION_TYPE``) -- Web UI LDAP
  authentication.
* ``OAUTH2_CLIENTS_CONFIGURATION`` (optional, default ``config/oauth2_clients.yml``)
  -- REST API client_id/client_secret registry.
* ``DATABASE_URL`` -- required by the
  underlying ``onboard``/``offboard`` commands (see ``commands/onboarding``).
"""
import pathlib
import subprocess
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from webapp.auth import LoginRequired, login_redirect
from webapp.bootstrap import ensure_commands_imported
from webapp.config import session_secret
from webapp.routers import api, odata, permissions, web

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

allowed_hosts = os.environ.get('WEBAPP_ALLOWED_HOSTS', '').split(',')

app = FastAPI(
    title='GyroBot Onboarding Interface',
    description='Web UI (LDAP-authenticated) and REST API (OAuth2 client-credentials) '
               'for the onboard/offboard chat bot commands.'
)


class RootPathMiddleware:
    """Sets the URL prefix of the proxy (``WEBAPP_ROOT_PATH``) on every request, however the server was started.

    Replaces ``FastAPI(root_path=...)``, which is deprecated; the prefix is stripped by the proxy, so only the
    generated links need it.
    """

    def __init__(self, asgi_app, root_path: str):
        self.asgi_app = asgi_app
        self.root_path = root_path.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket') and self.root_path:
            scope = {**scope, 'root_path': self.root_path}
        await self.asgi_app(scope, receive, send)


app.add_middleware(RootPathMiddleware, root_path=os.environ.get('WEBAPP_ROOT_PATH', '/eurobot/'))
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[hostname, "localhost"] + allowed_hosts)
app.add_middleware(SessionMiddleware, secret_key=session_secret())

STATIC_DIR = pathlib.Path(__file__).parent / 'static'


# A plain route instead of a StaticFiles mount: the mount does not find its files when root_path is set
@app.get('/static/{path}', name='static', include_in_schema=False)
def static_file(path: str):
    file = (STATIC_DIR / path).resolve()
    if file.parent != STATIC_DIR.resolve() or not file.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file)


app.add_exception_handler(LoginRequired, login_redirect)
app.include_router(web.public_router)
app.include_router(web.router)
app.include_router(web.json_router)
app.include_router(permissions.router)
app.include_router(api.router)
app.include_router(odata.router)
