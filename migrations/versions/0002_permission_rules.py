"""permission_rules table

Idempotent: the table already exists wherever scripts/migrate_permissions.py was run.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 10:45:00
"""
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS permission_rules (
            id            SERIAL NOT NULL,
            function_name TEXT NOT NULL,
            environment   TEXT NOT NULL DEFAULT '',
            role          TEXT NOT NULL DEFAULT 'default',
            users         JSONB NOT NULL DEFAULT '[]'::jsonb,
            channels      JSONB NOT NULL DEFAULT '[]'::jsonb,
            extra         JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT permission_rules_pkey PRIMARY KEY (id),
            CONSTRAINT permission_rules_function_name_environment_role_key UNIQUE (function_name, environment, role)
        )
    """)


def downgrade() -> None:
    raise NotImplementedError('Refusing to drop the permission_rules table; do it by hand if you really mean it')
