"""What the logged-in user may do, for showing or disabling links in the templates.

This only mirrors the real checks (``requires_approval`` requester rules and the permission-management rules),
using the same ``permission_rules`` and the web UI pseudo-channel; it never replaces them: the commands and routes
still enforce on every request. Used from templates as ``can(request, '<key>')``.
"""
import logging
from typing import Optional

from fastapi import Request

from backend import permissions
from backend.approval import ROLE_REQUEST
from backend.configuration import user_allowed
from webapp import config
from webapp.auth import session_user

logger = logging.getLogger('webapp.capabilities')

MANAGE_FUNCTION = 'webapp.routers.permissions:manage'
RELOAD_FUNCTION = 'commands.permissions:reload_permissions'

# key -> (permission rule function name, role). The requester rules belong to the approval-gated commands each page runs.
CAPABILITIES = {
    'onboard_github': ('commands.onboarding.github:onboard_github', ROLE_REQUEST),
    'onboard_crowd': ('commands.onboarding.crowd:onboard_crowd', ROLE_REQUEST),
    'onboard_jetbrains': ('commands.onboarding.jetbrains:onboard_jetbrains', ROLE_REQUEST),
    'onboard_slack': ('commands.onboarding:onboard_slack', ROLE_REQUEST),
    'offboard': ('commands.onboarding:offboard', ROLE_REQUEST),
    'move': ('commands.onboarding.team:onboard_move', ROLE_REQUEST),
    'set_email': ('commands.onboarding.github:github_set_email', ROLE_REQUEST),
    'reinvite': ('commands.onboarding.github:github_reinvite', ROLE_REQUEST),
    'manage_permissions': (MANAGE_FUNCTION, permissions.DEFAULT_ROLE),
    'reload_permissions': (RELOAD_FUNCTION, permissions.DEFAULT_ROLE),
}
# The action pages of ``web.FORMS`` that are named differently from their command
FORM_CAPABILITIES = {'github': 'onboard_github', 'crowd': 'onboard_crowd', 'jetbrains': 'onboard_jetbrains',
                     'slack': 'onboard_slack', 'offboard': 'offboard'}


def rule_allows(rule: Optional[dict], user: str) -> bool:
    """Whether ``rule`` lets ``user`` act from the web UI channel. A missing rule denies."""
    if rule is None:
        return False
    channels = rule['channels']
    if '*' not in channels and config.web_channel_name() not in channels:
        return False
    return user_allowed(config.web_team_name(), user, rule['users'])


def can_user(user: Optional[str], key: str, strict: bool = False) -> bool:
    """Whether ``user`` may use the capability ``key``. A failure to evaluate means no, unless ``strict`` (then it raises)."""
    function_name, role = CAPABILITIES[key]
    try:
        return bool(user) and rule_allows(permissions.get_rule(function_name, permissions.GLOBAL_ENVIRONMENT, role), user)
    except Exception as ex:
        if strict:
            raise
        logger.warning(f"Could not evaluate {function_name} ({role}): {ex!r}")
        return False


def can(request: Request, key: str) -> bool:
    """Template helper: :func:`can_user` for the request's user, evaluated once per request and key."""
    cache = request.scope.setdefault('capabilities', {})
    if key not in cache:
        cache[key] = can_user(session_user(request), FORM_CAPABILITIES.get(key, key))
    return cache[key]
