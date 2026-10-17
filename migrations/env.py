"""Alembic environment.

Usage (from the repo root)::

    uv run alembic -x env=<env-name> upgrade head

``env`` selects ``.env.d/<env-name>.env`` (loaded like the bot does). The database is taken from
``MIGRATIONS_DATABASE_URL``, otherwise from the first set of the variables in ``_DSN_VARIABLES``.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

import backend.models  # noqa: F401  (registers the tables on Base.metadata)
from backend.database import Base
from backend.secret_store import load_environment

_DSN_VARIABLES = ('MIGRATIONS_DATABASE_URL', 'APPROVAL_DATABASE_URL', 'PERMISSIONS_DATABASE_URL', 'KUDOS_DATABASE_URL')

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

env_name = context.get_x_argument(as_dictionary=True).get('env')
if env_name:
    load_environment(env_name)


def _database_url():
    for name in _DSN_VARIABLES:
        dsn = os.environ.get(name)
        if dsn:
            break
    else:
        raise SystemExit(f"No database configured: pass -x env=<env-name> or set one of {', '.join(_DSN_VARIABLES)}")
    if '://' not in dsn:
        raise SystemExit('Alembic needs a URL-style connection string (postgresql://user:pass@host/db)')
    url = make_url(dsn)
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    return url


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
