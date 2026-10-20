# -*- coding: utf-8 -*-
"""Editing of the ``permission_rules`` table (used by the web UI's management page).

Runtime resolution stays in :mod:`backend.permissions`. Every change made here is
recorded in ``permission_rules_history`` in the same transaction, and invalidates the
in-process permission cache afterwards (other processes still need ``permissions reload``).
"""
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import permissions
from backend.models.permissions import PermissionRule, PermissionRuleHistory


class RuleError(ValueError):
    """A rule change was rejected (duplicate key, unknown id, ...)."""


def _as_dict(rule: PermissionRule) -> dict:
    return {
        'id': rule.id, 'function_name': rule.function_name, 'environment': rule.environment, 'role': rule.role,
        'users': list(rule.users or []), 'channels': list(rule.channels or []), 'extra': dict(rule.extra or {}),
        'updated_at': rule.updated_at,
    }


def _snapshot(rule: dict) -> dict:
    return {k: rule[k] for k in ('users', 'channels', 'extra')}


def _record(session: Session, action: str, changed_by: str, rule: dict,
            before: Optional[dict], after: Optional[dict]) -> None:
    session.add(PermissionRuleHistory(
        function_name=rule['function_name'], environment=rule['environment'], role=rule['role'],
        action=action, changed_by=changed_by, before=before, after=after))


def list_rules() -> list[dict]:
    with Session(permissions._engine()) as session:
        rules = session.scalars(select(PermissionRule).order_by(
            PermissionRule.function_name, PermissionRule.environment, PermissionRule.role))
        return [_as_dict(r) for r in rules]


def get_rule_by_id(rule_id: int) -> Optional[dict]:
    with Session(permissions._engine()) as session:
        rule = session.get(PermissionRule, rule_id)
        return _as_dict(rule) if rule else None


def create_rule(function_name: str, environment: str, role: str, users: list, channels: list,
                extra: dict[str, Any], changed_by: str) -> dict:
    try:
        with Session(permissions._engine()) as session, session.begin():
            rule = PermissionRule(function_name=function_name, environment=environment, role=role,
                                  users=users, channels=channels, extra=extra)
            session.add(rule)
            session.flush()
            created = _as_dict(rule)
            _record(session, 'create', changed_by, created, None, _snapshot(created))
    except IntegrityError:
        raise RuleError(f"A rule for {function_name!r} environment={environment!r} role={role!r} already exists")
    permissions.invalidate_cache()
    return created


def update_rule(rule_id: int, function_name: str, environment: str, role: str, users: list, channels: list,
                extra: dict[str, Any], changed_by: str) -> Optional[dict]:
    """Returns the updated rule, or ``None`` if nothing changed."""
    try:
        with Session(permissions._engine()) as session, session.begin():
            rule = session.get(PermissionRule, rule_id)
            if rule is None:
                raise RuleError(f"Rule {rule_id} no longer exists")
            old = _as_dict(rule)
            new_values = {'function_name': function_name, 'environment': environment, 'role': role,
                          'users': users, 'channels': channels, 'extra': extra}
            if all(old[k] == v for k, v in new_values.items()):
                return None
            for key, value in new_values.items():
                setattr(rule, key, value)
            rule.updated_at = func.now()
            session.flush()  # a unique violation surfaces here, inside the try
            session.refresh(rule)
            updated = _as_dict(rule)
            # A renamed key is recorded under the new key, with the old key visible in `before`
            before = {**_snapshot(old), **{k: old[k] for k in ('function_name', 'environment', 'role')}}
            _record(session, 'update', changed_by, updated, before, _snapshot(updated))
    except IntegrityError:
        raise RuleError(f"A rule for {function_name!r} environment={environment!r} role={role!r} already exists")
    permissions.invalidate_cache()
    return updated


def delete_rule(rule_id: int, changed_by: str) -> dict:
    with Session(permissions._engine()) as session, session.begin():
        rule = session.get(PermissionRule, rule_id)
        if rule is None:
            raise RuleError(f"Rule {rule_id} no longer exists")
        deleted = _as_dict(rule)
        session.delete(rule)
        _record(session, 'delete', changed_by, deleted, _snapshot(deleted), None)
    permissions.invalidate_cache()
    return deleted


def list_history(function_name: Optional[str] = None, limit: int = 200) -> list[dict]:
    query = select(PermissionRuleHistory).order_by(PermissionRuleHistory.changed_at.desc(),
                                                  PermissionRuleHistory.id.desc()).limit(limit)
    if function_name:
        query = query.where(PermissionRuleHistory.function_name == function_name)
    with Session(permissions._engine()) as session:
        return [{
            'function_name': h.function_name, 'environment': h.environment, 'role': h.role, 'action': h.action,
            'changed_by': h.changed_by, 'changed_at': h.changed_at, 'before': h.before, 'after': h.after,
        } for h in session.scalars(query)]
