#!/usr/bin/env python3
"""Find GitHub enterprise members that have no GitHub provision in the database, and add them.

Usage (from the repository root; reads the database and GitHub settings from .env.d/<env-name>.env):

    uv run python scripts/add_missing_github_users.py <env-name>                     # preview only
    uv run python scripts/add_missing_github_users.py <env-name> --apply             # write to the database
    uv run python scripts/add_missing_github_users.py <env-name> --emails fill.csv   # supply emails by hand

A member counts as known when a GitHub provision (any status) has their username. For each unknown member the
email is taken from the verified-domain emails GitHub reports. Members with no email, or with several, are
listed and skipped unless ``--emails`` gives one: a CSV of ``login,email`` rows (a header row is fine).
A member whose email belongs to an account that already has a GitHub provision under another username
(a renamed user?) is reported as a ``conflict`` and left alone; review it by hand with ``onboard whois``.
Added provisions are ``active``, like ``onboard github set-email``: both ids are stored, and the team is
recorded only when the member is in exactly one enterprise team.
"""
import argparse
import csv
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv
from tqdm import tqdm


def read_email_map(path: pathlib.Path) -> dict[str, str]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        return {row[0].strip().lower(): row[1].strip() for row in csv.reader(f)
                if len(row) >= 2 and '@' in row[1]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--emails', type=pathlib.Path, help='CSV of login,email for members GitHub has no email for')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.github_api import GitHubApi

    manual = read_email_map(args.emails) if args.emails else {}
    github = GitHubApi()
    print('Reading the enterprise members and teams from GitHub...')
    members = github.list_enterprise_members()
    teams_by_login = github.get_ent_team_logins()
    known = {p.data['username'].lower() for p in storage.get_provisions('github') if p.data.get('username')}
    missing = sorted((m for m in members if m['login'].lower() not in known), key=lambda m: m['login'].lower())
    print(f"{len(members)} members, {len(known)} known provisions, {len(missing)} members without a provision\n")

    counts = {'added': 0, 'no_email': 0, 'ambiguous': 0, 'conflict': 0, 'error': 0}
    for member in tqdm(missing, desc='Missing members', unit='user'):
        login = member['login']
        emails = member['verified_emails']
        email = manual.get(login.lower()) or (emails[0] if len(emails) == 1 else None)
        if not email:
            kind = 'ambiguous' if emails else 'no_email'
            tqdm.write(f"{kind.replace('_', ' '):12} {login}" + (f": {', '.join(emails)}" if emails else ''))
            counts[kind] += 1
            continue

        account = storage.find_account_by_any_email(email)
        existing = account and storage.get_provision(account.id, 'github')
        if existing:
            tqdm.write(f"{'conflict':12} {login}: {email} already has GitHub user "
                       f"{existing.data.get('username')} ({existing.status})")
            counts['conflict'] += 1
            continue

        teams = teams_by_login.get(login.lower(), [])
        team = teams[0] if len(teams) == 1 else None
        tqdm.write(f"{'add' if args.apply else 'would add':12} {login:30} {email} "
                   f"({team or f'{len(teams)} teams, none recorded'})")
        if args.apply:
            data = {'username': login, 'email': email, 'recorded_by': 'add_missing_github_users',
                    'recorded_at': datetime.datetime.now(tz=datetime.timezone.utc).isoformat()}
            try:
                data.update(github.get_user_ids(login))
            except Exception as e:
                tqdm.write(f"{'warning':12} no ids for {login}: {e}")
            if team:
                data['team'] = team
            try:
                account = account or storage.get_or_create_account(primary_email=email, name=login, team=team)
                storage.set_provision_status(account.id, 'github', 'active', data)
            except Exception as e:
                tqdm.write(f"{'error':12} {login}: {e}")
                counts['error'] += 1
                continue
        counts['added'] += 1

    print(f"\n{counts['added']} {'added' if args.apply else 'to add'}, {counts['no_email']} without an email, "
          f"{counts['ambiguous']} with several emails, {counts['conflict']} conflicts, {counts['error']} errors"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))
    if counts['no_email'] or counts['ambiguous']:
        print("Put login,email rows in a CSV and pass it with --emails to add those members.")


if __name__ == '__main__':
    main()
