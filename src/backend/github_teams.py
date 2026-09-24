"""Builds a hierarchical team structure from the GitHub Enterprise team list.

GitHub Enterprise team slugs in this project follow a dash-separated naming
convention (e.g. ``eng-backend-api``) that implicitly encodes a hierarchy.
This module reconstructs that hierarchy as a tree of synthetic "path" nodes,
shared by:

* ``commands/github/__init__.py`` -- the ``github teams`` chat command, which
  renders it as ASCII art via ``treelib``.
* ``webapp/routers/web.py`` -- the Web UI's onboarding form, which renders it
  as a collapsible/selectable HTML tree (see ``templates/form.html``).

Only nodes whose full dash-joined path matches an *actual* team slug (from
``GitHubApi.get_ent_teams()``) are selectable/assignable; intermediate path
segments that don't correspond to a real team exist purely for grouping.
"""
from typing import Iterable, Optional

from backend.github_api import GitHubApi


def clean_slug(team: dict) -> str:
    """Strip the ``ent:`` prefix GitHub uses for enterprise team slugs."""
    return team['slug'].removeprefix('ent:')


def build_team_connections(teams: Iterable[dict]) -> tuple[dict, str, set]:
    """Reconstruct the parent -> children path map from a flat list of team dicts.

    Returns ``(connections, root_item, slug_set)`` where:

    * ``connections`` maps a node path (dash-joined prefix, or the sentinel
      root item) to the sorted list of its immediate child node paths.
    * ``root_item`` is the path of the single top-level node if there is
      exactly one, otherwise the synthetic label ``'GitHub'`` grouping every
      top-level node.
    * ``slug_set`` is the set of node paths that are real, assignable team
      slugs (as opposed to synthetic intermediate groupings).
    """
    slugs = [clean_slug(team) for team in teams]
    slug_set = set(slugs)

    connections: dict = {}
    all_nodes = set()

    for slug in slugs:
        parts = slug.split('-')
        for i in range(1, len(parts) + 1):
            all_nodes.add('-'.join(parts[:i]))

    for node in all_nodes:
        parts = node.split('-')
        if len(parts) == 1:
            connections.setdefault('root', []).append(node)
        else:
            parent_path = '-'.join(parts[:-1])
            connections.setdefault(parent_path, []).append(node)

    for key in connections:
        connections[key] = sorted(connections[key], key=str.lower)

    if len(connections.get('root', [])) == 1:
        root_item = connections['root'][0]
        connections.pop('root')
    else:
        root_item = 'GitHub'
        connections[root_item] = connections.pop('root', [])

    return connections, root_item, slug_set


def build_team_tree(teams: Optional[Iterable[dict]] = None) -> dict:
    """Build a nested ``{'label', 'value', 'children'}`` tree for the web UI.

    ``value`` is the assignable team slug (the same string ``onboard github``
    expects) if the node is a real team, or ``None`` if it's just a grouping
    node with no corresponding team.
    """
    if teams is None:
        teams = GitHubApi().get_ent_teams()

    connections, root_item, slug_set = build_team_connections(teams)

    def make_node(node_path: str) -> dict:
        return {
            'label': node_path,
            'value': node_path if node_path in slug_set else None,
            'children': [make_node(child) for child in connections.get(node_path, [])],
        }

    return make_node(root_item)
