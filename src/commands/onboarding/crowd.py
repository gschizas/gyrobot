import os

import click

from backend.account_storage import LIVE_STATUSES, get_account_by_email, get_or_create_account, get_provision, \
    set_membership, set_provision_status
from backend.approval import requires_approval
from backend.crowd_api import CrowdApi
from backend.crowd_config import load_settings
from backend.ldap_directory import LdapDirectory
from backend.providers import ProvisionRequest, PROVIDERS, RESOURCE_LABELS
from backend.team_mapping import resolve_teams
from commands import DefaultCommandGroup
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _crowd_summary(params: dict) -> str:
    extra = f" (+ groups {', '.join(params['group'])})" if params.get('group') else ''
    return f"onboard {params['user']} to Crowd, canonical team {params['team']}{extra}"


def _crowd_validate(params: dict, ctx: ExtendedContext) -> str | None:
    settings = load_settings()
    directory = LdapDirectory(settings)
    try:
        person = directory.find_person(params['user'])
    except ValueError as e:
        return f"{e}; use the email address."
    finally:
        directory.close()
    if not person:
        return f"{params['user']} was not found in the directory."
    if not (person.mail and person.first_name and person.last_name and person.username):
        return f"The directory entry of {params['user']} lacks a mail address or a name."

    groups = resolve_teams('crowd', params['team'])
    if not groups:
        return f"No Crowd group mapping for canonical team '{params['team']}' (config/team_mapping.yml)."
    available = CrowdApi(settings).get_groups()
    unknown = [g for g in [*groups, *params['group']] if g not in available]
    if unknown:
        return f"Unknown Crowd group(s): {', '.join(unknown)}. See 'onboard crowd groups'."

    account = get_account_by_email(person.mail)
    existing = get_provision(account.id, 'crowd') if account else None
    if existing and existing.status in LIVE_STATUSES:
        return f"{person.mail} already has a Crowd user ({existing.data.get('username', 'unknown')}); " \
               f"use 'onboard move' to change the team."
    params['user'] = person.mail  # the approver sees the resolved person
    return None


@click.group('crowd', cls=DefaultCommandGroup)
def crowd_group():
    """Crowd users: add (default), lookup, groups"""


@crowd_group.command('add', default_command=True)
@click.argument('user')
@click.argument('team')
@click.option('-g', '--group', multiple=True, help='Extra Crowd group (repeatable), besides the canonical team ones')
@click.pass_context
@requires_approval(summarize=_crowd_summary, validate=_crowd_validate)
def onboard_crowd(ctx: ExtendedContext, user: str, team: str, group: tuple):
    """Onboard a colleague for Crowd (Atlassian): creates the user, adds the groups and emails the password.

    USER is the login or email address in the directory; TEAM is a canonical team (config/team_mapping.yml).

    USAGE: bot onboard crowd [add] <user> <team> [--group <crowd group>]...
    """
    account_obj = ProvisionRequest(name=user, email=user, userid=user, team=team,
                                   provision_data={'extra_groups': list(group)})
    message = PROVIDERS['crowd'].provision(ctx, account_obj)

    data = account_obj.provision_data
    account = get_or_create_account(primary_email=data['email'], name=user, team=team)
    set_provision_status(account.id, 'crowd', 'active', data)
    set_membership(account.id, team, None)

    ctx.chat.send_table(title=f'Onboarded {user}', table=[{'Resource': RESOURCE_LABELS['crowd'], 'Result': message}])
    return f"{RESOURCE_LABELS['crowd']}: {message}"


@crowd_group.command('lookup')
@click.argument('user')
@click.pass_context
def crowd_lookup(ctx: ExtendedContext, user: str):
    """Show what the directory and Crowd know about a person. Read-only, not gated by approval.

    USAGE: bot onboard crowd lookup <login or email>
    """
    settings = load_settings()
    directory = LdapDirectory(settings)
    try:
        people = directory.find_people(user)
    finally:
        directory.close()
    if not people:
        ctx.chat.send_text(f"{user} was not found in the directory.", is_error=True)
        return
    api = CrowdApi(settings)
    rows = []
    for person in people:
        crowd_user = api.get_user(person.username)
        rows.append({
            'Name': f"{person.first_name} {person.last_name}", 'Email': person.mail, 'Crowd user': person.username,
            'CN': person.cn, 'sAMAccountName': person.login,
            'In Crowd': 'no' if crowd_user is None else ('active' if crowd_user.get('active') else 'inactive'),
            'Groups': ', '.join(api.get_user_groups(person.username)) if crowd_user else ''})
    ctx.chat.send_table(title=f'Directory and Crowd: {user}', table=rows)


@crowd_group.command('groups')
@click.argument('text', required=False)
@click.pass_context
def crowd_groups(ctx: ExtendedContext, text: str | None):
    """List the Crowd groups that can be assigned, optionally only those whose name or description has TEXT.

    USAGE: bot onboard crowd groups [text]
    """
    wanted = (text or '').lower()
    rows = [{'Group': name, 'Description': description}
            for name, description in CrowdApi().get_groups().items()
            if wanted in name.lower() or wanted in description.lower()]
    if not rows:
        ctx.chat.send_text("No matching groups.")
        return
    ctx.chat.send_table(title='Crowd groups', table=rows)
