PLUGIN = {'requires': ['GITHUB_TOKEN', 'GITHUB_ORG'], 'dependencies': ['treelib>=1.8.0']}

import os

import click
from treelib import Tree

from commands import gyrobot, DefaultCommandGroup
from backend.github_api import GitHubApi
from commands.extended_context import ExtendedContext
import psycopg

if 'GITHUB_TOKEN' not in os.environ:
    raise ImportError('GITHUB_TOKEN not found in environment')

if 'GITHUB_ORG' not in os.environ:
    raise ImportError('GITHUB_ORG not found in environment')


@gyrobot.group('github', cls=DefaultCommandGroup)
def github():
    pass


@github.command('teams')
@click.pass_context
def github_teams(ctx: ExtendedContext):
    """Display GitHub Teams"""

    def generate_tree(node_name, parent_node=None):
        # Check if this node is a leaf (has no children)
        is_leaf = node_name not in connections or len(connections[node_name]) == 0

        # Use different display based on whether it's a leaf
        display_name = f"📄 {node_name}" if is_leaf else f"📁 {node_name}"

        parent = tree.create_node(display_name, node_name.lower(), parent=parent_node)
        for branch_name in sorted(connections.get(node_name, []), key=lambda x: x.lower()):
            generate_tree(branch_name, parent)

    teams = GitHubApi().get_ent_teams()
    connections, root_item, _slug_set = GitHubApi().build_team_connections(teams)

    tree = Tree()
    generate_tree(root_item)
    text = tree.show(key=lambda x: x.identifier, line_type='ascii-ex', stdout=False)

    ctx.chat.send_text('```\n' + text + '```\n')

@github.command("members")
@click.argument("team_slug")
@click.pass_context
def github_team_members(ctx: ExtendedContext, team_slug: str):
    """Display members (login, email, team) of enterprise teams whose slug starts with TEAM_SLUG"""
    members = GitHubApi().get_ent_team_members_by_prefix(team_slug)

    if not members:
        ctx.chat.send_text(f"No members found for teams starting with {team_slug}.")
        return

    table = [{'Username': m['login'], 'Email': ', '.join(m['emails']), 'Team': m['team']}
             for m in sorted(members, key=lambda m: (m['team'], m['login'].lower()))]
    ctx.chat.send_table(title=f'Members of teams starting with {team_slug}', table=table)


@github.command("pending-invitations")
@click.argument("team_prefix", required=False)
@click.pass_context
def github_pending_invitations(ctx: ExtendedContext, team_prefix: str | None):
    """Display pending invitations, optionally only for teams starting with TEAM_PREFIX"""
    invitations = GitHubApi().get_pending_invitations()

    if not invitations:
        ctx.chat.send_text("No pending invitations found.")
        return

    usernames = [invite['login'] for invite in invitations]

    with psycopg.connect(os.environ['APPROVAL_DATABASE_URL'], row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ap.* FROM public.account_provisions AS ap WHERE data->>'username' = ANY(%s)",
                        (usernames,))
            db_rows = cur.fetchall()

    users_by_username = {row['data']['username']: row for row in db_rows}
    for inv in invitations:
        user = users_by_username.get(inv['login'])
        if not user:
            continue
        inv['email'] = user['data']['email']
        inv['team'] = user['data']['team']

    if team_prefix:
        prefix = team_prefix.lower().removeprefix('ent:')
        # Only invitations made through the bot have a team on record
        invitations = [inv for inv in invitations if inv.get('team', '').lower().removeprefix('ent:').startswith(prefix)]
        if not invitations:
            ctx.chat.send_text(f"No pending invitations found for teams starting with {team_prefix}.")
            return

    title = 'Pending Invitations' + (f' (teams starting with {team_prefix})' if team_prefix else '')
    ctx.chat.send_table(title=title, table=invitations)