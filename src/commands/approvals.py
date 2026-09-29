"""Approval queue management commands.

The ``approvals`` group lets designated approvers review and act on requests queued
by approval-gated commands such as ``onboard`` and ``offboard``. Approving a request
executes the original command body. Approver permissions, the channels the group may
be used in, and the self-approval policy all come from the ``permission_rules`` table
(see ``backend.permissions`` / ``scripts/migrate_permissions.py``), resolved against
the ``backend.approval.GLOBAL_APPROVAL_FUNCTION`` sentinel row rather than any single
approval-gated command's own name, since these commands operate the whole shared
queue (see ``backend.approval`` / ``check_approval_security``).
"""
import os
import traceback
from typing import List, Optional

import click

from backend.approval import (ROLE_APPROVE, check_approval_security, execute_approved,
                              get, list_pending, set_decision, set_result,
                              _allow_self_approval, _notify_channel)
from backend.email_logging import send_email_log
from commands import gyrobot, ClickAliasedGroup
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

# Human-readable action labels per subcommand, consumed by check_approval_security
# (mirrors the ctx.obj['security_text'] convention used by check_security).
_SECURITY_TEXT = {
    'list': 'list approvals',
    'show': 'view an approval request',
    'approve': 'approve requests',
    'reject': 'reject requests',
}


def _parse_id_spec(spec: str) -> List[int]:
    """Parse a single id-spec token such as ``90``, ``92-95``, or a whole
    comma-separated combination such as ``90,92-95,99-100`` into a list of ints.
    Raises ``ValueError`` on anything that isn't a plain integer or an
    ascending ``start-end`` range."""
    ids = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            start_text, _, end_text = part.partition('-')
            start, end = int(start_text), int(end_text)
            if end < start:
                raise ValueError(f"Invalid range {part!r}: end must not be before start.")
            ids.extend(range(start, end + 1))
        else:
            ids.append(int(part))
    return ids


def _resolve_ids(ids: tuple) -> Optional[List[int]]:
    if len(ids) == 1 and ids[0].lower() == 'all':
        return [row['id'] for row in list_pending()]
    try:
        # Each token may itself be a comma-separated list of ids/ranges (e.g. "90,92-95,99-100"),
        # and multiple such tokens may be passed as separate arguments (they're combined here).
        resolved = []
        for token in ids:
            resolved.extend(_parse_id_spec(token))
        # De-duplicate while preserving the requested order.
        seen = set()
        deduped = []
        for one_id in resolved:
            if one_id not in seen:
                seen.add(one_id)
                deduped.append(one_id)
        return deduped
    except ValueError:
        return None


@gyrobot.group('approvals', cls=ClickAliasedGroup, aliases=['approval'])
@click.pass_context
def approvals(ctx: ExtendedContext):
    """Review and act on queued command-approval requests"""
    ctx.ensure_object(dict)
    ctx.obj['security_text'] = _SECURITY_TEXT


@approvals.command('list')
@click.pass_context
@check_approval_security(role=ROLE_APPROVE)
def list_approvals(ctx: ExtendedContext):
    """List pending approval requests"""
    pending = list_pending()
    if not pending:
        ctx.chat.send_text("No pending approval requests.")
        return
    table = [{
        'ID': row['id'],
        'When': row['created_at'].strftime('%Y-%m-%d %H:%M'),
        'Requested by': row['requested_by_name'],
        'Command': row['command'],
        'Summary': row['summary'],
    } for row in pending]
    ctx.chat.send_table(title='Pending approvals', table=table)


@approvals.command('show')
@click.argument('request_id', type=int)
@click.pass_context
@check_approval_security(role=ROLE_APPROVE)
def show_approval(ctx: ExtendedContext, request_id: int):
    """Show full detail of a single approval request"""
    row = get(request_id)
    if row is None:
        ctx.chat.send_text(f"Request #{request_id} not found.", is_error=True)
        return
    params = ', '.join(f"{k}={v}" for k, v in row['params'].items())
    lines = [
        f"*Request #{row['id']}* — `{row['status']}`",
        f"Command: `{row['command']}`",
        f"Summary: {row['summary']}",
        f"Parameters: {params}",
        f"Requested by: {row['requested_by_name']} at {row['created_at']:%Y-%m-%d %H:%M}",
    ]
    if row['decided_at']:
        lines.append(f"Decided by: {row['decided_by_name']} at {row['decided_at']:%Y-%m-%d %H:%M}")
    if row['result']:
        lines.append(f"Result:\n```\n{row['result']}\n```")
    ctx.chat.send_text('\n'.join(lines))


@approvals.command('approve')
@click.argument('ids', nargs=-1, required=True)
@click.pass_context
@check_approval_security(role=ROLE_APPROVE)
def approve(ctx: ExtendedContext, ids: tuple):
    """Approve and execute one or more requests.

    IDS accepts numeric ids, ranges (``92-95``), and comma-separated
    combinations of both (e.g. ``90,92-95,99-100``); use `all` for every
    pending request.
    """
    request_ids = _resolve_ids(ids)
    if request_ids is None:
        ctx.chat.send_text(
            "Invalid request id(s). Use numeric ids, ranges (e.g. `92-95`), a "
            "comma-separated combination (e.g. `90,92-95,99-100`), or `all`.", is_error=True)
        return
    if not request_ids:
        ctx.chat.send_text("No pending requests to approve.")
        return
    for request_id in request_ids:
        _approve_one(ctx, request_id)


def _approve_one(ctx: ExtendedContext, request_id: int) -> None:
    row = get(request_id)
    if row is None:
        ctx.chat.send_text(f"Request #{request_id} not found.", is_error=True)
        return
    if row['status'] != 'pending':
        ctx.chat.send_text(f"Request #{request_id} is already `{row['status']}`.", is_error=True)
        return
    if row['requested_by_user_id'] == ctx.chat.user_id and not _allow_self_approval():
        ctx.chat.send_text(f"You can't approve your own request #{request_id}.", is_error=True)
        return

    set_decision(request_id, 'approved', ctx.chat.user_id, _approver_name(ctx))
    try:
        result = execute_approved(ctx, row) or 'Done.'
        set_result(request_id, 'executed', str(result))
        ctx.chat.send_text(f":white_check_mark: Request *#{request_id}* approved and executed.")
        _notify_requester(ctx, row, f":white_check_mark: Your request *#{request_id}* "
                                    f"({row['summary']}) was approved and executed.")
        _notify_approvals_channel(ctx, f":white_check_mark: Request *#{request_id}* "
                                       f"({row['summary']}) approved by {_approver_name(ctx)}.")
        row = get(request_id)
        send_email_log('approval', status='approved', request_id=request_id, row=row)
    except Exception as ex:
        error_text = ''.join(traceback.format_exception(type(ex), ex, ex.__traceback__))
        set_result(request_id, 'failed', error_text)
        ctx.logger.error(f"Approval execution failed for #{request_id}: {ex!r}")
        ctx.chat.send_text(f":x: Request *#{request_id}* approved but execution failed:\n"
                           f"```\n{ex!r}\n```", is_error=True)


@approvals.command('reject')
@click.argument('ids', nargs=-1, required=True)
@click.option('-r', '--reason', default='', help='Reason for rejection')
@click.pass_context
@check_approval_security(role=ROLE_APPROVE)
def reject(ctx: ExtendedContext, ids: tuple, reason: str):
    """Reject one or more pending requests.

    IDS accepts numeric ids, ranges (``92-95``), and comma-separated
    combinations of both (e.g. ``90,92-95,99-100``); use `all` for every
    pending request.
    """
    request_ids = _resolve_ids(ids)
    if request_ids is None:
        ctx.chat.send_text(
            "Invalid request id(s). Use numeric ids, ranges (e.g. `92-95`), a "
            "comma-separated combination (e.g. `90,92-95,99-100`), or `all`.", is_error=True)
        return
    if not request_ids:
        ctx.chat.send_text("No pending requests to reject.")
        return
    for request_id in request_ids:
        row = get(request_id)
        if row is None:
            ctx.chat.send_text(f"Request #{request_id} not found.", is_error=True)
            continue
        if row['status'] != 'pending':
            ctx.chat.send_text(f"Request #{request_id} is already `{row['status']}`.", is_error=True)
            continue
        set_decision(request_id, 'rejected', ctx.chat.user_id, _approver_name(ctx))
        if reason:
            set_result(request_id, 'rejected', f"Rejected: {reason}")
        ctx.chat.send_text(f":no_entry: Request *#{request_id}* rejected.")
        row = get(request_id)
        send_email_log('approval', status='rejected', request_id=request_id, row=row)
        suffix = f"\nReason: {reason}" if reason else ''
        _notify_requester(ctx, row, f":no_entry: Your request *#{request_id}* "
                                    f"({row['summary']}) was rejected.{suffix}")
        _notify_approvals_channel(ctx, f":no_entry: Request *#{request_id}* "
                                       f"({row['summary']}) rejected by {_approver_name(ctx)}.{suffix}")


def _approver_name(ctx: ExtendedContext) -> str:
    try:
        return ctx.chat.get_user_info(ctx.chat.user_id).get('real_name', ctx.chat.user_id)
    except Exception:
        return ctx.chat.user_id


def _notify_requester(ctx: ExtendedContext, row: dict, text: str) -> None:
    """Notify the user who made the approval request.

    If the request came from a non-chat interface (``$webui`` or ``$api``), this
    sends to the approval notifications channel instead of trying to message the
    fake pseudo-channel.
    """
    channel = row.get('channel_id')
    if channel and channel.startswith('$'):
        channel = _notify_channel()
    if channel and channel != ctx.chat.channel_id:
        ctx.chat.send_text(text, channel=channel)


def _notify_approvals_channel(ctx: ExtendedContext, text: str) -> None:
    """Send a notification to the configured approval notifications channel.

    This ensures that the approvals team is always notified of approvals/rejections,
    regardless of where the original request came from.
    """
    channel = _notify_channel()
    if channel and channel != ctx.chat.channel_id:
        ctx.chat.send_text(text, channel=channel)
