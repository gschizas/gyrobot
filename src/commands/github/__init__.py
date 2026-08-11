import os

import click
from treelib import Tree

from commands import gyrobot, DefaultCommandGroup
from backend.github_api import GitHubApi
from commands.extended_context import ExtendedContext

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

    def clean_slug(t):
        return t['slug'].removeprefix('ent:')

    teams = GitHubApi().get_ent_teams()

    connections = {}
    all_nodes = set()

    # Extract all unique path segments
    for team in teams:
        slug = clean_slug(team)
        parts = slug.split('-')

        # Add all intermediate paths
        for i in range(1, len(parts) + 1):
            node_path = '-'.join(parts[:i])
            all_nodes.add(node_path)

    # Build the tree by connecting each node to its parent
    for node in all_nodes:
        parts = node.split('-')

        if len(parts) == 1:
            # Root level - add to root
            if 'root' not in connections:
                connections['root'] = []
            connections['root'].append(node)
        else:
            # Find parent path (everything except the last segment)
            parent_path = '-'.join(parts[:-1])
            if parent_path not in connections:
                connections[parent_path] = []
            connections[parent_path].append(node)

    # Sort all lists
    for key in connections:
        connections[key] = sorted(connections[key])

    if len(connections['root']) == 1:
        root_item = connections['root'][0]
        connections.pop('root')
    else:
        root_item = 'GitHub'
        connections[root_item] = connections.pop('root')

    tree = Tree()
    generate_tree(root_item)
    text = tree.show(key=lambda x: x.identifier, line_type='ascii-ex', stdout=False)

    ctx.chat.send_text('```\n' + text + '```\n')
