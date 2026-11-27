"""Import the active Crowd users as ``crowd`` provisions (status ``active``), creating the accounts that are missing.

Deactivated Crowd users are skipped, and so are users whose email is outside the AD mail domain (unless
--include-external). Accounts are found by email (primary or additional); new ones are named from the directory
(the romanized Greek name when the Latin one disagrees with it), else from Crowd's own first and last name.
The groups the user is in (among the configured prefixes) are recorded as ``extra_groups``, so a later
``onboard move`` never removes them. Existing live provisions are only completed, never overwritten.

Run from the repo root (it uses the project environment, since it imports the bot's backend):

    uv run scripts/import_crowd_users.py <env-name>           # preview only
    uv run scripts/import_crowd_users.py <env-name> --apply   # write to the database
"""
import pathlib
import sys
from collections import Counter

import click
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.crowd_api import CrowdApi  # noqa: E402
from backend.ldap_directory import LdapDirectory  # noqa: E402
from backend.names import title_case  # noqa: E402
from backend.secret_store import load_environment  # noqa: E402


def account_name(person, crowd_user: dict) -> str:
    """The display name for a new account."""
    if person:
        if person.name_mismatch and person.expected_first_name and person.expected_last_name:
            return f"{person.expected_first_name} {person.expected_last_name}"
        return person.display_name
    return f"{title_case(crowd_user.get('first-name') or '')} {title_case(crowd_user.get('last-name') or '')}".strip()


@click.command()
@click.argument('env_name')
@click.option('--apply', is_flag=True, help='Write to the database (default: preview only).')
@click.option('--include-external', is_flag=True, help='Also import users whose email is outside the mail domain.')
def main(env_name, apply, include_external):
    load_environment(env_name)
    from backend import account_storage as storage

    crowd, ldap = CrowdApi(), LdapDirectory()
    suffix = '@' + ldap.settings.ldap.mail_domain.lower()
    assignable = crowd.get_groups()
    counts = Counter()
    lines = []
    try:
        for user in tqdm(crowd.list_users(), desc='Importing users', unit='user'):
            username, email = user['name'], (user.get('email') or '').strip().lower()
            if not user.get('active', True):
                counts['inactive'] += 1
                continue
            if not email:
                lines.append(f"no email  {username}: skipped")
                counts['no email'] += 1
                continue
            if not email.endswith(suffix) and not include_external:
                counts['external'] += 1
                continue
            groups = [g for g in crowd.get_user_groups(username) if g in assignable]
            data = {'username': username, 'email': email, 'team_groups': [], 'extra_groups': groups,
                    'imported': True}

            account = storage.find_account_by_any_email(email)
            existing = storage.get_provision(account.id, 'crowd') if account else None
            if existing and existing.status not in storage.LIVE_STATUSES:
                lines.append(f"not live  {username} <{email}>: provision is {existing.status}, Crowd user is active")
                counts['not live'] += 1
                continue
            if existing:
                missing = {k: v for k, v in data.items() if k != 'imported' and not existing.data.get(k)}
                if missing:
                    lines.append(f"complete  {username} <{email}>: {', '.join(missing)}")
                    if apply:
                        storage.merge_provision_data(existing.account_id, 'crowd', missing)
                    counts['complete'] += 1
                else:
                    counts['already'] += 1
                continue

            person = None
            try:
                people = ldap.find_people(username) or ldap.find_people(email)
                person = people[0] if len(people) == 1 else None
            except Exception as e:
                lines.append(f"directory {username}: lookup failed ({e!r}), using Crowd's names")
            if not account:
                name = account_name(person, user)
                lines.append(f"create    {username} <{email}>: new account {name!r}"
                             f"{'' if person else ' (not in the directory)'}")
                counts['create'] += 1
                if apply:
                    account = storage.create_account(name=name, primary_email=email)
            else:
                lines.append(f"create    {username} <{email}>: provision for {account.name!r}")
                counts['create'] += 1
            if apply:
                storage.set_provision_status(account.id, 'crowd', 'active', data)
    finally:
        ldap.close()

    for line in lines:
        click.echo(line)
    click.echo(f"\n{counts['create']} {'created' if apply else 'to create'}, "
               f"{counts['complete']} {'completed' if apply else 'to complete'}, {counts['already']} already complete, "
               f"{counts['not live']} not live, {counts['inactive']} deactivated, {counts['external']} external, "
               f"{counts['no email']} without email" + ('' if apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
