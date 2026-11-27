#!/usr/bin/env python3
"""List the GitHub enterprise members that are in no enterprise team and in no enterprise organization.

Usage (from the repository root; reads the GitHub settings from .env.d/<env-name>.env):

    uv run python scripts/list_unassigned_github_users.py <env-name>
    uv run python scripts/list_unassigned_github_users.py <env-name> -o unassigned.csv

Read only. A user in an organization but in no team is not listed; use ``--include-org-only`` to list those too.
"""
import argparse
import csv
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name', nargs='?', default=os.environ.get('GYROBOT_ENV'))
    parser.add_argument('-o', '--output', type=pathlib.Path, help='also write the list to this CSV file')
    parser.add_argument('--include-org-only', action='store_true',
                        help='also list members that are in an organization but in no team')
    args = parser.parse_args()
    if not args.env_name:
        parser.error('no environment: pass its name or set GYROBOT_ENV')

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend.github_api import GitHubApi

    github = GitHubApi()
    print('Reading the enterprise teams and members from GitHub...')
    in_team = {row['login'].lower() for row in github._ent_team_member_rows('', github.ses_usr)}
    members = github.list_enterprise_members_with_orgs()

    rows = [{'login': m['login'], 'name': m['name'], 'organizations': ' '.join(m['orgs'])}
            for m in sorted(members, key=lambda m: m['login'].lower())
            if m['login'].lower() not in in_team and (args.include_org_only or not m['orgs'])]
    print(f"{len(members)} members, {len(in_team)} in a team, {len(rows)} listed\n")
    for row in rows:
        print(f"{row['login']:30} {row['name']:30} {row['organizations']}")

    if args.output:
        with args.output.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['login', 'name', 'organizations'])
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWritten to {args.output}")


if __name__ == '__main__':
    main()
