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
from webapp.auth_oauth2 import create_access_token, decode_access_token, validate_client_credentials
from webapp.command_runner import run_bot_command
from webapp.models import (CommandResult, CrowdOnboardRequest, GithubOnboardRequest,
                           JetbrainsOnboardRequest, OffboardRequest, SlackOnboardRequest,
                           TokenResponse)

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


def get_current_client(token: str = Depends(oauth2_scheme)) -> str:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Not authenticated',
                            headers={'WWW-Authenticate': 'Bearer'})
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token',
                            headers={'WWW-Authenticate': 'Bearer'})
    return payload['sub']


def _run(args: list[str], client_id: str) -> CommandResult:
    result = run_bot_command(
        args, user_id=client_id, channel_name=config.api_channel_name(), team_name=config.api_team_name())
    return CommandResult(
        success=result.success, exit_code=result.exit_code, output=result.output,
        messages=result.messages, error=result.error)


@router.post('/onboarding/github', response_model=CommandResult)
def onboard_github(payload: GithubOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'github', payload.username, payload.email, payload.team], client_id)


@router.post('/onboarding/crowd', response_model=CommandResult)
def onboard_crowd(payload: CrowdOnboardRequest, client_id: str = Depends(get_current_client)):
    return _run(['onboard', 'crowd', payload.username, payload.team], client_id)


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
    return _run(['onboard', 'github_check'], client_id)
