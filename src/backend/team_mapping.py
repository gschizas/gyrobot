"""Mapping of the canonical team (the GitHub enterprise team slug) to each resource's own team.

``config/team_mapping.yml`` holds one section per resource, each mapping canonical teams to that resource's team::

    jetbrains:
      payments: payments-licences       # applies to payments and everything below it (payments-backend, ...)
    crowd:
      payments-backend: dev-payments

Canonical teams are dash-separated hierarchies. A lookup tries the team itself, then each parent
(``payments-backend-api`` -> ``payments-backend`` -> ``payments``), so a resource with coarser teams
needs only one entry. ``github`` needs no entry: the canonical team is already its team.
"""
import pathlib

from bot_framework.yaml_wrapper import yaml

MAPPING_FILE = pathlib.Path('config') / 'team_mapping.yml'

# Resources whose team is the canonical team itself unless the mapping says otherwise
IDENTITY_RESOURCES = ('github',)


def _load() -> dict:
    if not MAPPING_FILE.exists():
        return {}
    with MAPPING_FILE.open(encoding='utf-8') as f:
        return yaml.load(f) or {}


def normalize(team: str) -> str:
    return team.strip().lower().removeprefix('ent:')


def mapped_teams(resource: str) -> list[str]:
    """The resource's own teams that some canonical team is mapped to (a many-to-one mapping repeats values)."""
    return list(dict.fromkeys(str(v) for v in (_load().get(resource) or {}).values()))


def resolve_team(resource: str, canonical_team: str) -> str | None:
    """The team of ``resource`` that corresponds to ``canonical_team``, or None if there is none."""
    mapping = {normalize(str(k)): str(v) for k, v in (_load().get(resource) or {}).items()}
    parts = normalize(canonical_team).split('-')
    for length in range(len(parts), 0, -1):
        candidate = '-'.join(parts[:length])
        if candidate in mapping:
            return mapping[candidate]
    return normalize(canonical_team) if resource in IDENTITY_RESOURCES else None
