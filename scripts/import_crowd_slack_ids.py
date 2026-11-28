"""Link the Slack member ids stored in Crowd (user attribute ``slack-user-id``) to the matching accounts.

Only active Crowd users with that attribute are considered; the other ``slack-user-id.*`` attributes (other
workspaces, old ids) are ignored. The account is found by the Crowd user's email (primary or additional), and
accounts that do not exist are skipped: run ``import_crowd_users.py`` first. Ids already linked are left alone.
With --resolve each id is also looked up in Slack (needs SLACK_BOT_TOKEN) to record its sign-in email.

Run from the repo root (it uses the project environment, since it imports the bot's backend):

    uv run scripts/import_crowd_slack_ids.py <env-name>           # preview only
    uv run scripts/import_crowd_slack_ids.py <env-name> --apply   # write to the database
"""
import pathlib
import sys
from collections import Counter

import click
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.cli import gyrobot_env  # noqa: E402
from backend.crowd_api import CrowdApi  # noqa: E402

ATTRIBUTE = 'slack-user-id'


class _NoLookup:
    def get_user(self, member_id):
        return None


@click.command()
@click.option('--apply', is_flag=True, help='Write to the database (default: preview only).')
@click.option('--resolve', is_flag=True, help="Also look each id up in Slack to record its sign-in email.")
@gyrobot_env
def main(apply, resolve):
    from backend import account_storage as storage
    from backend import slack_accounts
    from backend.slack_accounts import parse_member_id
    from backend.slack_directory import SlackDirectory

    crowd = CrowdApi()
    directory = SlackDirectory() if resolve else _NoLookup()
    counts = Counter()
    lines = []
    for user in tqdm(crowd.list_users(), desc='Reading Crowd', unit='user'):
        if not user.get('active', True):
            counts['inactive'] += 1
            continue
        raw = crowd.get_user_attributes(user['name']).get(ATTRIBUTE)
        if not raw:
            continue
        username, email = user['name'], (user.get('email') or '').strip().lower()
        member_id = parse_member_id(str(raw))
        if not member_id:
            lines.append(f"invalid   {username}: {raw!r} is not a Slack member id")
            counts['invalid'] += 1
            continue
        account = storage.find_account_by_any_email(email) if email else None
        if not account:
            lines.append(f"no account {username} <{email}>: skipped")
            counts['no account'] += 1
            continue
        provision = storage.get_provision(account.id, 'slack')
        if provision and member_id in provision.data.get('member_ids', []):
            counts['already'] += 1
            continue
        lines.append(f"link      {username} <{email}>: {member_id}")
        counts['link'] += 1
        if apply:
            slack_accounts.link(account.primary_email, [member_id], directory)

    for line in lines:
        click.echo(line)
    click.echo(f"\n{counts['link']} {'linked' if apply else 'to link'}, {counts['already']} already linked, "
               f"{counts['no account']} without account, {counts['invalid']} invalid, {counts['inactive']} deactivated"
               + ('' if apply else "  -- preview only, rerun with --apply to write"))


if __name__ == '__main__':
    main()
