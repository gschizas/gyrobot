#!/usr/bin/env python3
"""Record the JetBrains licences that already exist in the JetBrains account as provisions.

Licences assigned before the bot managed JetBrains have no provision, so ``offboard`` and ``onboard move`` cannot
see them. Usage (from the repository root; reads the database and JetBrains settings from .env.d/<env-name>.env):

    uv run python scripts/backfill_jetbrains.py <env-name>           # preview only
    uv run python scripts/backfill_jetbrains.py <env-name> --apply   # write to the database

For every IntelliJ IDEA licence assigned to a person (not to a licence server or key) the script creates an
``active`` jetbrains provision holding the email, JetBrains team and licence id, marked ``imported: true``;
the account is created when the email is unknown. Existing live provisions are only completed with a missing
licence/team id. A person with a deprovisioned (or otherwise not live) provision is reported and left untouched,
and so is a person holding several licences (the first is recorded). JetBrains does not say when a licence was
assigned, so the import date is used.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.jetbrains_api import JetBrainsApi

    by_email: dict[str, list[dict]] = {}
    skipped_holders = 0
    for lic in JetBrainsApi().get_licenses(assigned=True):
        assignee = lic.get('assignee') or {}
        if assignee.get('type') != 'USER' or not assignee.get('email'):
            skipped_holders += 1
            continue
        by_email.setdefault(assignee['email'].strip().lower(), []).append(lic)

    counts = {'create': 0, 'complete': 0, 'already': 0, 'not live': 0}
    for email, licenses in sorted(by_email.items()):
        lic = licenses[0]
        data = {'email': email, 'team_name': lic['team']['name'], 'team_id': lic['team']['id'],
                'license_id': lic['licenseId'], 'imported': True}
        note = f" (+{len(licenses) - 1} more licence(s) not recorded)" if len(licenses) > 1 else ''

        account = storage.get_account_by_email(email)
        existing = storage.get_provision(account.id, 'jetbrains') if account else None
        if existing and existing.status not in storage.LIVE_STATUSES:
            print(f"{'not live':10} {email:40} provision is {existing.status}, licence {lic['licenseId']} is still assigned")
            counts['not live'] += 1
            continue
        if existing:
            missing = {k: v for k, v in data.items() if k != 'imported' and not existing.data.get(k)}
            if not missing:
                counts['already'] += 1
                continue
            print(f"{'complete' if args.apply else 'would complete':14} {email:40} {', '.join(missing)}{note}")
            if args.apply:
                storage.merge_provision_data(existing.account_id, 'jetbrains', missing)
            counts['complete'] += 1
            continue

        print(f"{'create' if args.apply else 'would create':14} {email:40} {lic['team']['name']}{note}"
              f"{'' if account else ' (new account)'}")
        if args.apply:
            if not account:
                account = storage.create_account(name=(lic.get('assignee') or {}).get('name') or email,
                                                 primary_email=email)
            storage.set_provision_status(account.id, 'jetbrains', 'active', data)
        counts['create'] += 1

    print(f"\n{counts['create']} {'created' if args.apply else 'to create'}, "
          f"{counts['complete']} {'completed' if args.apply else 'to complete'}, {counts['already']} already complete, "
          f"{counts['not live']} not live, {skipped_holders} not held by a person"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
