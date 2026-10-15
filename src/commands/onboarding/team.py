import os

import click

from backend.account_storage import LIVE_STATUSES, get_account_by_email, get_active_provisions, \
    set_provision_status, update_account
from backend.approval import requires_approval
from backend.github_api import GitHubApi
from backend.providers import PROVIDERS, RESOURCE_LABELS
from backend.team_mapping import normalize, resolve_team
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _move_summary(params: dict) -> str:
    return f"move {params['email']} to team {params['team']} on all resources"


def _move_validate(params: dict) -> str | None:
    email = params['email'].strip()
    params['team'] = team = normalize(params['team'])
    account = get_account_by_email(email)
    if not account:
        return f"No account found for {email}."
    if not any(p.status in LIVE_STATUSES for p in get_active_provisions(account.id)):
        return f"{email} has no active provisions to move."
    if team not in {t['slug'].removeprefix('ent:') for t in GitHubApi().get_ent_teams()}:
        return f"Team {team} not found."
    return None


@click.command('move')
@click.argument('email')
@click.argument('team')
@click.pass_context
@requires_approval(summarize=_move_summary, validate=_move_validate)
def onboard_move(ctx: ExtendedContext, email: str, team: str):
    """Move a colleague to another team on every resource they hold.

    TEAM is the core team, i.e. the GitHub enterprise team slug (without "ent:"). Each resource's own team
    is found through config/team_mapping.yml. The account's team is only updated if every resource succeeded;
    after fixing a failure the command can simply be run again.

    USAGE: bot onboard move <email> <team>
    """
    team = normalize(team)
    account = get_account_by_email(email.strip())
    if not account:
        ctx.chat.send_text(f"No account found for {email}", is_error=True)
        return f"Error: No account found for {email}"

    results = []
    failed = False
    for provision in get_active_provisions(account.id):
        if provision.status not in LIVE_STATUSES:
            continue
        label = RESOURCE_LABELS.get(provision.resource, provision.resource)
        provider = PROVIDERS.get(provision.resource)
        change_team = getattr(provider, 'change_team', None)
        if not change_team:
            results.append({'Resource': label, 'Result': 'Has no teams, nothing to do'})
            continue
        target = resolve_team(provision.resource, team)
        if not target:
            failed = True
            results.append({'Resource': label, 'Result': f"FAILED: no team mapping for {team}"})
            continue
        try:
            message = change_team(ctx, provision, target)
            set_provision_status(provision.account_id, provision.resource, provision.status, provision.data)
            results.append({'Resource': label, 'Result': message})
        except Exception as e:
            failed = True
            ctx.logger.exception(f"Error moving {email} to {target} on {provision.resource}")
            results.append({'Resource': label, 'Result': f"FAILED: {e}"})

    if failed:
        results.append({'Resource': 'Account', 'Result': f"Team left at {account.team or '(none)'}; fix and re-run"})
    else:
        update_account(account.id, team=team)
        results.append({'Resource': 'Account', 'Result': f"Team set to {team}"})

    ctx.chat.send_table(title=f'Moved {email} to {team}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)
