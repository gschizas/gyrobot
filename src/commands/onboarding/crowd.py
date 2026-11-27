import os

import click
from treelib import Tree

from backend.account_storage import LIVE_STATUSES, get_account_by_email, get_or_create_account, get_provision, \
    set_membership, set_provision_status
from backend.approval import requires_approval
from backend.crowd_api import CrowdApi
from backend.crowd_config import load_settings
from backend.ldap_directory import LdapDirectory
from backend.manager import refresh_manager
from backend.providers import ProvisionRequest, PROVIDERS, RESOURCE_LABELS
from backend.team_mapping import resolve_teams
from commands import DefaultCommandGroup
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _crowd_summary(params: dict) -> str:
    extra = f" (+ groups {', '.join(params['group'])})" if params.get('group') else ''
    name = f" ({params['given_name']} {params['surname']})" if params.get('given_name') and params.get('surname') else ''
    return f"onboard {params['user']}{name} to Crowd, canonical team {params['team']}{extra}"


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

    available = CrowdApi(settings).get_groups()
    groups = resolve_teams('crowd', params['team'])
    if not groups and params['team'] in available:
        groups = [params['team']]  # a Crowd group picked directly (the web UI's group tree)
    if not groups:
        return f"No Crowd group mapping for canonical team '{params['team']}' (config/team_mapping.yml), " \
               f"and no Crowd group of that name."
    unknown = [g for g in [*groups, *params['group']] if g not in available]
    if unknown:
        return f"Unknown Crowd group(s): {', '.join(unknown)}. See 'onboard crowd groups'."

    account = get_account_by_email(person.mail)
    existing = get_provision(account.id, 'crowd') if account else None
    if existing and existing.status in LIVE_STATUSES:
        return f"{person.mail} already has a Crowd user ({existing.data.get('username', 'unknown')}); " \
               f"use 'onboard move' to change the team."
    params['user'] = person.mail  # the approver sees the resolved person
    params['given_name'] = (params.get('given_name') or '').strip() or person.first_name
    params['surname'] = (params.get('surname') or '').strip() or person.last_name
    return None


@click.group('crowd', cls=DefaultCommandGroup)
def crowd_group():
    """Crowd users: add (default), lookup, groups, teams"""


@crowd_group.command('add', default_command=True)
@click.argument('user')
@click.argument('team')
@click.option('-g', '--group', multiple=True, help='Extra Crowd group (repeatable), besides the canonical team ones')
@click.option('--given-name', default=None, help='Given name, if the directory has it wrong')
@click.option('--surname', default=None, help='Surname, if the directory has it wrong')
@click.pass_context
@requires_approval(summarize=_crowd_summary, validate=_crowd_validate)
def onboard_crowd(ctx: ExtendedContext, user: str, team: str, group: tuple, given_name: str | None = None,
                  surname: str | None = None):
    """Onboard a colleague for Crowd (Atlassian): creates the user, adds the groups and emails the password.

    USER is the login or email address in the directory; TEAM is a canonical team (config/team_mapping.yml).

    USAGE: bot onboard crowd [add] <user> <team> [--group <crowd group>]... [--given-name <name>] [--surname <name>]

    The name comes from the directory (Title Case); the options override it, and it becomes the account's name.
    """
    display_name = f"{given_name} {surname}" if given_name and surname else user
    account_obj = ProvisionRequest(name=display_name, email=user, userid=user, team=team,
                                   provision_data={'extra_groups': list(group), 'given_name': given_name,
                                                   'surname': surname})
    message = PROVIDERS['crowd'].provision(ctx, account_obj)

    data = account_obj.provision_data
    account = get_or_create_account(primary_email=data['email'], name=display_name, team=team)
    refresh_manager(account)
    set_provision_status(account.id, 'crowd', 'active', data)
    set_membership(account.id, team, None)

    ctx.chat.send_table(title=f'Onboarded {display_name}', table=[{'Resource': RESOURCE_LABELS['crowd'], 'Result': message}])
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
        managers = {person.login: directory.get_manager(person) for person in people}
    finally:
        directory.close()
    if not people:
        ctx.chat.send_text(f"{user} was not found in the directory.", is_error=True)
        return
    api = CrowdApi(settings)
    rows = []
    for person in people:
        crowd_user = api.get_user(person.username)
        manager = managers[person.login]
        rows.append({
            'Name': f"{person.first_name} {person.last_name}", 'Email': person.mail, 'Crowd user': person.username,
            'Manager': f"{manager.display_name} <{manager.mail}>" if manager else '',
            'CN': person.cn, 'sAMAccountName': person.login,
            'In Crowd': 'no' if crowd_user is None else ('active' if crowd_user.get('active') else 'inactive'),
            'Groups': ', '.join(api.get_user_groups(person.username)) if crowd_user else ''})
    ctx.chat.send_table(title=f'Directory and Crowd: {user}', table=rows)


def render_group_tree(tree: dict, text: str | None = None, max_depth: int | None = None) -> str:
    """The Crowd group tree as text, drawn like ``onboard github teams``. A group inside several groups is listed
    under each, but expanded only the first time: later copies that have children end in ``(*)``. With ``text``,
    only the groups whose name has it are shown (with everything below them) plus their ancestors. ``max_depth``
    limits the levels shown (1 = the top groups). Returns an empty string when nothing matches."""
    wanted = (text or '').lower()
    memo: dict[str, bool] = {}

    def leads_to_match(node: dict, path: tuple = ()) -> bool:
        name = node['value']
        if name in path:
            return False
        if name not in memo:
            memo[name] = wanted in name.lower() or any(leads_to_match(c, (*path, name)) for c in node['children'])
        return memo[name]

    drawing, expanded = Tree(), set()
    drawing.create_node(f"📁 {tree['label']}", '')

    def visit(node: dict, parent_id: str, level: int, show_all: bool, path: tuple) -> None:
        name = node['value']
        show_all = show_all or not wanted or wanted in name.lower()
        children = [c for c in node['children'] if c['value'] not in path and (show_all or leads_to_match(c, path))]
        mark = ''
        if children and name in expanded:
            mark, children = ' (*)', []
        elif children and max_depth is not None and level >= max_depth:
            mark, children = ' ...', []
        expanded.add(name)
        # The identifier is the path, so a group under several parents gets one node each; it also sorts siblings
        node_id = f"{parent_id}/{name.lower()}"
        drawing.create_node(f"{'📁' if node['children'] else '📄'} {name}{mark}", node_id, parent=parent_id)
        for child in sorted(children, key=lambda c: c['value'].lower()):
            visit(child, node_id, level + 1, show_all, (*path, name))

    roots = [c for c in tree['children'] if leads_to_match(c)]
    for root in sorted(roots, key=lambda c: c['value'].lower()):
        visit(root, '', 1, False, ())
    if not roots:
        return ''
    return drawing.show(key=lambda x: x.identifier, line_type='ascii-ex', stdout=False)


@crowd_group.command('teams')
@click.argument('text', required=False)
@click.option('-d', '--depth', type=click.IntRange(min=1), help='Show only this many levels (1 = the top groups)')
@click.option('-f', '--flat', is_flag=True, help='List the matching group names, sorted, instead of a tree')
@click.pass_context
def crowd_teams(ctx: ExtendedContext, text: str | None, depth: int | None, flat: bool):
    """Display the Crowd groups as a tree, optionally only those whose name has TEXT (and their parents).

    A group inside several groups is listed under each of them; its later occurrences are marked (*) and not
    expanded again. With --flat, the group names are listed sorted, one per line.

    USAGE: bot onboard crowd teams [text] [--depth N] [--flat]
    """
    api = CrowdApi()
    if flat:
        wanted = (text or '').lower()
        output = '\n'.join(sorted((n for n in api.get_groups() if wanted in n.lower()), key=str.lower))
    else:
        output = render_group_tree(api.build_group_tree(), text, depth)
    if not output:
        ctx.chat.send_text("No matching groups.")
        return
    ctx.chat.send_code(output)


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
