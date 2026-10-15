"""Mapping of the core team (the GitHub enterprise team slug) to each resource's own team.

``config/team_mapping.yml`` holds one section per resource, each mapping core teams to that resource's team::

    jetbrains:
      payments: payments-licences       # applies to payments and everything below it (payments-backend, ...)
    crowd:
      payments-backend: dev-payments

Core teams are dash-separated hierarchies. A lookup tries the team itself, then each parent
(``payments-backend-api`` -> ``payments-backend`` -> ``payments``), so a resource with coarser teams
needs only one entry. ``github`` needs no entry: the core team is already its team.
"""
import pathlib

from bot_framework.yaml_wrapper import yaml

MAPPING_FILE = pathlib.Path('config') / 'team_mapping.yml'

# Resources whose team is the core team itself unless the mapping says otherwise
IDENTITY_RESOURCES = ('github',)


def _load() -> dict:
    if not MAPPING_FILE.exists():
        return {}
    with MAPPING_FILE.open(encoding='utf-8') as f:
        return yaml.load(f) or {}


def normalize(team: str) -> str:
    return team.strip().lower().removeprefix('ent:')


def resolve_team(resource: str, core_team: str) -> str | None:
    """The team of ``resource`` that corresponds to ``core_team``, or None if there is none."""
    mapping = {normalize(str(k)): str(v) for k, v in (_load().get(resource) or {}).items()}
    parts = normalize(core_team).split('-')
    for length in range(len(parts), 0, -1):
        candidate = '-'.join(parts[:length])
        if candidate in mapping:
            return mapping[candidate]
    return normalize(core_team) if resource in IDENTITY_RESOURCES else None
