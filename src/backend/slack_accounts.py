"""Linking Slack member ids to Gyrobot accounts (the ``slack`` provision).

A person can have several Slack accounts (corporate and outsourcer emails). The ids are kept in the account's
``slack`` provision (``data['member_ids']``) and each account's sign-in email in ``data['emails']`` and in the
account's ``additional_emails``, so offboarding finds every Slack account.
"""
import logging
import re

from backend.account_storage import (
    add_additional_email, find_account_by_any_email, get_or_create_account, get_provision, set_provision_status
)
from backend.slack_directory import MEMBER_ID, SlackDirectory

logger = logging.getLogger(__name__)

_MENTION = re.compile(r'<@(?P<id>[A-Z0-9]+)(?:\|[^>]*)?>')


def parse_member_id(text: str) -> str | None:
    """The Slack member id in ``text`` (``<@U123|name>``, ``@U123`` or ``U123``), or None."""
    text = text.strip()
    if match := _MENTION.fullmatch(text):
        text = match.group('id')
    text = text.lstrip('@').upper()
    return text if MEMBER_ID.fullmatch(text) else None


def _data(account) -> dict:
    provision = get_provision(account.id, 'slack')
    data = dict(provision.data) if provision else {}
    return {'member_ids': list(data.get('member_ids', [])), 'emails': list(data.get('emails', []))}


def link(email: str, member_ids: list[str], directory: SlackDirectory | None = None,
         *, name: str | None = None) -> dict:
    """Add ``member_ids`` to the Slack provision of the account with ``email``.

    Each id is looked up in Slack; its sign-in email is recorded as another address of the account.
    A lookup failure (no token, unknown id) only skips the email part. Returns
    ``{'added': [...], 'emails': [...], 'unresolved': [...]}``.
    """
    account = get_or_create_account(primary_email=email, name=name or email)
    data = _data(account)
    directory = directory or SlackDirectory()
    added, found, unresolved = [], [], []
    for member_id in member_ids:
        if member_id not in data['member_ids']:
            data['member_ids'].append(member_id)
            added.append(member_id)
        try:
            user = directory.get_user(member_id)
        except Exception as e:
            logger.warning(f"Slack lookup of {member_id} failed: {e}")
            user = None
        if user is None or not user.email:
            unresolved.append(member_id)
            continue
        if user.email not in data['emails']:
            data['emails'].append(user.email)
        found.append(user.email)
        if user.email != account.primary_email.lower():
            add_additional_email(account.id, user.email)
    data['email'] = account.primary_email
    set_provision_status(account.id, 'slack', 'active', data)
    return {'added': added, 'emails': found, 'unresolved': unresolved}


def unlink(email: str, member_ids: list[str]) -> list[str] | None:
    """Remove ``member_ids`` from the account's Slack provision. Returns the ids removed, None if no provision."""
    account = find_account_by_any_email(email)
    provision = get_provision(account.id, 'slack') if account else None
    if provision is None:
        return None
    data = _data(account)
    removed = [m for m in member_ids if m in data['member_ids']]
    data['member_ids'] = [m for m in data['member_ids'] if m not in removed]
    data['email'] = account.primary_email
    set_provision_status(account.id, 'slack', 'active' if data['member_ids'] else 'removed', data)
    return removed
