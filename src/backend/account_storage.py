"""Account storage layer for PostgreSQL persistence.

Handles CRUD operations for accounts and their provisioning state across resources.
Uses APPROVAL_DATABASE_URL environment variable for database connection.
"""
import os
from typing import List, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.accounts import Account, Provision

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


_schema_ready = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY,
    name TEXT,
    primary_email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS account_provisions (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, resource)
);

CREATE INDEX IF NOT EXISTS idx_account_provisions_resource_status 
    ON account_provisions(resource, status);
"""


def _connect() -> psycopg.Connection:
    """Establish database connection and initialize schema if needed."""
    global _schema_ready
    conn = psycopg.connect(os.environ['APPROVAL_DATABASE_URL'], row_factory=dict_row)
    _schema_ready = True
    return conn
    #if not _schema_ready:
    #    with conn.cursor() as cur:
    #        cur.execute(_SCHEMA)
    #    conn.commit()
    #    _schema_ready = True
    #return conn


def get_account(account_id: UUID) -> Optional[Account]:
    """Retrieve account by ID."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s;", (str(account_id),))
            row = cur.fetchone()
    if not row:
        return None
    return Account.from_dict(row)


def get_account_by_email(email: str) -> Optional[Account]:
    """Retrieve account by primary email."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE primary_email = %s;", (email,))
            row = cur.fetchone()
    if not row:
        return None
    return Account.from_dict(row)


def create_account(name: Optional[str], primary_email: str, **metadata) -> Account:
    """Create a new account. Returns the created Account."""
    account = Account(name=name, primary_email=primary_email, metadata=metadata)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO accounts (id, name, primary_email, created_at, updated_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    str(account.id),
                    account.name,
                    account.primary_email,
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                    Jsonb(account.metadata),
                ),
            )
        conn.commit()
    return account


def get_or_create_account(primary_email: str, name: Optional[str] = None, **metadata) -> Account:
    """Get account by email, or create it if it doesn't exist."""
    existing = get_account_by_email(primary_email)
    if existing:
        return existing
    return create_account(name, primary_email, **metadata)


def update_account(account_id: UUID, **updates) -> Optional[Account]:
    """Update account metadata. Returns updated Account or None if not found."""
    from datetime import datetime
    
    account = get_account(account_id)
    if not account:
        return None
    
    # Update allowed fields
    if 'name' in updates:
        account.name = updates['name']
    if 'metadata' in updates:
        account.metadata = updates['metadata']
    
    account.updated_at = datetime.utcnow()
    
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE accounts 
                SET name = %s, metadata = %s, updated_at = %s
                WHERE id = %s;
                """,
                (
                    account.name,
                    Jsonb(account.metadata),
                    account.updated_at.isoformat(),
                    str(account_id),
                ),
            )
        conn.commit()
    return account


def set_provision_status(account_id: UUID, resource: str, status: str, data: dict) -> Provision:
    """Create or update provision status for an account + resource combo."""
    from datetime import datetime
    
    provision = Provision(
        account_id=account_id,
        resource=resource,
        status=status,
        data=data,
    )
    
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO account_provisions (id, account_id, resource, status, data, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id, resource) 
                DO UPDATE SET status = %s, data = %s, updated_at = %s;
                """,
                (
                    str(provision.id),
                    str(account_id),
                    resource,
                    status,
                    Jsonb(data),
                    provision.created_at.isoformat(),
                    provision.updated_at.isoformat(),
                    status,
                    Jsonb(data),
                    datetime.utcnow().isoformat(),
                ),
            )
        conn.commit()
    return provision


def get_provision(account_id: UUID, resource: str) -> Optional[Provision]:
    """Retrieve provision status for account + resource."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM account_provisions 
                WHERE account_id = %s AND resource = %s;
                """,
                (str(account_id), resource),
            )
            row = cur.fetchone()
    if not row:
        return None
    return Provision.from_dict(row)


def get_pending_provisions(resource: str, status: str) -> List[Provision]:
    """Get all provisions for a resource with a specific status."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM account_provisions 
                WHERE resource = %s AND status = %s
                ORDER BY created_at;
                """,
                (resource, status),
            )
            rows = cur.fetchall()
    return [Provision.from_dict(row) for row in rows]


def get_account_provisions(account_id: UUID) -> List[Provision]:
    """Get all provisions for an account (across all resources)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM account_provisions 
                WHERE account_id = %s
                ORDER BY resource;
                """,
                (str(account_id),),
            )
            rows = cur.fetchall()
    return [Provision.from_dict(row) for row in rows]


def get_active_provisions(account_id: UUID) -> List[Provision]:
    """Get all active (non-deprovisioned) provisions for an account."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM account_provisions 
                WHERE account_id = %s AND status != 'deprovisioned'
                ORDER BY resource;
                """,
                (str(account_id),),
            )
            rows = cur.fetchall()
    return [Provision.from_dict(row) for row in rows]
