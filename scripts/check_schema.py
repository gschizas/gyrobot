#!/usr/bin/env python3
"""Check that the database has every table, column and index the code expects (read-only).

Usage (from the repository root; reads the database settings from .env.d/<env-name>.env):

    uv run python scripts/check_schema.py <env-name>

The expectations are read from the ``_SCHEMA`` strings of ``backend/account_storage.py`` and
``backend/approval.py``, so there is nothing to keep in sync. Exit code is 0 if the database is up to date,
1 if something is missing. Column types are not compared, only names.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

import os

import psycopg
from dotenv import load_dotenv

NOT_COLUMNS = {'unique', 'primary', 'constraint', 'foreign', 'check'}


def parse_schema(sql: str) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({table: [columns]}, [index names]) declared in a CREATE script."""
    tables = {}
    for name, body in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);', sql, re.S | re.I):
        columns = []
        for line in body.splitlines():
            line = line.split('--')[0].strip()
            match = re.match(r'(\w+)\s+\w+', line)
            if match and match.group(1).lower() not in NOT_COLUMNS:
                columns.append(match.group(1))
        tables[name] = columns
    return tables, re.findall(r'CREATE INDEX IF NOT EXISTS (\w+)', sql, re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage, approval

    expected_tables, expected_indexes = {}, []
    for module in (account_storage, approval):
        tables, indexes = parse_schema(module._SCHEMA)
        expected_tables.update(tables)
        expected_indexes += indexes

    with psycopg.connect(os.environ['APPROVAL_DATABASE_URL'], connect_timeout=10) as conn:
        cur = conn.cursor()
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema()")
        actual: dict[str, set[str]] = {}
        for table, column in cur.fetchall():
            actual.setdefault(table, set()).add(column)
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
        actual_indexes = {row[0] for row in cur.fetchall()}

    problems = []
    for table, columns in expected_tables.items():
        if table not in actual:
            problems.append(f"missing table {table}")
            continue
        problems += [f"missing column {table}.{c}" for c in columns if c not in actual[table]]
    problems += [f"missing index {i}" for i in expected_indexes if i not in actual_indexes]

    if problems:
        print("Database is NOT up to date:")
        print('\n'.join(f"  - {p}" for p in problems))
        print("Create the missing objects with the statements in the _SCHEMA of backend/account_storage.py.")
        return 1
    print(f"Database is up to date ({len(expected_tables)} tables, {len(expected_indexes)} indexes checked).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
