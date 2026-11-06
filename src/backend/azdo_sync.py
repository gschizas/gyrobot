"""Matches Azure DevOps users to accounts (and so to canonical teams) and keeps a snapshot of their access level.

The snapshot is an ``azdo`` provision per account: ``active`` while the person is in Azure DevOps, ``deprovisioned``
once they are gone. Its history therefore shows when somebody's access level changed.
"""
import datetime

from backend.account_storage import LIVE_STATUSES, get_all_accounts, get_provisions, set_provision_status
from backend.accounts import Account
from backend.azdo_api import AzdoApi

UNKNOWN_TEAM = 'unknown'  # no account has the user's email
NO_TEAM = '(no team)'  # the account has no canonical team

# Fields that make up the snapshot; changes in any of them (but not in last_accessed) are recorded
_TRACKED = ('azdo_id', 'email', 'username', 'access_level', 'license_type', 'licensing_source', 'assignment_source',
            'azdo_status')


def email_index(accounts: list[Account]) -> dict[str, Account]:
    """Lowercase email (primary or additional) -> account; the oldest account wins a clash."""
    index: dict[str, Account] = {}
    for account in accounts:
        for email in (account.primary_email, *account.metadata.get('additional_emails', [])):
            if email:
                index.setdefault(email.lower(), account)
    return index


def member_account(member: dict, index: dict[str, Account]) -> Account | None:
    return index.get(member['email']) or index.get(member['principal_name'])


def _snapshot(member: dict) -> dict:
    return {'azdo_id': member['id'], 'email': member['email'], 'username': member['principal_name'],
            'name': member['name'], 'access_level': member['access_level'], 'license_type': member['license_type'],
            'licensing_source': member['licensing_source'], 'assignment_source': member['assignment_source'],
            'azdo_status': member['status'], 'last_accessed': member['last_accessed']}


def sync_members(max_age: float = 300) -> list[dict]:
    """Read Azure DevOps and record the snapshots; returns the members, each with ``account`` and ``team`` added.

    Only changes are written. Accounts whose snapshot is live but who are no longer in Azure DevOps are marked
    ``deprovisioned``.
    """
    members = AzdoApi().get_members(max_age)
    index = email_index(get_all_accounts())
    stored = {p.account_id: p for p in get_provisions('azdo')}
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    seen: set = set()
    for member in members:
        account = member_account(member, index)
        member['account'] = account
        member['team'] = UNKNOWN_TEAM if account is None else (account.team or NO_TEAM)
        if account is None or account.id in seen:  # a second Azure DevOps user of the same person is not stored
            continue
        seen.add(account.id)
        data = _snapshot(member)
        previous = stored.get(account.id)
        if previous and previous.status == 'active' and all(previous.data.get(k) == data[k] for k in _TRACKED):
            continue
        set_provision_status(account.id, 'azdo', 'active', {**data, 'synced_at': now})

    if members:  # an empty answer is more likely a problem than everybody leaving
        for account_id, provision in stored.items():
            if account_id not in seen and provision.status in LIVE_STATUSES:
                set_provision_status(account_id, 'azdo', 'deprovisioned', {**provision.data, 'removed_at': now})
    return members
