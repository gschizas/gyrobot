# -*- coding: utf-8 -*-
"""Runtime permission resolution, backed by the ``permission_rules`` table.

Consolidates the per-command permission data migrated from the legacy
``config/*.permissions.yml`` files (see ``scripts/migrate_permissions.py``)
into a single Postgres-backed source of truth, keyed by fully-qualified
function name (``func.__module__ + ':' + func.__name__``), environment (or
``GLOBAL_ENVIRONMENT`` for commands with no per-namespace axis, e.g. the
approval queue) and role (``'default'`` for @check_security-gated commands;
``'requester'``/``'approver'`` for @requires_approval-gated commands).

All rows are loaded into an in-process cache on first use and kept until
explicitly invalidated - there is no automatic TTL/expiry, so a cache reload
is required after editing the table for changes to take effect. Invalidate via
:func:`invalidate_cache`, exposed to chat users through the
``permissions reload`` command (see ``commands/permissions.py``).
"""
import os
import threading
from typing import Optional

import psycopg
from psycopg.rows import dict_row

# Sentinel used for the `environment` column/key when a function has no
# per-environment/namespace axis (e.g. approval-queue commands). Deliberately
# NOT NULL: Postgres treats NULL <> NULL, so a NULL environment would break
# the UNIQUE(function_name, environment, role) upsert used by the migration
# script (every re-run would insert new rows instead of updating).
GLOBAL_ENVIRONMENT = ''
DEFAULT_ROLE = 'default'

_lock = threading.Lock()
# (function_name, environment, role) -> {'users': [...], 'channels': [...], 'extra': {...}}
_cache: Optional[dict] = None


def function_full_name(func) -> str:
    """The fully-qualified name used as the `function_name` key everywhere:
    ``func.__module__ + ':' + func.__name__``."""
    return f'{func.__module__}:{func.__name__}'


def _database_url() -> str:
    try:
        return os.environ['PERMISSIONS_DATABASE_URL']
    except KeyError:
        raise RuntimeError(
            "PERMISSIONS_DATABASE_URL not set - required to resolve permissions "
            "from the permission_rules table. See scripts/migrate_permissions.py "
            "--to-db to populate it.")


def _load_all() -> dict:
    cache = {}
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT function_name, environment, role, users, channels, extra "
                "FROM permission_rules;")
            for row in cur.fetchall():
                cache[(row['function_name'], row['environment'], row['role'])] = {
                    'users': row['users'] or [],
                    'channels': row['channels'] or [],
                    'extra': row['extra'] or {},
                }
    return cache


def _ensure_cache() -> dict:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:  # re-check inside the lock (another thread may have loaded it)
                _cache = _load_all()
    return _cache


def invalidate_cache() -> None:
    """Force the next :func:`get_rule` call to reload every row from the database."""
    global _cache
    with _lock:
        _cache = None


def get_rule(function_name: str, environment: str = GLOBAL_ENVIRONMENT,
            role: str = DEFAULT_ROLE) -> Optional[dict]:
    """Return ``{'users': [...], 'channels': [...], 'extra': {...}}`` for the
    given ``(function_name, environment, role)``, or ``None`` if no such rule
    is configured (callers should fail closed - deny by default - in that case)."""
    cache = _ensure_cache()
    return cache.get((function_name, environment, role))
