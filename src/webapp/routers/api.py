"""REST API for onboarding, authenticated with OAuth2 client-credentials.

1. The client exchanges its ``client_id``/``client_secret`` (configured in
   ``config/oauth2_clients.yml``) for a short-lived bearer token at
   ``POST /api/oauth/token``.
2. The client calls the onboarding endpoints below, passing the token back as
   an HTTP bearer credential in the ``Authorization`` request header.

Every endpoint drives the exact same ``onboard``/``offboard`` Click commands
used by chat (see ``commands/onboarding``), via
:func:`webapp.command_runner.run_bot_command`. Since those commands are
gated behind the approval queue (``backend.approval.requires_approval``),
successful calls here enqueue an approval request rather than provisioning
immediately - identical to the chat behaviour.
"""
import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from webapp import config
from webapp.config import client_scopes
from webapp.auth_oauth2 import create_access_token, decode_access_token, validate_client_credentials
from webapp.command_runner import run_bot_command
from webapp.models import (CommandResult, CrowdOnboardRequest, GithubBulkOnboardRequest,
                           GithubOnboardRequest, JetbrainsOnboardRequest, OffboardRequest,
                           SlackOnboardRequest, TokenResponse)

router = APIRouter(prefix='/api', tags=['api'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/oauth/token', auto_error=False)


@router.post('/oauth/token', response_model=TokenResponse)
def issue_token(grant_type: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...)):
    """OAuth2 "client_credentials" token endpoint (RFC 6749 §4.4)."""
    if grant_type != 'client_credentials':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='unsupported_grant_type')
    if not validate_client_credentials(client_id, client_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='invalid_client')
    access_token, ttl = create_access_token(client_id)
    return TokenResponse(access_token=access_token, expires_in=ttl)


def _authenticate(token: str) -> dict:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Not authenticated',
                            headers={'WWW-Authenticate': 'Bearer'})
    try:
        return decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token',
                            headers={'WWW-Authenticate': 'Bearer'})


def require_scope(scope: str):
    """A dependency returning the client id when the token grants ``scope`` (and the registry still does)."""
    def dependency(token: str = Depends(oauth2_scheme)) -> str:
        payload = _authenticate(token)
        granted = set(str(payload.get('scope', '')).split()) & set(client_scopes(payload['sub']))
        if scope not in granted:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f'Missing scope: {scope}')
        return payload['sub']
    return dependency


get_current_client = require_scope(config.DEFAULT_SCOPE)


def _run(args: list[str], client_id: str) -> CommandResult:
    result = run_bot_command(
        args, user_id=client_id, channel_name=config.api_channel_name(), team_name=config.api_team_name())
    return CommandResult(
        success=result.success, exit_code=result.exit_code, output=result.output,
        messages=result.messages, error=result.error)


def _github_args(item) -> list[str]:
    args = ['onboard', 'github', item.username, item.email, item.team]
    if item.role:
        args += ['--role', item.role]
    return args


@router.post('/onboarding/github', response_model=CommandResult)
def onboard_github(payload: GithubOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(_github_args(payload), client_id)


@router.post('/onboarding/github/bulk', response_model=list[CommandResult])
def onboard_github_bulk(payload: GithubBulkOnboardRequest, client_id: str = Depends(get_current_client)):
    """Onboard multiple GitHub Copilot colleagues in one call.

    Each item is run through the exact same ``onboard github`` command as
    :func:`onboard_github` (including the approval queue), independently -
    one item failing doesn't stop the rest from being processed.
    """
    return [_run(_github_args(item), client_id) for item in payload.items]


@router.post('/onboarding/crowd', response_model=CommandResult)
def onboard_crowd(payload: CrowdOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'crowd', payload.username, payload.team,
                 *(arg for group in payload.groups for arg in ('--group', group))], client_id)


@router.post('/onboarding/jetbrains', response_model=CommandResult)
def onboard_jetbrains(payload: JetbrainsOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'jetbrains', payload.email, payload.team_name], client_id)


@router.post('/onboarding/slack', response_model=CommandResult)
def onboard_slack(payload: SlackOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'slack', payload.email, *payload.member_ids], client_id)


@router.post('/onboarding/offboard', response_model=CommandResult)
def offboard(payload: OffboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['offboard', payload.email], client_id)


@router.post('/onboarding/github_check', response_model=CommandResult)
def github_check(client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'github', 'check'], client_id)


@router.post('/admin/permissions/reload', response_model=CommandResult)
def reload_permissions(client_id: str = Depends(get_current_client)):
    """Invalidate this process's permission cache (subject to the same permission check as chat)."""
    return _run(['permissions', 'reload'], client_id)
