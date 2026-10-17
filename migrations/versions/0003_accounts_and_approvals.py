"""accounts, provisions, their history tables and the approval queue

Idempotent: most of these tables already exist (they used to be created by the application). ``accounts.team`` and
``account_history`` are the newer additions, so they are added only when missing. ``ADD COLUMN IF NOT EXISTS`` needs
PostgreSQL 9.6, hence the inspector check.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 11:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id UUID NOT NULL,
            name TEXT,
            primary_email TEXT NOT NULL,
            team TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT accounts_pkey PRIMARY KEY (id),
            CONSTRAINT accounts_primary_email_key UNIQUE (primary_email)
        )
    """)
    if not op.get_context().as_sql:
        columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('accounts')}
        if 'team' not in columns:
            op.add_column('accounts', sa.Column('team', sa.Text()))
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_provisions (
            id UUID NOT NULL,
            account_id UUID NOT NULL,
            resource TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT account_provisions_pkey PRIMARY KEY (id),
            CONSTRAINT account_provisions_account_id_resource_key UNIQUE (account_id, resource),
            CONSTRAINT account_provisions_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_account_provisions_resource_status ON account_provisions (resource, status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_provision_history (
            id BIGSERIAL NOT NULL,
            account_id UUID NOT NULL,
            resource TEXT NOT NULL,
            previous_status TEXT,
            status TEXT NOT NULL,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT account_provision_history_pkey PRIMARY KEY (id),
            CONSTRAINT account_provision_history_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_account_provision_history_account "
               "ON account_provision_history (account_id, resource, recorded_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS account_history (
            id BIGSERIAL NOT NULL,
            account_id UUID NOT NULL,
            name TEXT,
            primary_email TEXT,
            team TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT account_history_pkey PRIMARY KEY (id),
            CONSTRAINT account_history_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_account_history_account ON account_history (account_id, recorded_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            id SERIAL NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            requested_by_user_id TEXT,
            requested_by_name TEXT,
            team_id TEXT,
            team_name TEXT,
            channel_id TEXT,
            command TEXT NOT NULL,
            params JSONB NOT NULL DEFAULT '{}'::jsonb,
            summary TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            decided_by_user_id TEXT,
            decided_by_name TEXT,
            decided_at TIMESTAMPTZ,
            result TEXT,
            CONSTRAINT approval_requests_pkey PRIMARY KEY (id)
        )
    """)


def downgrade() -> None:
    raise NotImplementedError('Refusing to drop the onboarding and approval tables; do it by hand if you really mean it')
