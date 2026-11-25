"""Session authentication for the web UI, as FastAPI dependencies.

Protection is applied per router (``APIRouter(dependencies=[Depends(current_user)])``), so a new page is
protected by default; only the routes on a public router are open. ``current_user`` raises
:class:`LoginRequired`, which :func:`login_redirect` (registered in ``webapp.main``) turns into a redirect to
the login page. JSON endpoints used by page scripts use :func:`current_user_json` (HTTP 401) instead.
"""
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse


class LoginRequired(Exception):
    """The request has no logged-in user."""


def session_user(request: Request) -> str | None:
    return request.session.get('user')


def current_user(request: Request) -> str:
    """The logged-in user's name, or :class:`LoginRequired`."""
    if user := session_user(request):
        return user
    raise LoginRequired


def current_user_json(request: Request) -> str:
    """Like :func:`current_user`, for JSON endpoints: HTTP 401 instead of a redirect."""
    if user := session_user(request):
        return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Not logged in')


def login_redirect(request: Request, exc: LoginRequired) -> RedirectResponse:
    return RedirectResponse(url=request.url_for('login_form'), status_code=status.HTTP_302_FOUND)
