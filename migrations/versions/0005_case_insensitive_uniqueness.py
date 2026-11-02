"""Case-insensitive uniqueness of account emails and GitHub usernames

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02 15:30:00

Two accounts whose emails differ only in case (or two GitHub provisions with the same login in different case)
are the same person. Stops the duplicates at the database; fails with the list of offenders if some already exist.
"""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

EMAIL_INDEX = 'accounts_primary_email_lower_key'
USERNAME_INDEX = 'account_provisions_github_username_lower_key'

DUPLICATE_EMAILS = """
    SELECT lower(primary_email), count(*) FROM accounts GROUP BY 1 HAVING count(*) > 1
"""
DUPLICATE_USERNAMES = """
    SELECT lower(data->>'username'), count(*) FROM account_provisions
    WHERE resource = 'github' GROUP BY 1 HAVING count(*) > 1
"""


def _fail_on_duplicates(label: str, query: str) -> None:
    rows = op.get_bind().exec_driver_sql(query).fetchall()
    if rows:
        listing = ', '.join(f"{value!r} ({count}x)" for value, count in rows)
        raise RuntimeError(f"Merge or remove the duplicate {label} first (they differ only in case): {listing}")


def upgrade() -> None:
    _fail_on_duplicates('account emails', DUPLICATE_EMAILS)
    _fail_on_duplicates('GitHub usernames', DUPLICATE_USERNAMES)
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {EMAIL_INDEX} ON accounts (lower(primary_email))")
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {USERNAME_INDEX} "
               f"ON account_provisions (lower(data->>'username')) WHERE resource = 'github'")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {USERNAME_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {EMAIL_INDEX}")
