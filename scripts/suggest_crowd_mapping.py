# /// script
# requires-python = ">=3.12"
# dependencies = ["click", "tqdm", "requests", "ruamel.yaml", "sqlalchemy", "python-dotenv", "pycryptodome", "ldap3>=2.9.1"]
# ///
"""Suggest the ``crowd:`` section of config/team_mapping.yml by fuzzy-matching the GitHub canonical teams with the
Crowd groups. Read-only; the output is a starting point to edit by hand, not a mapping to trust.

Run from the repo root:

    uv run scripts/suggest_crowd_mapping.py <env-name> [--output FILE] [--cutoff 0.5] [--candidates 3]

The file is new (an existing one is never overwritten). Every canonical team gets its best match as the value and
the other candidates as comments; teams without a candidate above the cutoff are left commented out.
"""
import difflib
import pathlib
import re
import sys

import click
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.crowd_api import CrowdApi  # noqa: E402
from backend.github_api import GitHubApi  # noqa: E402
from backend.secret_store import load_environment  # noqa: E402


def tokens(name: str) -> list[str]:
    return [t for t in re.split(r'[-_\s]+', name.lower()) if t]


def score(team: str, group: str) -> float:
    """Similarity in [0, 1]: the shared words weigh more than the spelling."""
    a, b = tokens(team), tokens(group)
    if not a or not b:
        return 0.0
    shared = len(set(a) & set(b)) / len(set(a) | set(b))
    spelling = difflib.SequenceMatcher(None, '-'.join(a), '-'.join(b)).ratio()
    return 0.6 * shared + 0.4 * spelling


def candidates(team: str, groups: list[str], cutoff: float, limit: int) -> list[tuple[float, str]]:
    ranked = sorted(((score(team, group), group) for group in groups), reverse=True)
    return [(s, g) for s, g in ranked[:limit] if s >= cutoff]


@click.command()
@click.argument('env_name')
@click.option('--output', type=click.Path(dir_okay=False), default='crowd_mapping_suggestion.yml', show_default=True)
@click.option('--cutoff', type=float, default=0.5, show_default=True, help='Lowest similarity worth suggesting.')
@click.option('--candidates', 'limit', type=int, default=3, show_default=True, help='Candidates listed per team.')
def main(env_name, output, cutoff, limit):
    path = pathlib.Path(output)
    if path.exists():
        raise click.ClickException(f"{path} exists; refusing to overwrite it.")
    load_environment(env_name)
    teams = [o['value'] for o in GitHubApi.flatten_team_tree(GitHubApi().build_team_tree())]
    groups = sorted(CrowdApi().get_groups())
    lines, matched = ['crowd:'], 0
    for team in tqdm(sorted(teams), desc='Matching teams', unit='team'):
        found = candidates(team, groups, cutoff, limit)
        if not found:
            lines.append(f"  # {team}: ???")
            continue
        matched += 1
        lines.append(f"  {team}: {found[0][1]}  # {found[0][0]:.2f}")
        lines.extend(f"  #   alternative: {group}  # {s:.2f}" for s, group in found[1:])
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    click.echo(f"{matched} of {len(teams)} teams have a suggestion; written to {path}. Review it by hand, "
               f"then move the section into config/team_mapping.yml.")


if __name__ == '__main__':
    main()
