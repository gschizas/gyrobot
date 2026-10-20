"""permission_rules_history table (audit trail of permission rule edits)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 10:30:00
"""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS permission_rules_history (
            id            SERIAL NOT NULL,
            function_name TEXT NOT NULL,
            environment   TEXT NOT NULL,
            role          TEXT NOT NULL,
            action        TEXT NOT NULL,
            changed_by    TEXT NOT NULL,
            changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            before        JSONB,
            after         JSONB,
            CONSTRAINT permission_rules_history_pkey PRIMARY KEY (id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS permission_rules_history")
