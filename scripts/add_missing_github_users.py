#!/usr/bin/env python3
"""Find GitHub enterprise members that have no GitHub provision in the database, and add them.

Usage (from the repository root; reads the database and GitHub settings from .env.d/<env-name>.env):

    uv run python scripts/add_missing_github_users.py <env-name>                     # preview only
    uv run python scripts/add_missing_github_users.py <env-name> --apply             # write to the database
    uv run python scripts/add_missing_github_users.py <env-name> --emails fill.csv   # supply emails by hand
    uv run python scripts/add_missing_github_users.py <env-name> --user LOGIN --verbose   # troubleshoot one user

``--user`` checks (and, with ``--apply``, adds) just that user. ``--verbose`` prints GitHub's answer per
organization: the verified emails, the user's organizations and any errors (for example SAML/SSO ones).

Only members of at least one enterprise team are checked. A member counts as known when a GitHub provision (any status) has their username. For each unknown member the
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


def diagnose_user(github, ses, login: str) -> None:
    """Print the raw GraphQL answer for one user's verified emails, org by org, errors included."""
    import json
    from backend.github_api import GRAPHQL_URL

    orgs = github.get_org_logins(ses)
    print(f"\nEnterprise organizations ({len(orgs)}): {', '.join(orgs)}")
    for org in orgs:
        query = ('query($login: String!) { user(login: $login) { login id '
                 f'organizationVerifiedDomainEmails(login: "{org}") '
                 'organizations(first: 100) { nodes { login } } } }')
        response = ses.post(GRAPHQL_URL, json={'query': query, 'variables': {'login': login}})
        print(f"\n--- {org}: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            print(response.text[:2000])
            continue
        user = (body.get('data') or {}).get('user') or {}
        print('verified emails:', user.get('organizationVerifiedDomainEmails'))
        print('member of:', [o['login'] for o in (user.get('organizations') or {}).get('nodes', [])])
        for error in body.get('errors', []):
            print('error:', json.dumps({k: v for k, v in error.items() if k != 'locations'})[:600])
    print('\n--- end of GitHub responses\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--emails', type=pathlib.Path, help='CSV of login,email for members GitHub has no email for')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    parser.add_argument('--user', metavar='LOGIN', help='check only this GitHub user, even if in no team')
    parser.add_argument('--verbose', action='store_true',
                        help='with --user: show what GitHub returns (organizations, verified emails, errors)')
    args = parser.parse_args()
    if args.verbose and not args.user:
        parser.error('--verbose needs --user')

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.github_api import GitHubApi

    manual = read_email_map(args.emails) if args.emails else {}
    github = GitHubApi()
    print('Reading the enterprise members and teams from GitHub...')
    # The user session (SSO-authorized) is needed to read the organizations' verified emails
    ses = github.ses_usr
    teams_by_login: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for row in github._ent_team_member_rows('', ses):
        teams_by_login.setdefault(row['login'].lower(), []).append(row['team'])
        names[row['login'].lower()] = row['login']
    known = {p.data['username'].lower() for p in storage.get_provisions('github') if p.data.get('username')}
    if args.user:
        key = args.user.lower()
        names.setdefault(key, args.user)
        print(f"{args.user}: {'known' if key in known else 'NOT known'} in the database, "
              f"teams: {', '.join(teams_by_login.get(key, [])) or 'none'}")
        if args.verbose:
            diagnose_user(github, ses, args.user)
        if key in known:
            return
        unknown = [key]
    else:
        unknown = sorted((key for key in teams_by_login if key not in known))
    print(f"{len(teams_by_login)} team members, {len(known)} known provisions, {len(unknown)} without a provision\n")
    emails_by_login = github.get_verified_emails([names[key] for key in unknown], ses) if unknown else {}
    missing = [{'login': names[key], 'verified_emails': emails_by_login.get(key, [])} for key in unknown]

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
