#!/usr/bin/env python3
"""Import pre-existing users as account provisions (users added before gyrobot automated this).

Usage (from the repository root; reads APPROVAL_DATABASE_URL from .env.d/<env-name>.env):

    uv run python tools/import_provisions.py <env-name> users.csv            # preview only
    uv run python tools/import_provisions.py <env-name> users.xlsx --apply   # write to the database

Columns (header row required, case-insensitive; CSV may be comma- or semicolon-separated, auto-detected):

    email       required  account primary email
    resource    required  github | jetbrains | crowd | slack
    status      optional  default: assigned
    username    optional  stored in the provision data (GitHub login, Crowd user, ...)
    team        optional  stored in the provision data
    created_at  optional  original date (ISO, e.g. 2024-03-01); keeps invitation-expiry logic correct

Existing account+resource provisions are skipped unless --overwrite is given. Excel input needs
``openpyxl`` (``uv pip install openpyxl``). Imported rows are marked ``imported: true`` in the data
and appear in the audit table like any other change.
"""
import argparse
import csv
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv

RESOURCES = {'github', 'jetbrains', 'crowd', 'slack'}
STATUSES = {'pending', 'invited', 'assigned', 'active', 'expired', 'deprovisioned'}


def read_rows(path: pathlib.Path) -> list[dict]:
    if path.suffix.lower() in ('.xlsx', '.xlsm', '.xls'):
        try:
            import pandas
            frame = pandas.read_excel(path, dtype=str).fillna('')
        except ImportError as e:
            sys.exit(f"Reading Excel files needs openpyxl: uv pip install openpyxl ({e})")
        rows = frame.to_dict('records')
    else:
        with path.open(newline='', encoding='utf-8-sig') as f:
            header = f.readline()
            f.seek(0)
            delimiter = ';' if header.count(';') > header.count(',') else ','
            rows = list(csv.DictReader(f, delimiter=delimiter))
    return [{str(k).strip().lower(): str(v).strip() for k, v in row.items()} for row in rows]


def parse_date(text: str) -> datetime | None:
    if not text:
        return None
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def validate(row: dict, default_status: str) -> tuple[dict | None, str | None]:
    email, resource = row.get('email', ''), row.get('resource', '').lower()
    status = row.get('status') or default_status
    if '@' not in email:
        return None, f"invalid email {email!r}"
    if resource not in RESOURCES:
        return None, f"unknown resource {resource!r}"
    if status not in STATUSES:
        return None, f"unknown status {status!r}"
    try:
        created_at = parse_date(row.get('created_at', ''))
    except ValueError:
        return None, f"invalid created_at {row['created_at']!r}"
    data = {'email': email, 'imported': True}
    for key in ('username', 'team'):
        if row.get(key):
            data[key] = row[key]
    return {'email': email, 'resource': resource, 'status': status, 'data': data,
            'created_at': created_at, 'name': row.get('username') or email}, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('file', type=pathlib.Path)
    parser.add_argument('--default-status', default='assigned')
    parser.add_argument('--overwrite', action='store_true', help='replace provisions that already exist')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage

    rows, errors = [], []
    for number, raw in enumerate(read_rows(args.file), start=2):
        row, error = validate(raw, args.default_status)
        if error:
            errors.append(f"row {number}: {error}")
        else:
            rows.append(row)
    if errors:
        print('\n'.join(errors))
        sys.exit(f"{len(errors)} invalid row(s); nothing was written")

    counts = {'create': 0, 'skip': 0, 'overwrite': 0}
    for row in rows:
        account = storage.get_account_by_email(row['email'])
        existing = storage.get_provision(account.id, row['resource']) if account else None
        if existing and not args.overwrite:
            action = 'skip'
        else:
            action = 'overwrite' if existing else 'create'
        counts[action] += 1
        print(f"{action:9} {row['email']:40} {row['resource']:10} {row['status']:10}"
              f"{' (new account)' if not account else ''}")
        if action == 'skip' or not args.apply:
            continue
        if not account:
            account = storage.create_account(name=row['name'], primary_email=row['email'])
        storage.set_provision_status(account.id, row['resource'], row['status'], row['data'],
                                     created_at=row['created_at'])

    print(f"\n{counts['create']} to create, {counts['overwrite']} to overwrite, {counts['skip']} skipped"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
