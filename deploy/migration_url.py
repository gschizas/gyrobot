"""Print the database URL of an instance (from .env.d/<env-name>.env) for another user, without a password.

Usage (from the repository root): uv run python deploy/migration_url.py <env-name> <db-user>

Used by deploy/migrate.sh and deploy/windows/migrate.ps1; the password is passed through PGPASSWORD.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from sqlalchemy.engine import URL, make_url  # noqa: E402

from backend.secret_store import load_environment  # noqa: E402

DSN_VARIABLES = ('MIGRATIONS_DATABASE_URL', 'DATABASE_URL')


def main(env_name: str, db_user: str) -> None:
    load_environment(env_name)
    for name in DSN_VARIABLES:
        if dsn := os.environ.get(name):
            break
    else:
        raise SystemExit(f'No database URL in .env.d/{env_name}.env')
    url = make_url(dsn)
    url = URL.create('postgresql', username=db_user, host=url.host, port=url.port, database=url.database,
                     query=url.query)
    print(url.render_as_string(hide_password=False))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
