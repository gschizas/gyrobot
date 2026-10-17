"""kudos table

Idempotent baseline: the table already exists in production, so this only creates it on a fresh database.
Kudos first appeared in the project on 2019-05-16 (commit 4e79115), which is the date used below.

Revision ID: 0001
Revises:
Create Date: 2019-05-16 00:04:31
"""
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS kudos (
            id SERIAL NOT NULL,
            datestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            from_user VARCHAR(21),
            to_user VARCHAR(21),
            from_user_id VARCHAR(12) NOT NULL,
            to_user_id VARCHAR(12) NOT NULL,
            team_id VARCHAR(64) NOT NULL DEFAULT '',
            team_name VARCHAR(64) NOT NULL DEFAULT '',
            permalink VARCHAR(128) NOT NULL DEFAULT '',
            channel_id VARCHAR(12) NOT NULL DEFAULT '',
            channel_name VARCHAR(128) NOT NULL,
            reason TEXT,
            CONSTRAINT kudos_pk PRIMARY KEY (id)
        )
    """)


def downgrade() -> None:
    raise NotImplementedError('Refusing to drop the kudos table; do it by hand if you really mean it')
