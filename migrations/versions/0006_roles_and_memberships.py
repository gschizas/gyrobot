"""roles and team_memberships tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23 14:00:00

Roles live in the database (seeded from the former ``Role`` enum). A membership is one person in one team with an
optional role; accounts.team stays as the person's main team.
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

SEED = [
    ('facilitator', 'Facilitator'),
    ('scrum_master', 'Scrum Master'),
    ('frontend_developer', 'Frontend Developer'),
    ('backend_developer', 'Backend Developer'),
    ('full_stack_developer', 'Full Stack Developer'),
    ('ios_developer', 'iOS Developer'),
    ('android_developer', 'Android Developer'),
    ('product_owner', 'Product Owner'),
    ('business_analyst', 'Business Analyst'),
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            key           TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            is_team_admin BOOLEAN NOT NULL DEFAULT false,
            active        BOOLEAN NOT NULL DEFAULT true,
            team_prefix   TEXT,
            CONSTRAINT roles_pkey PRIMARY KEY (key)
        )
    """)
    for key, display_name in SEED:
        op.execute(f"INSERT INTO roles (key, display_name) VALUES ('{key}', '{display_name}') "
                   "ON CONFLICT (key) DO NOTHING")
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_memberships (
            account_id    UUID NOT NULL,
            team          TEXT NOT NULL,
            role_key      TEXT,
            is_team_admin BOOLEAN NOT NULL DEFAULT false,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT team_memberships_pkey PRIMARY KEY (account_id, team),
            CONSTRAINT team_memberships_account_id_fkey
                FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE,
            CONSTRAINT team_memberships_role_key_fkey FOREIGN KEY (role_key) REFERENCES roles (key)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_team_memberships_team ON team_memberships (team)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_memberships")
    op.execute("DROP TABLE IF EXISTS roles")
