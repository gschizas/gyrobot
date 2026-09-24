"""Web UI for onboarding, authenticated against LDAP.

Login sets a signed session cookie (``SessionMiddleware`` in ``webapp.main``)
holding the authenticated username; every onboarding form then drives the
same ``onboard``/``offboard`` Click commands used by chat, via
:func:`webapp.command_runner.run_bot_command`, using that username as the
requesting identity (see ``backend.approval``/``backend.configuration``
permission checks, matched against the ``$webui`` pseudo-channel).
"""
import json
import logging
import pathlib
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.github_teams import build_team_tree
from webapp import config
from webapp.auth_ldap import ldap_authenticate
from webapp.command_runner import run_bot_command

logger = logging.getLogger('webapp.routers.web')

router = APIRouter(tags=['web'])
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent.parent / 'templates'))
templates.env.filters['tojson'] = json.dumps

# Simple declarative form definitions for each onboarding action. Keeping this
# data-driven avoids one template per action. The github 'team' field uses
# type 'team_tree' to render a selectable tree (see build_team_tree /
# form.html) instead of a plain text input.
FORMS = {
    'github': {
        'title': 'Onboard: GitHub Copilot',
        'fields': [
            {'name': 'username', 'label': 'GitHub username', 'required': True},
            {'name': 'email', 'label': 'Email address', 'required': True},
            {'name': 'team', 'label': 'Enterprise team', 'required': True, 'type': 'team_tree'},
        ],
    },
    'crowd': {
        'title': 'Onboard: Crowd',
        'fields': [
            {'name': 'username', 'label': 'Username', 'required': True},
            {'name': 'team', 'label': 'Team', 'required': True},
        ],
    },
    'jetbrains': {
        'title': 'Onboard: JetBrains IntelliJ IDEA',
        'fields': [
            {'name': 'email', 'label': 'Email address', 'required': True},
            {'name': 'team_name', 'label': 'Team name', 'required': True},
        ],
    },
    'slack': {
        'title': 'Onboard: Slack',
        'fields': [
            {'name': 'email', 'label': 'Email address', 'required': True},
            {'name': 'member_ids', 'label': 'Member IDs (comma-separated)', 'required': True},
        ],
    },
    'offboard': {
        'title': 'Offboard',
        'fields': [
            {'name': 'email', 'label': 'Email address', 'required': True},
        ],
    },
}


def _current_user(request: Request) -> str | None:
    return request.session.get('user')


def _require_login(request: Request) -> Optional[RedirectResponse]:
    if not _current_user(request):
        return RedirectResponse(url='/login', status_code=status.HTTP_302_FOUND)
    return None


def _github_team_tree() -> tuple[Optional[dict], Optional[str]]:
    """Fetch the GitHub Enterprise team hierarchy for the tree widget.

    Returns ``(tree, error)``: on failure (missing config, GitHub API/network
    error, etc.) ``tree`` is None and ``error`` holds a message to display,
    letting the form gracefully fall back to a plain text field.
    """
    try:
        return build_team_tree(), None
    except Exception as ex:
        logger.warning(f"Failed to build GitHub team tree: {ex!r}")
        return None, f"Could not load the GitHub team list ({ex}); enter the team slug manually."


@router.get('/', include_in_schema=False)
def index(request: Request):
    return RedirectResponse(url='/onboarding' if _current_user(request) else '/login')


@router.get('/login', include_in_schema=False)
def login_form(request: Request):
    if _current_user(request):
        return RedirectResponse(url='/onboarding', status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, 'login.html', {'error': None})


@router.post('/login', include_in_schema=False)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if ldap_authenticate(username, password):
        request.session['user'] = username
        return RedirectResponse(url='/onboarding', status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request, 'login.html', {'error': 'Invalid username or password'},
        status_code=status.HTTP_401_UNAUTHORIZED)


@router.get('/logout', include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/login', status_code=status.HTTP_302_FOUND)


@router.get('/onboarding', include_in_schema=False)
def dashboard(request: Request):
    if redirect := _require_login(request):
        return redirect
    return templates.TemplateResponse(request, 'dashboard.html', {'user': _current_user(request), 'forms': FORMS})


@router.get('/onboarding/{action}', include_in_schema=False)
def onboarding_form(request: Request, action: str):
    if redirect := _require_login(request):
        return redirect
    form = FORMS.get(action)
    if not form:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    context = {'user': _current_user(request), 'action': action, **form}
    if action == 'github':
        context['team_tree'], context['team_tree_error'] = _github_team_tree()
    return templates.TemplateResponse(request, 'form.html', context)


@router.post('/onboarding/{action}', include_in_schema=False)
async def onboarding_submit(request: Request, action: str):
    if redirect := _require_login(request):
        return redirect
    form_def = FORMS.get(action)
    if not form_def:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    form_data = await request.form()
    args = _build_args(action, form_data)
    if args is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='Invalid form data')

    user = _current_user(request)
    result = run_bot_command(args, user_id=user, channel_name=config.web_channel_name(),
                             team_name=config.web_team_name())
    return templates.TemplateResponse(
        request, 'result.html', {'user': user, 'title': form_def['title'], 'result': result})


def _build_args(action: str, form_data) -> list[str] | None:
    if action == 'github':
        return ['onboard', 'github', form_data['username'], form_data['email'], form_data['team']]
    if action == 'crowd':
        return ['onboard', 'crowd', form_data['username'], form_data['team']]
    if action == 'jetbrains':
        return ['onboard', 'jetbrains', form_data['email'], form_data['team_name']]
    if action == 'slack':
        member_ids = [m.strip() for m in str(form_data['member_ids']).split(',') if m.strip()]
        if not member_ids:
            return None
        return ['onboard', 'slack', form_data['email'], *member_ids]
    if action == 'offboard':
        return ['offboard', form_data['email']]
    return None
