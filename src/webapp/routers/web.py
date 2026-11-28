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
import re
import threading
import time
from typing import Optional

import requests
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from backend.account_storage import LIVE_STATUSES, find_account_by_any_email, find_provisions_by_username, \
    get_account_by_email, get_provision, list_accounts_with_provisions, list_reinvitable_github, list_roles, \
    search_accounts
from backend.crowd_api import CrowdApi
from backend.github_api import GitHubApi
from backend.ldap_directory import LdapDirectory, verify_person
from backend.slack_directory import SlackDirectory
from webapp import config
from webapp.auth import current_user, current_user_json, session_user
from webapp.auth_ldap import ldap_authenticate
from webapp.command_runner import run_bot_command
from webapp.templating import templates

logger = logging.getLogger('webapp.routers.web')

MAX_VALIDATE_USERNAMES = 100
# Alphanumerics or single hyphens, not starting/ending with a hyphen, max 39 chars
GITHUB_LOGIN_RE = re.compile(r'(?=.{1,39}$)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*')

# Every route on ``router`` requires a login (redirect to the login page); ``json_router`` answers 401 instead;
# only ``public_router`` is open.
router = APIRouter(tags=['web'], dependencies=[Depends(current_user)])
json_router = APIRouter(tags=['web'], dependencies=[Depends(current_user_json)])
public_router = APIRouter(tags=['web'])

# Simple declarative form definitions for each onboarding action. Keeping this
# data-driven avoids one template per action. The github 'team' field uses
# type 'team_tree' to render a selectable tree (see build_team_tree /
# form.html) instead of a plain text input.
FORMS = {
    'github': {
        'title': 'Onboard: GitHub Copilot',
        'fields': [
            {'name': 'username', 'label': 'GitHub username', 'required': True,
             'placeholder': 'GitHub Login, no @, no emails'},
            {'name': 'email', 'label': 'Email address', 'required': True},
            {'name': 'team', 'label': 'Team', 'required': True, 'type': 'team_tree',
             'placeholder': 'team-slug'},
            {'name': 'role', 'label': 'Role (optional)', 'required': False, 'type': 'role'},
        ],
    },
    'crowd': {
        'title': 'Onboard: Crowd',
        'fields': [
            {'name': 'username', 'label': 'Email address (or login)', 'required': True},
            {'name': 'team', 'label': 'Crowd group (or canonical team)', 'required': True, 'type': 'team_tree'},
            {'name': 'groups', 'label': 'Extra Crowd groups (optional, comma separated)', 'required': False},
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
            {'name': 'email', 'label': 'Account (name or email address)', 'required': True, 'type': 'slack_account'},
            {'name': 'member_ids', 'label': 'Slack members', 'required': True, 'type': 'slack_members'},
        ],
    },
    'offboard': {
        'title': 'Offboard',
        'fields': [
            {'name': 'email', 'label': 'Email address', 'required': True},
        ],
    },
}


_current_user = session_user


def _github_team_tree() -> tuple[Optional[dict], Optional[str]]:
    """Fetch the GitHub Enterprise team hierarchy for the tree widget.

    Returns ``(tree, error)``: on failure (missing config, GitHub API/network
    error, etc.) ``tree`` is None and ``error`` holds a message to display,
    letting the form gracefully fall back to a plain text field.
    """
    try:
        return GitHubApi().build_team_tree(), None
    except Exception as ex:
        logger.warning(f"Failed to build GitHub team tree: {ex!r}")
        return None, f"Could not load the GitHub team list ({ex}); enter the team slug manually."


def _crowd_group_tree() -> tuple[Optional[dict], Optional[str]]:
    """The Crowd group hierarchy for the tree widget, as ``(tree, error)`` like :func:`_github_team_tree`."""
    try:
        return CrowdApi().build_group_tree(), None
    except Exception as ex:
        logger.warning(f"Failed to build the Crowd group tree: {ex!r}")
        return None, f"Could not load the Crowd group list ({ex}); enter the group name manually."


def _github_email_placeholder() -> str:
    """Example email address for the bulk onboarding form, derived from the
    ``allowed_email_domains`` configured in ``config/github.yml`` (falls back
    to a generic example if unset/unavailable)."""
    try:
        domains = GitHubApi().allowed_email_domains
    except Exception:
        domains = None
    domain = domains[0] if domains else 'example.com'
    return f'your-email-here@{domain}'


@public_router.get('/', include_in_schema=False)
def index(request: Request):
    return RedirectResponse(url=request.url_for('dashboard') if _current_user(request) else request.url_for('login_form'))


@public_router.get('/login', include_in_schema=False)
def login_form(request: Request):
    if _current_user(request):
        return RedirectResponse(url=request.url_for('dashboard'), status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, 'login.html', {'error': None})


@public_router.post('/login', include_in_schema=False)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if user := ldap_authenticate(username, password):
        request.session['user'] = user
        return RedirectResponse(url=request.url_for('dashboard'), status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request, 'login.html', {'error': 'Invalid username or password'},
        status_code=status.HTTP_401_UNAUTHORIZED)


@public_router.get('/logout', include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=request.url_for('login_form'), status_code=status.HTTP_302_FOUND)


@router.get('/onboarding', include_in_schema=False)
def dashboard(request: Request):
    return templates.TemplateResponse(request, 'dashboard.html', {'user': _current_user(request), 'forms': FORMS})


@router.post('/admin/reload-permissions', include_in_schema=False)
def reload_permissions(request: Request):
    """Invalidate this web process's permission cache (the chat bot has its own, in another process)."""
    user = _current_user(request)
    result = run_bot_command(['permissions', 'reload'], user_id=user, channel_name=config.web_channel_name(),
                             team_name=config.web_team_name())
    return templates.TemplateResponse(
        request, 'result.html', {'user': user, 'title': 'Reload permissions', 'result': result})


@router.get('/onboarding/users', include_in_schema=False)
def users_page(request: Request):
    people = [{'account': account, 'provisions': provisions} for account, provisions in
              list_accounts_with_provisions()]
    return templates.TemplateResponse(request, 'users.html', {'user': _current_user(request), 'people': people})


@router.get('/onboarding/{action}', include_in_schema=False)
def onboarding_form(request: Request, action: str):
    form = FORMS.get(action)
    if not form:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    context = {'user': _current_user(request), 'action': action, **form}
    if action == 'github':
        context['fields'] = [{**f, 'placeholder': _github_email_placeholder()} if f['name'] == 'email' else f
                             for f in form['fields']]
        context['team_tree'], context['team_tree_error'] = _github_team_tree()
        context['roles'] = [(r.key, r.display_name) for r in list_roles()]
    if action == 'crowd':
        context['team_tree'], context['team_tree_error'] = _crowd_group_tree()
    return templates.TemplateResponse(request, 'form.html', context)


@router.post('/onboarding/{action}', include_in_schema=False)
async def onboarding_submit(request: Request, action: str):
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


@json_router.post('/onboarding/github/validate-users', include_in_schema=False)
async def github_validate_users(request: Request):
    """Server-side check that GitHub usernames exist, for the onboarding forms' JS validation.

    Body: ``{"usernames": [...]}``. Returns ``{"results": {<input>: {"status": "ok"|"not_found"|"invalid"|"error",
    "login": <canonical login>, "message": ...}}}``. ``error`` means the lookup itself failed (e.g. rate limit),
    so the form shouldn't treat the username as wrong.
    """
    try:
        usernames = (await request.json())['usernames']
        if not isinstance(usernames, list) or not all(isinstance(u, str) for u in usernames):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JSONResponse({'error': 'Expected {"usernames": [...]}'}, status_code=status.HTTP_400_BAD_REQUEST)
    unique = list(dict.fromkeys(u.strip() for u in usernames if u.strip()))
    if len(unique) > MAX_VALIDATE_USERNAMES:
        return JSONResponse({'error': f'At most {MAX_VALIDATE_USERNAMES} usernames per request'},
                            status_code=status.HTTP_400_BAD_REQUEST)
    results = await run_in_threadpool(_check_github_usernames, unique)
    return {'results': results}


def _check_github_usernames(usernames: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    github = GitHubApi()
    for username in usernames:
        # Also guards the URL built from the username in GitHubApi.get_user_details
        if not GITHUB_LOGIN_RE.fullmatch(username):
            results[username] = {'status': 'invalid', 'message': 'Not a valid GitHub username (no @, no email)'}
            continue
        try:
            results[username] = {'status': 'ok', 'login': github.get_user_details(username).get('login', username)}
        except requests.HTTPError as ex:
            if ex.response is not None and ex.response.status_code == 404:
                results[username] = {'status': 'not_found', 'message': 'GitHub user not found'}
            else:
                logger.warning(f"GitHub lookup failed for {username}: {ex}")
                results[username] = {'status': 'error', 'message': f'Could not check: {ex}'}
        except Exception as ex:
            logger.warning(f"GitHub lookup failed for {username}: {ex!r}")
            results[username] = {'status': 'error', 'message': f'Could not check: {ex}'}

    # Accounts that exist on GitHub but are already onboarded (per our database)
    found = [u for u, r in results.items() if r['status'] == 'ok']
    try:
        existing = {p.data.get('username', '').lower(): p for p in find_provisions_by_username('github', found)}
    except Exception as ex:
        logger.warning(f"Database lookup of existing provisions failed: {ex!r}")
        existing = {}
    for username in found:
        if provision := existing.get(results[username]['login'].lower()) or existing.get(username.lower()):
            results[username] = {
                'status': 'already_onboarded', 'login': results[username]['login'],
                'message': f"Already onboarded ({provision.status}, {provision.data.get('email', 'unknown email')})"}
    return results


@json_router.post('/onboarding/crowd/verify', include_in_schema=False)
async def crowd_verify_emails(request: Request):
    """Check email addresses (or logins) in the directory, for the Crowd onboarding forms.

    Body: ``{"emails": [...]}``. Returns ``{"results": {<input>: {"status": "ok"|"not_found"|"already_onboarded"|
    "error", "mail", "given_name", "surname", "expected_given_name", "expected_surname", "mismatch", "message"}}}``.
    The expected names are the romanized Greek name; ``mismatch`` tells the form to offer editing the name.
    """
    try:
        emails = (await request.json())['emails']
        if not isinstance(emails, list) or not all(isinstance(e, str) for e in emails):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JSONResponse({'error': 'Expected {"emails": [...]}'}, status_code=status.HTTP_400_BAD_REQUEST)
    unique = list(dict.fromkeys(e.strip() for e in emails if e.strip()))
    if len(unique) > MAX_VALIDATE_USERNAMES:
        return JSONResponse({'error': f'At most {MAX_VALIDATE_USERNAMES} addresses per request'},
                            status_code=status.HTTP_400_BAD_REQUEST)
    return {'results': await run_in_threadpool(_check_crowd_emails, unique)}


def _check_crowd_emails(emails: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    try:
        directory = LdapDirectory()
    except Exception as ex:
        logger.warning(f"Directory is not available: {ex!r}")
        return {e: {'status': 'error', 'message': f'Could not check: {ex}'} for e in emails}
    try:
        for email in emails:
            try:
                person, error = verify_person(email, directory=directory)
            except Exception as ex:
                logger.warning(f"Directory lookup failed for {email}: {ex!r}")
                results[email] = {'status': 'error', 'message': f'Could not check: {ex}'}
                continue
            if error:
                results[email] = {'status': 'not_found', 'message': error}
                continue
            result = {'status': 'ok', 'mail': person.mail, 'given_name': person.first_name,
                      'surname': person.last_name, 'expected_given_name': person.expected_first_name,
                      'expected_surname': person.expected_last_name, 'mismatch': person.name_mismatch}
            try:
                account = get_account_by_email(person.mail)
                existing = get_provision(account.id, 'crowd') if account else None
                if existing and existing.status in LIVE_STATUSES:
                    result.update(status='already_onboarded',
                                  message=f"Already has a Crowd user ({existing.data.get('username', 'unknown')})")
            except Exception as ex:
                logger.warning(f"Database lookup of the Crowd provision of {email} failed: {ex!r}")
            results[email] = result
    finally:
        directory.close()
    return results


@json_router.get('/onboarding/slack/accounts', include_in_schema=False)
async def slack_find_accounts(q: str = ''):
    """Accounts whose name or email contains ``q`` (at least 2 characters), for the Slack form's autocomplete."""
    if len(q.strip()) < 2:
        return {'accounts': []}
    accounts = await run_in_threadpool(search_accounts, q)
    return {'accounts': [{'name': a.name, 'email': a.primary_email, 'team': a.team} for a in accounts]}


@json_router.get('/onboarding/slack/account', include_in_schema=False)
async def slack_account(email: str):
    """What the bot knows about the account of ``email`` (primary or additional address), for the Slack form."""
    return await run_in_threadpool(_slack_account_details, email)


def _slack_account_details(email: str) -> dict:
    account = find_account_by_any_email(email.strip())
    if account is None:
        return {'found': False}
    provision = get_provision(account.id, 'slack')
    data = provision.data if provision else {}
    return {
        'found': True, 'name': account.name, 'email': account.primary_email, 'team': account.team,
        'additional_emails': list(account.metadata.get('additional_emails', [])),
        'member_ids': list(data.get('member_ids', [])), 'slack_status': provision.status if provision else None}


_SLACK_MEMBERS_TTL = 1800
_slack_members: dict = {'time': 0.0, 'members': None}
_slack_members_lock = threading.Lock()


def _load_slack_members(refresh: bool) -> list[dict]:
    """Workspace members, cached for 30 minutes per process (listing them takes several API calls)."""
    with _slack_members_lock:
        if refresh or _slack_members['members'] is None or time.time() - _slack_members['time'] > _SLACK_MEMBERS_TTL:
            users = SlackDirectory().list_users()
            _slack_members['members'] = sorted(
                ({'id': u.id, 'name': u.name, 'email': u.email, 'deleted': u.deleted}
                 for u in users if not u.is_bot and u.id != 'USLACKBOT'),
                key=lambda m: (m['deleted'], m['name'].lower()))
            _slack_members['time'] = time.time()
        return _slack_members['members']


@json_router.get('/onboarding/slack/members', include_in_schema=False)
async def slack_members(refresh: bool = False):
    """The Slack workspace members (id, name, sign-in email, deactivated flag) for the member picker."""
    try:
        return {'members': await run_in_threadpool(_load_slack_members, refresh)}
    except Exception as ex:
        logger.warning(f"Failed to list the Slack members: {ex!r}")
        return JSONResponse({'error': f'Could not load the Slack members ({ex}); enter the ids manually.'},
                            status_code=status.HTTP_502_BAD_GATEWAY)


@router.get('/onboarding/crowd/bulk', include_in_schema=False)
def crowd_bulk_form(request: Request):
    team_tree, team_tree_error = _crowd_group_tree()
    return templates.TemplateResponse(request, 'bulk_crowd.html', {
        'user': _current_user(request), 'team_tree': team_tree, 'team_tree_error': team_tree_error})


@router.post('/onboarding/crowd/bulk', include_in_schema=False)
async def crowd_bulk_submit(request: Request):
    form_data = await request.form()
    user = _current_user(request)
    rows = []
    for email, team, given_name, surname in zip(*(form_data.getlist(k) for k in ('email', 'team', 'given_name',
                                                                                 'surname'))):
        email, team, given_name, surname = email.strip(), team.strip(), given_name.strip(), surname.strip()
        if not (email or team):
            continue  # fully blank row - silently skipped
        if not (email and team):
            rows.append({'email': email, 'team': team, 'result': None, 'error': 'Missing email or team.'})
            continue
        args = ['onboard', 'crowd', email, team]
        for option, value in (('--given-name', given_name), ('--surname', surname)):
            if value:
                args += [option, value]
        result = run_bot_command(args, user_id=user, channel_name=config.web_channel_name(),
                                 team_name=config.web_team_name())
        rows.append({'email': email, 'team': team, 'name': f'{given_name} {surname}'.strip(), 'result': result,
                     'error': None})
    return templates.TemplateResponse(request, 'bulk_crowd_result.html', {'user': user, 'rows': rows})


@router.get('/onboarding/github/bulk', include_in_schema=False)
def github_bulk_form(request: Request):
    team_tree, team_tree_error = _github_team_tree()
    team_options = GitHubApi.flatten_team_tree(team_tree) if team_tree else None
    return templates.TemplateResponse(request, 'bulk_github.html', {
        'user': _current_user(request), 'team_tree': team_tree, 'team_tree_error': team_tree_error,
        'team_options': team_options, 'email_placeholder': _github_email_placeholder(),
        'roles': [(r.key, r.display_name) for r in list_roles()],
    })


@router.post('/onboarding/github/bulk', include_in_schema=False)
async def github_bulk_submit(request: Request):

    form_data = await request.form()
    usernames = form_data.getlist('username')
    emails = form_data.getlist('email')
    teams = form_data.getlist('team')
    roles = form_data.getlist('role')

    user = _current_user(request)
    rows = []
    for username, email, team, role in zip(usernames, emails, teams, roles):
        username, email, team, role = username.strip(), email.strip(), team.strip(), role.strip()
        if not (username or email or team):
            continue  # fully blank row - silently skipped

        if not (username and email and team):
            rows.append({'username': username, 'email': email, 'team': team, 'role': role, 'result': None,
                        'error': 'Missing GitHub username, email, or team.'})
            continue

        args = ['onboard', 'github', username, email, team]
        if role:
            args += ['--role', role]
        result = run_bot_command(
            args, user_id=user,
            channel_name=config.web_channel_name(), team_name=config.web_team_name())
        rows.append({'username': username, 'email': email, 'team': team, 'role': role, 'result': result,
                     'error': None})

    return templates.TemplateResponse(request, 'bulk_result.html', {'user': user, 'rows': rows})


MISSING_EMAILS_TTL = 30 * 60  # seconds a finished scan stays cached
# One scan shared by all users; state is per process, so this assumes a single uvicorn worker.
_missing_job: dict = {}
_missing_lock = threading.Lock()


def _run_missing_job(job: dict):
    def progress(message, done, total):
        job.update(message=message, done=done, total=total)

    try:
        job['members'] = GitHubApi().get_members_without_email(progress)
        job['status'] = 'done'
    except Exception as ex:
        logger.warning(f"Failed to list GitHub members without an email: {ex!r}")
        job.update(status='error', error=f"Could not load the GitHub members ({ex}).")
    job['finished'] = time.time()


def _missing_job_get(restart: bool = False) -> dict:
    """The current scan, starting a new one if there is none, it is stale, or ``restart`` is set."""
    global _missing_job
    with _missing_lock:
        job = _missing_job
        stale = job.get('status') != 'running' and time.time() - job.get('finished', 0) > MISSING_EMAILS_TTL
        if not job or stale or (restart and job.get('status') != 'running'):
            job = _missing_job = {'status': 'running', 'message': 'Starting', 'done': 0, 'total': 0,
                                  'members': [], 'error': None}
            threading.Thread(target=_run_missing_job, args=(job,), daemon=True).start()
        return job


@json_router.get('/onboarding/github/missing-emails/status', include_in_schema=False)
def missing_emails_status():
    job = _missing_job_get()
    return {k: job.get(k) for k in ('status', 'message', 'done', 'total', 'error')}


@router.get('/onboarding/github/missing-emails', include_in_schema=False)
def missing_emails_form(request: Request, refresh: bool = False):
    job = _missing_job_get(restart=refresh)
    context = {'user': _current_user(request), 'job': job, 'error': job.get('error'),
               'email_placeholder': _github_email_placeholder(), 'members': [], 'total_members': 0}
    if job['status'] == 'done':
        # All rows go to the page; filtering, sorting and paging happen in the browser so one submit covers them all
        context.update(members=job['members'], total_members=len(job['members']))
    return templates.TemplateResponse(request, 'missing_emails.html', context)


@router.post('/onboarding/github/missing-emails', include_in_schema=False)
async def missing_emails_submit(request: Request):

    form_data = await request.form()
    user = _current_user(request)
    rows = []
    for username, email in zip(form_data.getlist('username'), form_data.getlist('email')):
        username, email = username.strip(), email.strip()
        if not (username and email):
            continue  # nothing filled in for this user
        result = run_bot_command(
            ['onboard', 'github', 'set-email', username, email], user_id=user,
            channel_name=config.web_channel_name(), team_name=config.web_team_name())
        rows.append({'username': username, 'email': email, 'result': result})

    submitted = {r['username'].lower() for r in rows}
    with _missing_lock:
        if _missing_job.get('status') == 'done':
            _missing_job['members'] = [m for m in _missing_job['members'] if m['login'].lower() not in submitted]

    return templates.TemplateResponse(request, 'missing_emails_result.html', {'user': user, 'rows': rows})


@router.get('/onboarding/github/reinvite', include_in_schema=False)
def reinvite_form(request: Request):
    people = list_reinvitable_github()
    return templates.TemplateResponse(request, 'reinvite.html', {'user': _current_user(request), 'people': people})


@router.post('/onboarding/github/reinvite', include_in_schema=False)
async def reinvite_submit(request: Request):

    form_data = await request.form()
    user = _current_user(request)
    rows = []
    for email in dict.fromkeys(e.strip() for e in form_data.getlist('email')):
        if not email:
            continue
        result = run_bot_command(
            ['onboard', 'github', 'reinvite', email], user_id=user,
            channel_name=config.web_channel_name(), team_name=config.web_team_name())
        rows.append({'email': email, 'result': result})
    return templates.TemplateResponse(request, 'reinvite_result.html', {'user': user, 'rows': rows})


@router.get('/onboarding/move/bulk', include_in_schema=False)
def move_bulk_form(request: Request):
    team_tree, team_tree_error = _github_team_tree()
    team_options = GitHubApi.flatten_team_tree(team_tree) if team_tree else None
    return templates.TemplateResponse(request, 'bulk_move.html', {
        'user': _current_user(request), 'team_tree': team_tree, 'team_tree_error': team_tree_error,
        'team_options': team_options, 'email_placeholder': _github_email_placeholder(),
    })


@router.post('/onboarding/move/bulk', include_in_schema=False)
async def move_bulk_submit(request: Request):

    form_data = await request.form()
    user = _current_user(request)
    rows = []
    for email, team in zip(form_data.getlist('email'), form_data.getlist('team')):
        email, team = email.strip(), team.strip()
        if not (email or team):
            continue  # fully blank row - silently skipped

        if not (email and team):
            rows.append({'email': email, 'team': team, 'result': None, 'error': 'Missing email or team.'})
            continue

        result = run_bot_command(
            ['onboard', 'move', email, team], user_id=user,
            channel_name=config.web_channel_name(), team_name=config.web_team_name())
        rows.append({'email': email, 'team': team, 'result': result, 'error': None})

    return templates.TemplateResponse(request, 'bulk_move_result.html', {'user': user, 'rows': rows})


def _build_args(action: str, form_data) -> list[str] | None:
    if action == 'github':
        args = ['onboard', 'github', form_data['username'], form_data['email'], form_data['team']]
        if role := str(form_data.get('role') or '').strip():
            args += ['--role', role]
        return args
    if action == 'crowd':
        args = ['onboard', 'crowd', form_data['username'], form_data['team']]
        for group in str(form_data.get('groups') or '').split(','):
            if group.strip():
                args += ['--group', group.strip()]
        for field, option in (('given_name', '--given-name'), ('surname', '--surname')):
            if value := str(form_data.get(field) or '').strip():
                args += [option, value]
        return args
    if action == 'jetbrains':
        return ['onboard', 'jetbrains', form_data['email'], form_data['team_name']]
    if action == 'slack':
        member_ids = [m.strip() for value in form_data.getlist('member_ids') for m in str(value).split(',')
                      if m.strip()]
        if not member_ids:
            return None
        return ['onboard', 'slack', form_data['email'], *dict.fromkeys(member_ids)]
    if action == 'offboard':
        return ['offboard', form_data['email']]
    return None
