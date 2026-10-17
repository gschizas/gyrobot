"""SQLAlchemy plumbing shared by every database-backed feature.

All the bot's tables live in one PostgreSQL database, whose schema is managed by Alembic (see ``migrations/``).
Each feature keeps its tables in ``backend/models/<feature>.py`` and asks for an engine with :func:`get_engine`,
passing the name of the environment variable that holds its connection string.
"""
import os
from functools import cache

import psycopg
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base of every model; ``Base.metadata`` is what Alembic compares the database with."""


@cache
def _engine(dsn: str) -> Engine:
    if '://' not in dsn:
        # A libpq "key=value" connection string cannot be turned into a SQLAlchemy URL
        return create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(dsn), pool_pre_ping=True)
    url = make_url(dsn)
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    return create_engine(url, pool_pre_ping=True)


def get_engine(env_var: str) -> Engine:
    """The engine for the connection string in environment variable ``env_var`` (one engine per distinct string)."""
    return _engine(os.environ[env_var])
