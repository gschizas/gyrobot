#!/usr/bin/env python3
"""Add the numeric GitHub user id (``github_id``) to existing GitHub provisions.

Usernames can change on GitHub; the id cannot. Usage (from the repository root; reads the database and
GitHub settings from .env.d/<env-name>.env):

    uv run python scripts/backfill_github_ids.py <env-name>           # preview only
    uv run python scripts/backfill_github_ids.py <env-name> --apply   # write to the database

Provisions that already have a ``github_id`` are skipped. A provision whose username no longer exists on
GitHub (renamed or deleted) is reported and left untouched. Costs one GitHub API request per provision.
If the stored username was reassigned to a different person, the id will be wrong, so review the preview.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

import requests
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    args = parser.parse_args()

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.github_api import GitHubApi

    github = GitHubApi()
    counts = {'updated': 0, 'already': 0, 'no_username': 0, 'not_found': 0, 'error': 0}
    for provision in storage.get_provisions('github'):
        username = provision.data.get('username')
        if provision.data.get('github_id'):
            counts['already'] += 1
            continue
        if not username:
            print(f"{'no username':12} account {provision.account_id}")
            counts['no_username'] += 1
            continue
        try:
            user = github.get_user_details(username)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"{'not found':12} {username} ({provision.status})")
                counts['not_found'] += 1
            else:
                print(f"{'error':12} {username}: {e}")
                counts['error'] += 1
            continue
        print(f"{'set' if args.apply else 'would set':12} {username:30} -> {user['id']} ({provision.status})")
        if args.apply:
            storage.merge_provision_data(provision.account_id, 'github', {'github_id': user['id']})
        counts['updated'] += 1

    print(f"\n{counts['updated']} {'updated' if args.apply else 'to update'}, {counts['already']} already had an id, "
          f"{counts['not_found']} not found, {counts['no_username']} without username, {counts['error']} errors"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
