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
    """Display members of a GitHub Team"""
    members = GitHubApi().get_ent_team_members(team_slug)

    if not members:
        ctx.chat.send_text(f"No members found for team {team_slug}.")
        return

    table = [{'Username': member['login'], 'Name': member.get('name', ''), 'Email': member.get('email', '')} for member in members]
    ctx.chat.send_table(title=f'Members of {team_slug}', table=table)


@github.command("pending-invitations")
@click.pass_context
def github_pending_invitations(ctx: ExtendedContext):
    """Display pending invitations for the GitHub organization"""
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

    ctx.chat.send_table(title='Pending Invitations', table=invitations)