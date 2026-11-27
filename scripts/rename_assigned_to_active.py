#!/usr/bin/env python3
"""Rename the provision status ``assigned`` to ``active``, in the provisions and in their history.

Usage (from the repository root; reads the database settings from .env.d/<env-name>.env):

    uv run python scripts/rename_assigned_to_active.py <env-name>           # preview only
    uv run python scripts/rename_assigned_to_active.py <env-name> --apply   # write to the database

Updates ``account_provisions.status`` and both ``status`` and ``previous_status`` of
``account_provision_history``, for every resource, in one transaction. Run it before restarting the bot
with the code that no longer treats ``assigned`` as a live status. Safe to run again.
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name', nargs='?', default=os.environ.get('GYROBOT_ENV'))
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    args = parser.parse_args()
    if not args.env_name:
        parser.error('no environment: pass its name or set GYROBOT_ENV')

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from sqlalchemy import func, select, update
    from backend import account_storage as storage
    from backend.models.accounts import ProvisionHistoryRow, ProvisionRow

    with storage._session() as session, session.begin():
        by_resource = dict(session.execute(
            select(ProvisionRow.resource, func.count()).where(ProvisionRow.status == 'assigned')
            .group_by(ProvisionRow.resource)).all())
        history_status = session.scalar(
            select(func.count()).select_from(ProvisionHistoryRow).where(ProvisionHistoryRow.status == 'assigned'))
        history_previous = session.scalar(
            select(func.count()).select_from(ProvisionHistoryRow)
            .where(ProvisionHistoryRow.previous_status == 'assigned'))
        print(f"provisions: {sum(by_resource.values())} {by_resource or ''}")
        print(f"history rows: {history_status} with status, {history_previous} with previous_status")

        if not args.apply:
            print("\nPreview only, rerun with --apply to write.")
            return
        session.execute(update(ProvisionRow).where(ProvisionRow.status == 'assigned').values(status='active'))
        session.execute(update(ProvisionHistoryRow).where(ProvisionHistoryRow.status == 'assigned')
                        .values(status='active'))
        session.execute(update(ProvisionHistoryRow).where(ProvisionHistoryRow.previous_status == 'assigned')
                        .values(previous_status='active'))
    print("\nDone.")


if __name__ == '__main__':
    main()
