# /// script
# requires-python = ">=3.12"
# dependencies = ["click", "tqdm", "ldap3>=2.9.1", "pycryptodome", "requests", "ruamel.yaml", "sqlalchemy", "python-dotenv"]
# ///
"""Check whether the AD CN (lower-cased) or sAMAccountName matches the Crowd user name, for every Crowd user.

Read-only. Run from the repo root:

    uv run scripts/check_crowd_usernames.py <env-name> [--mismatches-only] [--csv FILE]
"""
import csv
import pathlib
import sys
from collections import Counter

import click
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.crowd_api import CrowdApi  # noqa: E402
from backend.ldap_directory import LdapDirectory  # noqa: E402
from backend.secret_store import load_environment  # noqa: E402

NO_MATCH, AMBIGUOUS, DIFFER, OK = 'no AD match', 'ambiguous AD match', 'CN and sAMAccountName differ', 'ok'


def classify(crowd_name, people):
    """Return (category, detail) for one Crowd user and the AD people found for it."""
    if not people:
        return NO_MATCH, ''
    if len(people) > 1:
        return AMBIGUOUS, ', '.join(p.login for p in people)
    person = people[0]
    name = crowd_name.lower()
    cn, login = person.cn.lower(), person.login.lower()
    detail = f"cn={cn} sam={login}"
    if name == cn and name == login:
        return OK, detail
    if name != cn and name != login:
        return DIFFER, detail + ' (matches neither)'
    return DIFFER, detail + (' (matches only CN)' if name == cn else ' (matches only sAMAccountName)')


@click.command()
@click.argument('env_name')
@click.option('--mismatches-only', is_flag=True, help='Do not list users that match.')
@click.option('--csv', 'csv_path', type=click.Path(dir_okay=False), default='crowd_username_mismatches.csv',
              show_default=True, help='Where to write the mismatches.')
def main(env_name, mismatches_only, csv_path):
    load_environment(env_name)
    crowd, ldap = CrowdApi(), LdapDirectory()
    users = crowd.list_users()
    results = []
    try:
        for user in tqdm(users, desc='Checking users', unit='user'):
            name = user['name']
            people = ldap.find_people(user.get('email') or '') if user.get('email') else []
            if not people:
                people = ldap.find_people(name)
            category, detail = classify(name, people)
            results.append((name, user.get('email', ''), category, detail))
    finally:
        ldap.close()

    counts = Counter(r[2] for r in results)
    for category, count in counts.most_common():
        click.echo(f"{count:6}  {category}")
    for row in results:
        if row[2] != OK or not mismatches_only:
            click.echo(f"{row[2]}: {row[0]} <{row[1]}> {row[3]}")
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['crowd_user', 'email', 'category', 'detail'])
        writer.writerows(r for r in sorted(results, key=lambda r: (r[2], r[0])) if r[2] != OK)
    click.echo(f"Mismatches written to {csv_path}")


if __name__ == '__main__':
    main()
