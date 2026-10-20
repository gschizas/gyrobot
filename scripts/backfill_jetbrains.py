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

Emails outside ``allowed_email_domains`` (see ``backend/email_domains.py``) never get an account of their own.
Such a licence is attached to an existing account when its email is already one of that account's
``additional_emails``, or when --map names the account:

    uv run python scripts/backfill_jetbrains.py <env-name> --map mapping.csv

where mapping.csv has the header ``external_email,account_email``. The external email is then recorded as an
additional email of that account (so the provision keeps the address JetBrains knows). Otherwise the licence is
skipped, and the preview suggests accounts whose name equals the licence holder's name as lines ready to paste
into the mapping file; suggestions are never applied automatically.
"""
import argparse
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv


def read_mapping(path: str) -> dict[str, str]:
    with open(path, newline='', encoding='utf8') as f:
        reader = csv.DictReader(f)
        if not {'external_email', 'account_email'} <= set(reader.fieldnames or []):
            sys.exit(f"{path}: the header must be external_email,account_email")
        return {row['external_email'].strip().lower(): row['account_email'].strip()
                for row in reader if row['external_email'].strip() and row['account_email'].strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    parser.add_argument('--map', metavar='CSV', help='external_email,account_email pairs for licences held by '
                                                      'emails outside the allowed domains')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.email_domains import allowed_email_domains, is_allowed_email
    from backend.jetbrains_api import JetBrainsApi

    mapping = read_mapping(args.map) if args.map else {}
    domains = allowed_email_domains()
    if not domains:
        print("note: no allowed_email_domains configured, every email is treated as internal\n")

    by_email: dict[str, list[dict]] = {}
    skipped_holders = 0
    for lic in JetBrainsApi().get_licenses(assigned=True):
        assignee = lic.get('assignee') or {}
        if assignee.get('type') != 'USER' or not assignee.get('email'):
            skipped_holders += 1
            continue
        by_email.setdefault(assignee['email'].strip().lower(), []).append(lic)

    counts = {'create': 0, 'complete': 0, 'already': 0, 'not live': 0, 'link': 0, 'external': 0, 'duplicate': 0}
    seen: dict = {}  # account id -> the email whose licence was handled in this run (one provision per account)
    for email, licenses in sorted(by_email.items()):
        lic = licenses[0]
        holder_name = (lic.get('assignee') or {}).get('name') or ''
        data = {'email': email, 'team_name': lic['team']['name'], 'team_id': lic['team']['id'],
                'license_id': lic['licenseId'], 'imported': True}
        note = f" (+{len(licenses) - 1} more licence(s) not recorded)" if len(licenses) > 1 else ''

        account = storage.find_account_by_any_email(email)
        link_to = None
        if not account and not is_allowed_email(email, domains):
            target_email = mapping.get(email)
            if target_email:
                account = storage.find_account_by_any_email(target_email)
                if not account:
                    print(f"{'external':10} {email:40} mapped to {target_email}, which is not an account; skipped{note}")
                    counts['external'] += 1
                    continue
                link_to = account
            else:
                print(f"{'external':10} {email:40} outside the allowed domains and not mapped; skipped{note}")
                for candidate in storage.find_accounts_by_name(holder_name) if holder_name else []:
                    print(f"{'':10} suggestion: {email},{candidate.primary_email}   (name \"{holder_name}\")")
                counts['external'] += 1
                continue

        existing = storage.get_provision(account.id, 'jetbrains') if account else None
        holder = seen.get(account.id) if account else None
        if holder is None and existing and existing.status in storage.LIVE_STATUSES:
            holder = (existing.data.get('email') or email).lower()
        if holder and holder != email:
            print(f"{'duplicate':10} {email:40} {account.primary_email} already holds a licence as {holder}; skipped")
            counts['duplicate'] += 1
            continue
        if account:
            seen[account.id] = email

        if link_to:
            print(f"{'link' if args.apply else 'would link':14} {email:40} additional email of {link_to.primary_email}")
            if args.apply:
                storage.add_additional_email(link_to.id, email)
            counts['link'] += 1

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
                account = storage.create_account(name=holder_name or email, primary_email=email)
            storage.set_provision_status(account.id, 'jetbrains', 'active', data)
        counts['create'] += 1

    print(f"\n{counts['create']} {'created' if args.apply else 'to create'}, "
          f"{counts['complete']} {'completed' if args.apply else 'to complete'}, "
          f"{counts['link']} {'linked' if args.apply else 'to link'}, {counts['already']} already complete, "
          f"{counts['not live']} not live, {counts['external']} external and skipped, "
          f"{counts['duplicate']} duplicate, "
          f"{skipped_holders} not held by a person"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
