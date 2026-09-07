"""Generic command-approval queue.

Commands decorated with :func:`requires_approval` do not run immediately. Instead,
the invocation (command name + click parameters) is serialized into the
``approval_requests`` table and a notification is sent. Designated approvers later
run the ``approvals`` command group to approve/reject pending requests; on approval
the original command body is executed via :func:`execute_approved`.

Storage is PostgreSQL (psycopg3), configured through ``APPROVAL_DATABASE_URL``.
Permissions (who may request/approve, allowed channels, ``notify_channel``,
``allow_self``) come from the ``permission_rules`` table via
``backend.permissions`` (see ``scripts/migrate_permissions.py``), not from YAML.
Only commands whose click parameters are JSON-serializable can be gated.
"""
import functools
import os
from typing import Callable, List, Optional

import click
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend import permissions
from backend.configuration import user_allowed
from backend.email_logging import send_email_log
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

# Roles distinguished within the approval queue: who may request approval-gated
# commands vs. who may approve them. These match the `role` column values
# written by scripts/migrate_permissions.py.
ROLE_REQUEST = 'requester'
ROLE_APPROVE = 'approver'

# Sentinel function name for the approval queue's *own* commands
# (commands/approvals.py: list/show/approve/reject) - these gate access to the
# whole queue, not any single approval-gated command, so they resolve against
# a fixed row rather than their own module:function name. requires_approval's
# per-command requester checks still resolve against the actual gated
# function's own name (see `wrapper` below).
GLOBAL_APPROVAL_FUNCTION = 'backend.approval:_global'


# Registry of approval-gated click commands, keyed by command name. Populated by the
# requires_approval decorator at import time so requests can be re-invoked by name.
APPROVAL_COMMANDS: dict = {}

_schema_ready = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id                   SERIAL PRIMARY KEY,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_by_user_id TEXT,
    requested_by_name    TEXT,
    team_id              TEXT,
    team_name            TEXT,
    channel_id           TEXT,
    command              TEXT NOT NULL,
    params               JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary              TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    decided_by_user_id   TEXT,
    decided_by_name      TEXT,
    decided_at           TIMESTAMPTZ,
    result               TEXT
);
"""


def _connect():
    global _schema_ready
    conn = psycopg.connect(os.environ['APPROVAL_DATABASE_URL'], row_factory=dict_row)
    if not _schema_ready:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
        conn.commit()
        _schema_ready = True
    return conn


def enqueue(*, command: str, params: dict, summary: str,
            requested_by_user_id: str, requested_by_name: str,
            team_id: str, team_name: str, channel_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO approval_requests
                    (command, params, summary, requested_by_user_id, requested_by_name,
                     team_id, team_name, channel_id)
                VALUES (%(command)s, %(params)s, %(summary)s, %(user_id)s, %(name)s,
                        %(team_id)s, %(team_name)s, %(channel_id)s)
                RETURNING id;
                """,
                {'command': command, 'params': Jsonb(params), 'summary': summary,
                 'user_id': requested_by_user_id, 'name': requested_by_name,
                 'team_id': team_id, 'team_name': team_name, 'channel_id': channel_id})
            request_id = cur.fetchone()['id']
        conn.commit()
    return request_id


def get(request_id: int) -> Optional[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM approval_requests WHERE id = %s;", (request_id,))
            return cur.fetchone()


def list_pending() -> List[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY id;")
            return cur.fetchall()


def set_decision(request_id: int, status: str, decided_by_user_id: str,
                 decided_by_name: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_requests
                SET status = %(status)s,
                    decided_by_user_id = %(user_id)s,
                    decided_by_name = %(name)s,
                    decided_at = NOW()
                WHERE id = %(id)s;
                """,
                {'status': status, 'user_id': decided_by_user_id,
                 'name': decided_by_name, 'id': request_id})
        conn.commit()


def set_result(request_id: int, status: str, result: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE approval_requests SET status = %s, result = %s WHERE id = %s;",
                (status, result, request_id))
        conn.commit()


def _allow_self_approval() -> bool:
    rule = permissions.get_rule(GLOBAL_APPROVAL_FUNCTION, permissions.GLOBAL_ENVIRONMENT, ROLE_APPROVE)
    return bool(((rule or {}).get('extra') or {}).get('meta', {}).get('allow_self', False))


def _notify_channel() -> Optional[str]:
    rule = permissions.get_rule(GLOBAL_APPROVAL_FUNCTION, permissions.GLOBAL_ENVIRONMENT, ROLE_APPROVE)
    return ((rule or {}).get('extra') or {}).get('notify_channel') or None


def security_check(ctx: ExtendedContext, role: str, function_name: str, action_name: str) -> bool:
    """Validate the calling user and channel for ``role`` against the
    ``permission_rules`` table (see ``backend.permissions``).

    Resembles :func:`backend.configuration.check_security`: checks the user with
    :func:`user_allowed` and verifies the channel is permitted (``*`` allows any).
    ``role`` selects requester vs. approver rules for ``function_name``. Denies by
    default (fails closed) when no rule is configured. On success, records the
    matched role on ``ctx.obj['security_role']`` (see ``ExtendedContext.security_role``).
    """
    rule = permissions.get_rule(function_name, permissions.GLOBAL_ENVIRONMENT, role)
    if rule is None:
        ctx.logger.warning(
            f"No permission_rules row for {function_name!r} "
            f"environment={permissions.GLOBAL_ENVIRONMENT!r} role={role!r} - denying by default.")
        ctx.chat.send_text(
            f"No permission rule configured for `{function_name}` (role `{role}`); "
            f"denying by default. Ask an administrator to add one.", is_error=True)
        return False
    action_proper = action_name.capitalize()
    if not user_allowed(ctx.chat.team_name, ctx.chat.user_id, rule['users']):
        ctx.chat.send_text(f"You don't have permission to {action_name}.", is_error=True)
        return False
    allowed_channels = rule['channels']
    channel_name = ctx.chat.channel_name
    if '*' not in allowed_channels and channel_name not in allowed_channels:
        ctx.chat.send_text(f"{action_proper} commands are not allowed in {channel_name}", is_error=True)
        return False
    ctx.obj['security_role'] = role
    return True


def check_approval_security(func: Callable = None, *, role: str = None):
    """``check_security``-style decorator for approval-queue-management commands
    (``commands/approvals.py``: list/show/approve/reject).

    Reads the human-readable action label from ``ctx.obj['security_text'][command]``
    and gates execution on :func:`security_check` against ``GLOBAL_APPROVAL_FUNCTION``
    for the given ``role`` (these commands operate the shared queue as a whole, not
    any single approval-gated command). Place it *below* ``@click.pass_context``.
    """
    if func is None:
        return functools.partial(check_approval_security, role=role)

    @functools.wraps(func)
    def wrapper(ctx: ExtendedContext, *args, **kwargs):
        action_name = ctx.obj['security_text'][ctx.command.name]
        if not security_check(ctx, role, GLOBAL_APPROVAL_FUNCTION, action_name):
            return
        return ctx.invoke(func, ctx, *args, **kwargs)

    return wrapper


def _requester_name(ctx) -> str:
    try:
        return ctx.chat.get_user_info(ctx.chat.user_id).get('real_name', ctx.chat.user_id)
    except Exception:
        return ctx.chat.user_id


def requires_approval(func: Callable = None, *, summarize: Callable = None,
                      validate: Callable = None):
    """Decorator gating a click command behind the approval queue.

    Place *below* ``@click.pass_context`` so the wrapped callback receives ``ctx``.
    When invoked by a requester the command body is skipped and a pending request is
    enqueued; when re-invoked by an approver (``ctx.obj['_approved_execution']``) the
    real body runs.

    The command's click parameters must be JSON-serializable. Pass ``summarize`` to
    build a human-readable one-line summary from the params dict, and ``validate`` to
    reject bad requests before they are queued (return an error string to abort).
    """
    if func is None:
        return functools.partial(requires_approval, summarize=summarize, validate=validate)

    @functools.wraps(func)
    def wrapper(ctx: ExtendedContext, *args, **kwargs):
        if ctx.obj.get('_approved_execution'):
            return ctx.invoke(func, ctx, *args, **kwargs)

        command_name = permissions.function_full_name(func)
        if not security_check(ctx, ROLE_REQUEST, command_name, f"request {command_name}"):
            return

        params = dict(ctx.params)

        if validate is not None and (error := validate(params)):
            ctx.chat.send_text(error, is_error=True)
            return

        summary = summarize(params) if summarize else _default_summary(command_name, params)
        request_id = enqueue(
            command=command_name, params=params, summary=summary,
            requested_by_user_id=ctx.chat.user_id, requested_by_name=_requester_name(ctx),
            team_id=ctx.chat.team_id, team_name=ctx.chat.team_name,
            channel_id=ctx.chat.channel_id)

        ctx.chat.send_text(
            f":hourglass_flowing_sand: Request *#{request_id}* queued for approval: {summary}")
        notify_channel = _notify_channel()
        if notify_channel:
            ctx.chat.send_text(
                f":inbox_tray: New approval request *#{request_id}*: {summary}\n"
                f"Use `{ctx.chat.bot_name} approvals approve {request_id}` to approve.",
                channel=notify_channel)
            #TODO: make this generic, maybe with another function argument
            send_email_log('onboarding', **params)
        return None

    APPROVAL_COMMANDS[permissions.function_full_name(func)] = wrapper
    wrapper._approval_callback = func
    return wrapper


def _default_summary(command_name: str, params: dict) -> str:
    parts = ' '.join(f"{k}={v}" for k, v in params.items())
    return f"{command_name} {parts}".strip()


def execute_approved(approver_ctx, row: dict) -> str:
    """Re-invoke a stored request's command body and return its result string."""
    command_name = row['command']
    cmd = _find_command(command_name)
    if cmd is None:
        raise click.ClickException(f"Unknown approval command {command_name!r}")

    obj = dict(approver_ctx.obj)
    obj['_approved_execution'] = True
    obj['_approval_request'] = row

    sub_ctx = click.Context(cmd, info_name=command_name, obj=obj)
    sub_ctx.params = dict(row['params'])
    return cmd.invoke(sub_ctx)


def _find_command(command_name: str):
    from commands import gyrobot
    cmd = gyrobot.commands.get(command_name)
    if cmd is not None:
        return cmd
    if command_name in APPROVAL_COMMANDS:
        # Fall back to a synthetic command wrapping the registered callback.
        return click.Command(command_name, callback=click.pass_context(
            APPROVAL_COMMANDS[command_name]._approval_callback))
    return None
