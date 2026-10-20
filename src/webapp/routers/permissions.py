"""Web UI page for managing the ``permission_rules`` table.

Access is itself governed by a permission rule (function name :data:`MANAGE_FUNCTION`, global
environment, role ``default``), matched against the web UI pseudo-channel like every other
web action. Denies by default when the rule is missing. Every change is audited in
``permission_rules_history`` and invalidates this process's permission cache.
"""
import json
import logging
import pathlib
import re
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from backend import permission_admin, permissions
from backend.configuration import user_allowed
from webapp import config

logger = logging.getLogger('webapp.routers.permissions')

MANAGE_FUNCTION = 'webapp.routers.permissions:manage'
FUNCTION_NAME_RE = re.compile(r'[\w.]+:\w+')
ROLE_RE = re.compile(r'\w+')

router = APIRouter(prefix='/admin/permissions', tags=['web'])
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent.parent / 'templates'))
templates.env.filters['tojson'] = json.dumps


def _may_manage(user: str) -> bool:
    return _rule_allows(permissions.get_rule(MANAGE_FUNCTION), user)


def _rule_allows(rule: Optional[dict], user: str) -> bool:
    if rule is None:
        return False
    channels = rule['channels']
    if '*' not in channels and config.web_channel_name() not in channels:
        return False
    return user_allowed(config.web_team_name(), user, rule['users'])


def can_manage(user: Optional[str]) -> bool:
    """For the dashboard: whether to show the link. Never raises."""
    try:
        return bool(user) and _may_manage(user)
    except Exception as ex:
        logger.warning(f"Could not evaluate {MANAGE_FUNCTION}: {ex!r}")
        return False


def _authorize(request: Request) -> str:
    """The logged-in user, if allowed to manage rules. Raises HTTPException/redirect otherwise."""
    user = request.session.get('user')
    if not user:
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={'Location': str(request.url_for('login_form'))})
    try:
        allowed = _may_manage(user)
    except RuntimeError as ex:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(ex))
    if not allowed:
        logger.warning(f"{user} tried to manage permission rules without being allowed")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You don't have permission to manage permission rules.")
    return user


def _flash(request: Request, text: str, is_error: bool = False) -> None:
    request.session['flash'] = {'text': text, 'is_error': is_error}


def _lines(value: str) -> list[str]:
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def _parse_form(function_name: str, environment: str, role: str, users: str, channels: str,
                extra: str) -> tuple[dict, list[str]]:
    errors = []
    function_name, environment, role = function_name.strip(), environment.strip(), role.strip()
    if not FUNCTION_NAME_RE.fullmatch(function_name):
        errors.append("Function name must look like 'package.module:function'.")
    if not ROLE_RE.fullmatch(role):
        errors.append("Role is required (letters, digits, underscore).")
    extra_value = {}
    if extra.strip():
        try:
            extra_value = json.loads(extra)
            if not isinstance(extra_value, dict):
                raise ValueError
        except ValueError:
            errors.append("Extra must be a JSON object, e.g. {} .")
    return {'function_name': function_name, 'environment': environment, 'role': role,
            'users': _lines(users), 'channels': _lines(channels), 'extra': extra_value}, errors


def _is_manage_rule(rule: dict) -> bool:
    return (rule['function_name'], rule['environment'], rule['role']) == (
        MANAGE_FUNCTION, permissions.GLOBAL_ENVIRONMENT, permissions.DEFAULT_ROLE)


def _lockout(rule: dict, user: str) -> bool:
    """True if saving ``rule`` would remove the acting user's own access to this page."""
    return _is_manage_rule(rule) and not _rule_allows(rule, user)


@router.get('', include_in_schema=False)
def list_rules(request: Request):
    user = _authorize(request)
    flash = request.session.pop('flash', None)
    return templates.TemplateResponse(request, 'permissions.html', {
        'user': user, 'rules': permission_admin.list_rules(), 'flash': flash, 'manage_function': MANAGE_FUNCTION})


@router.get('/history', include_in_schema=False)
def history(request: Request, function_name: Optional[str] = None):
    user = _authorize(request)
    return templates.TemplateResponse(request, 'permissions_history.html', {
        'user': user, 'entries': permission_admin.list_history(function_name or None),
        'function_name': function_name})


@router.get('/new', include_in_schema=False)
def new_form(request: Request):
    user = _authorize(request)
    return templates.TemplateResponse(request, 'permission_form.html', {
        'user': user, 'rule': {'function_name': '', 'environment': '', 'role': permissions.DEFAULT_ROLE,
                               'users': [], 'channels': [], 'extra': {}},
        'rule_id': None, 'errors': []})


@router.post('/new', include_in_schema=False)
def create(request: Request, function_name: str = Form(''), environment: str = Form(''), role: str = Form(''),
           users: str = Form(''), channels: str = Form(''), extra: str = Form('')):
    user = _authorize(request)
    rule, errors = _parse_form(function_name, environment, role, users, channels, extra)
    if not errors and _lockout(rule, user):
        errors.append("This would remove your own access to this page.")
    if not errors:
        try:
            permission_admin.create_rule(**rule, changed_by=user)
        except permission_admin.RuleError as ex:
            errors.append(str(ex))
    if errors:
        return templates.TemplateResponse(request, 'permission_form.html', {
            'user': user, 'rule': {**rule, 'extra': rule['extra']}, 'rule_id': None, 'errors': errors,
            'raw_extra': extra}, status_code=status.HTTP_400_BAD_REQUEST)
    _flash(request, f"Created rule for {rule['function_name']}.")
    return RedirectResponse(request.url_for('list_rules'), status_code=status.HTTP_303_SEE_OTHER)


@router.get('/{rule_id}/edit', include_in_schema=False)
def edit_form(request: Request, rule_id: int):
    user = _authorize(request)
    rule = permission_admin.get_rule_by_id(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(request, 'permission_form.html', {
        'user': user, 'rule': rule, 'rule_id': rule_id, 'errors': []})


@router.post('/{rule_id}/edit', include_in_schema=False)
def update(request: Request, rule_id: int, function_name: str = Form(''), environment: str = Form(''),
           role: str = Form(''), users: str = Form(''), channels: str = Form(''), extra: str = Form('')):
    user = _authorize(request)
    current = permission_admin.get_rule_by_id(rule_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    rule, errors = _parse_form(function_name, environment, role, users, channels, extra)
    if not errors:
        # Renaming the page's own rule away would also lock everybody out
        if _is_manage_rule(current) and not _is_manage_rule(rule):
            errors.append("The key of this page's own rule cannot be changed.")
        elif _lockout(rule, user):
            errors.append("This would remove your own access to this page.")
    if not errors:
        try:
            changed = permission_admin.update_rule(rule_id, **rule, changed_by=user)
        except permission_admin.RuleError as ex:
            errors.append(str(ex))
    if errors:
        return templates.TemplateResponse(request, 'permission_form.html', {
            'user': user, 'rule': rule, 'rule_id': rule_id, 'errors': errors, 'raw_extra': extra},
            status_code=status.HTTP_400_BAD_REQUEST)
    _flash(request, f"Updated rule for {rule['function_name']}." if changed else "No changes to save.")
    return RedirectResponse(request.url_for('list_rules'), status_code=status.HTTP_303_SEE_OTHER)


@router.post('/{rule_id}/delete', include_in_schema=False)
def delete(request: Request, rule_id: int):
    user = _authorize(request)
    rule = permission_admin.get_rule_by_id(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if _is_manage_rule(rule):
        _flash(request, "The rule that governs this page cannot be deleted here.", is_error=True)
    else:
        try:
            permission_admin.delete_rule(rule_id, changed_by=user)
            _flash(request, f"Deleted rule for {rule['function_name']}.")
        except permission_admin.RuleError as ex:
            _flash(request, str(ex), is_error=True)
    return RedirectResponse(request.url_for('list_rules'), status_code=status.HTTP_303_SEE_OTHER)
