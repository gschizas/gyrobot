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


def _include_object(obj, name, type_, reflected, compare_to):
    # The database may hold tables that belong to other programs; never propose dropping what has no model
    if type_ == 'table' and reflected and compare_to is None:
        return False
    if type_ == 'index' and reflected and compare_to is None and obj.table.name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'}, include_object=_include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=_include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
