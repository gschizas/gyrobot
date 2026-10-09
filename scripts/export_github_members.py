#!/usr/bin/env python3
"""Export the GitHub Enterprise members (with verified email and enterprise teams) to CSV.

Usage (from the repository root; reads GITHUB_* settings from .env.d/<env-name>.env):

    uv run python scripts/export_github_members.py <env-name>                  # writes github_members.csv
    uv run python scripts/export_github_members.py <env-name> -o members.csv

The file is ``;``-separated and its columns are compatible with ``scripts/import_provisions.py``:

    email, resource (always "github"), status (always "assigned"), username, team, name, other_emails

* ``email`` is the first organization-verified-domain email across all organizations of the enterprise
  (``user.organizationVerifiedDomainEmails``); any further ones go in ``other_emails`` (``,``-separated).
* ``team`` lists the enterprise teams (``enterprise.enterpriseTeams``) the user belongs to, as slugs
  without the ``ent:`` prefix, ``,``-separated.
* Members without a verified email are still exported (empty ``email``) and listed on stderr, because
  ``import_provisions.py`` needs an email to create the account.
"""
import argparse
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv

COLUMNS = ['email', 'resource', 'status', 'username', 'team', 'name', 'other_emails']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env', help='environment name; loads .env.d/<env>.env')
    parser.add_argument('-o', '--output', default='github_members.csv', help='CSV file to write')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env}.env', override=True)

    # backend.github_api imports account_storage, which needs APPROVAL_DATABASE_URL (no connection is made)
    from backend.github_api import GitHubApi
    api = GitHubApi()

    print('Fetching enterprise members...', file=sys.stderr)
    members = api.list_enterprise_members(api.ses_usr)
    print('Fetching enterprise teams...', file=sys.stderr)
    teams_by_login = api.get_ent_team_logins(api.ses_usr)

    no_email = []
    with open(args.output, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(COLUMNS)
        for member in sorted(members, key=lambda m: m['login'].lower()):
            emails = member['verified_emails']
            if not emails:
                no_email.append(member['login'])
            writer.writerow([
                emails[0] if emails else '', 'github', 'assigned', member['login'],
                ','.join(sorted(teams_by_login.get(member['login'].lower(), []))),
                member['name'], ','.join(emails[1:]),
            ])

    print(f'Wrote {len(members)} members to {args.output}.', file=sys.stderr)
    if no_email:
        print(f'{len(no_email)} member(s) have no verified email: {", ".join(no_email)}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
