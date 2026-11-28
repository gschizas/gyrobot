"""Link the Slack member ids found in the permission rules (``extra.meta.user_info``) to accounts, by name.

The approval rules carry ``{slack id: {name, team}}`` taken from the hand-written comments of
``approvals.permissions.yml`` (see ``migrate_permissions.py``). The comment has no email, so each one is matched to an account: a name without spaces is the email local part
(``<name>@<domain>`` for each of ``allowed_email_domains`` in ``config/github.yml``); any other name is compared with the display names
of the accounts (case, accent and spacing insensitive, a Greek name romanized first). Only unique matches are
linked; ambiguous or unknown ones are listed for you to handle with ``bot onboard slack <email> <id>``. Ids already linked are left alone. With --resolve each id is also looked up in
Slack (needs SLACK_BOT_TOKEN) to record its sign-in email.

Run from the repo root (it uses the project environment, since it imports the bot's backend):

    uv run scripts/import_permission_slack_ids.py <env-name>           # preview only
    uv run scripts/import_permission_slack_ids.py <env-name> --apply   # write to the database
"""
import pathlib
import sys
from collections import Counter

import click
from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.cli import gyrobot_env  # noqa: E402


class _NoLookup:
    def get_user(self, member_id):
        return None


def permission_user_info() -> dict[str, str]:
    """``{slack id: name}`` from every permission rule, the first name seen winning."""
    from backend.database import get_engine
    from backend.models.permissions import PermissionRule

    people: dict[str, str] = {}
    with Session(get_engine()) as session:
        for extra in session.scalars(select(PermissionRule.extra)):
            for user_id, info in ((extra or {}).get('meta') or {}).get('user_info', {}).items():
                if name := (info or {}).get('name'):
                    people.setdefault(user_id, name)
    return people


@click.command()
@click.option('--apply', is_flag=True, help='Write to the database (default: preview only).')
@click.option('--resolve', is_flag=True, help="Also look each id up in Slack to record its sign-in email.")
@gyrobot_env
def main(apply, resolve):
    from backend import account_storage as storage
    from backend import slack_accounts
    from backend.email_domains import allowed_email_domains
    from backend.names import names_agree
    from backend.slack_accounts import parse_member_id
    from backend.slack_directory import SlackDirectory

    directory = SlackDirectory() if resolve else _NoLookup()
    domains = allowed_email_domains()
    if not domains:
        raise click.ClickException('allowed_email_domains in config/github.yml is empty: no mail domain to use')
    accounts = [a for a in storage.get_all_accounts() if a.name]
    counts = Counter()
    lines = []
    for slack_id, name in tqdm(sorted(permission_user_info().items(), key=lambda i: i[1].lower()),
                               desc='Matching people', unit='person'):
        member_id = parse_member_id(slack_id)
        if not member_id:
            lines.append(f"invalid   {slack_id} ({name}): not a Slack member id")
            counts['invalid'] += 1
            continue
        if ' ' not in name.strip():
            found = (storage.find_account_by_any_email(f"{name.strip()}@{domain}") for domain in domains)
            matches = list({a.id: a for a in found if a}.values())
        else:
            matches = [a for a in accounts if names_agree(a.name, name) and names_agree(name, a.name)]
        if len(matches) != 1:
            lines.append(f"{'ambiguous' if matches else 'unknown  '} {member_id} ({name}): "
                         + (', '.join(a.primary_email for a in matches) if matches else 'no account'))
            counts['ambiguous' if matches else 'unknown'] += 1
            continue
        account = matches[0]
        provision = storage.get_provision(account.id, 'slack')
        if provision and member_id in provision.data.get('member_ids', []):
            counts['already'] += 1
            continue
        lines.append(f"link      {member_id} ({name}): {account.primary_email}")
        counts['link'] += 1
        if apply:
            slack_accounts.link(account.primary_email, [member_id], directory)

    for line in lines:
        click.echo(line)
    click.echo(f"\n{counts['link']} {'linked' if apply else 'to link'}, {counts['already']} already linked, "
               f"{counts['unknown']} unknown name, {counts['ambiguous']} ambiguous, {counts['invalid']} invalid"
               + ('' if apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
