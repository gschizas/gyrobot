"""Account storage layer for PostgreSQL persistence.

Handles CRUD operations for accounts and their provisioning state across resources.
Uses APPROVAL_DATABASE_URL environment variable for database connection.
"""
import os
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from backend.accounts import Account, Provision
from backend.database import get_engine
from backend.models.accounts import AccountHistoryRow, AccountRow, ProvisionHistoryRow, ProvisionRow

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

# Provision statuses meaning the resource is held or an invitation is outstanding
LIVE_STATUSES = ('pending', 'invited', 'accepted', 'assigned', 'active')


def _session() -> Session:
    return Session(get_engine('APPROVAL_DATABASE_URL'))


def _to_account(row: AccountRow) -> Account:
    return Account(id=row.id, name=row.name, primary_email=row.primary_email, team=row.team,
                   created_at=row.created_at, updated_at=row.updated_at, metadata=row.metadata_ or {})


def _to_provision(row: ProvisionRow) -> Provision:
    return Provision(id=row.id, account_id=row.account_id, resource=row.resource, status=row.status,
                     data=row.data or {}, created_at=row.created_at, updated_at=row.updated_at)


def _record_account_history(session: Session, account: Account) -> None:
    session.add(AccountHistoryRow(account_id=account.id, name=account.name, primary_email=account.primary_email,
                                  team=account.team, metadata_=account.metadata))

def get_account(account_id: UUID) -> Optional[Account]:
    """Retrieve account by ID."""
    with _session() as session:
        row = session.get(AccountRow, account_id)
        return _to_account(row) if row else None


def get_account_by_email(email: str) -> Optional[Account]:
    """Retrieve account by primary email."""
    with _session() as session:
        row = session.scalars(select(AccountRow).where(AccountRow.primary_email == email)).first()
        return _to_account(row) if row else None


def create_account(name: Optional[str], primary_email: str, team: Optional[str] = None, **metadata) -> Account:
    """Create a new account. Returns the created Account."""
    account = Account(name=name, primary_email=primary_email, team=team, metadata=metadata)
    with _session() as session, session.begin():
        session.add(AccountRow(id=account.id, name=account.name, primary_email=account.primary_email,
                               team=account.team, created_at=account.created_at, updated_at=account.updated_at,
                               metadata_=account.metadata))
        session.flush()  # the history row has a foreign key to the account
        _record_account_history(session, account)
    return account


def get_or_create_account(primary_email: str, name: Optional[str] = None, team: Optional[str] = None,
                          **metadata) -> Account:
    """Get account by email, or create it if it doesn't exist.

    ``team`` is only recorded when the account has none yet; changing it is what ``onboard move`` is for.
    """
    existing = get_account_by_email(primary_email)
    if existing:
        if team and not existing.team:
            return update_account(existing.id, team=team) or existing
        return existing
    return create_account(name, primary_email, team=team, **metadata)


def update_account(account_id: UUID, **updates) -> Optional[Account]:
    """Update account name, team or metadata. Returns updated Account or None if not found."""
    with _session() as session, session.begin():
        row = session.get(AccountRow, account_id)
        if not row:
            return None
        if 'name' in updates:
            row.name = updates['name']
        if 'team' in updates:
            row.team = updates['team']
        if 'metadata' in updates:
            row.metadata_ = updates['metadata']
        row.updated_at = datetime.now(timezone.utc)
        account = _to_account(row)
        _record_account_history(session, account)
    return account


def set_provision_status(account_id: UUID, resource: str, status: str, data: dict,
                         created_at=None) -> Provision:
    """Create or update provision status for an account + resource combo.

    ``created_at`` backdates the provision (used when importing pre-existing users).
    """
    provision = Provision(
        account_id=account_id,
        resource=resource,
        status=status,
        data=data,
    )
    if created_at is not None:
        provision.created_at = created_at

    with _session() as session, session.begin():
        previous = session.scalar(select(ProvisionRow.status).where(
            ProvisionRow.account_id == account_id, ProvisionRow.resource == resource))
        session.add(ProvisionHistoryRow(account_id=account_id, resource=resource, previous_status=previous,
                                        status=status, data=data))
        stmt = insert(ProvisionRow).values(
            id=provision.id, account_id=account_id, resource=resource, status=status, data=data,
            created_at=provision.created_at, updated_at=provision.updated_at)
        session.execute(stmt.on_conflict_do_update(
            constraint='account_provisions_account_id_resource_key',
            set_={'status': status, 'data': stmt.excluded.data, 'created_at': provision.created_at,
                  'updated_at': datetime.now(timezone.utc)}))
    return provision


def get_provision(account_id: UUID, resource: str) -> Optional[Provision]:
    """Retrieve provision status for account + resource."""
    with _session() as session:
        row = session.scalars(select(ProvisionRow).where(
            ProvisionRow.account_id == account_id, ProvisionRow.resource == resource)).first()
        return _to_provision(row) if row else None


def get_provision_history(account_id: UUID, resource: Optional[str] = None) -> List[dict]:
    """Audit trail of provision status changes for an account, oldest first."""
    query = select(ProvisionHistoryRow).where(ProvisionHistoryRow.account_id == account_id)
    if resource:
        query = query.where(ProvisionHistoryRow.resource == resource)
    with _session() as session:
        return [{c.key: getattr(row, c.key) for c in ProvisionHistoryRow.__table__.columns}
                for row in session.scalars(query.order_by(ProvisionHistoryRow.recorded_at, ProvisionHistoryRow.id))]


def get_last_status_times(resource: str, status: str) -> dict[UUID, datetime]:
    """When each account's ``resource`` provision last entered ``status``, from the audit trail.

    Unlike the provision row's own timestamps, these come from the database clock and survive later rewrites.
    """
    with _session() as session:
        rows = session.execute(
            select(ProvisionHistoryRow.account_id, func.max(ProvisionHistoryRow.recorded_at))
            .where(ProvisionHistoryRow.resource == resource, ProvisionHistoryRow.status == status)
            .group_by(ProvisionHistoryRow.account_id))
        return {account_id: recorded_at for account_id, recorded_at in rows}


def _provisions(*conditions) -> List[Provision]:
    with _session() as session:
        return [_to_provision(row) for row in session.scalars(
            select(ProvisionRow).where(*conditions).order_by(ProvisionRow.created_at))]


def get_pending_provisions(resource: str, status: str) -> List[Provision]:
    """Get all provisions for a resource with a specific status."""
    return _provisions(ProvisionRow.resource == resource, ProvisionRow.status == status)


def find_provisions_by_username(resource: str, usernames: List[str],
                                statuses: tuple[str, ...] = LIVE_STATUSES) -> List[Provision]:
    """Provisions of a resource whose stored ``username`` matches any of the given names (case-insensitive).

    By default only provisions that still hold, or are about to hold, the resource are returned
    (not ``expired``, ``failed`` or ``deprovisioned`` ones).
    """
    if not usernames:
        return []
    return _provisions(ProvisionRow.resource == resource, ProvisionRow.status.in_(statuses),
                       func.lower(ProvisionRow.data['username'].astext).in_([u.lower() for u in usernames]))


def find_provisions_by_any_username(usernames: List[str]) -> List[Provision]:
    """Provisions of any resource whose stored ``username`` is one of the given names (exact match)."""
    if not usernames:
        return []
    return _provisions(ProvisionRow.data['username'].astext.in_(usernames))


def get_provisions(resource: str) -> List[Provision]:
    """All provisions of a resource, whatever their status."""
    return _provisions(ProvisionRow.resource == resource)


def find_provisions_by_github_id(github_id: int, statuses: tuple[str, ...] = LIVE_STATUSES) -> List[Provision]:
    """GitHub provisions stored with the given numeric GitHub user id (survives username changes)."""
    return _provisions(ProvisionRow.resource == 'github', ProvisionRow.status.in_(statuses),
                       ProvisionRow.data['github_id'].astext == str(github_id))


def merge_provision_data(account_id: UUID, resource: str, extra: dict) -> None:
    """Add/overwrite keys in a provision's data without touching its status or created_at."""
    with _session() as session, session.begin():
        session.execute(update(ProvisionRow)
                        .where(ProvisionRow.account_id == account_id, ProvisionRow.resource == resource)
                        .values(data=ProvisionRow.data.op('||')(type_coerce(extra, JSONB)), updated_at=func.now()))


def get_account_provisions(account_id: UUID) -> List[Provision]:
    """Get all provisions for an account (across all resources)."""
    with _session() as session:
        return [_to_provision(row) for row in session.scalars(
            select(ProvisionRow).where(ProvisionRow.account_id == account_id).order_by(ProvisionRow.resource))]


def get_active_provisions(account_id: UUID) -> List[Provision]:
    """Get all active (non-deprovisioned) provisions for an account."""
    with _session() as session:
        return [_to_provision(row) for row in session.scalars(
            select(ProvisionRow)
            .where(ProvisionRow.account_id == account_id,
                   ProvisionRow.status.not_in(('deprovisioned', 'cancelled', 'expired')))
            .order_by(ProvisionRow.resource))]
