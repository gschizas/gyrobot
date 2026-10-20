import os

import click

from backend.account_storage import LIVE_STATUSES, get_account_by_email, get_or_create_account, get_provision, \
    set_provision_status
from backend.approval import requires_approval
from backend.arguments import extract_email
from backend.jetbrains_api import JetBrainsApi
from backend.providers import ProvisionRequest, PROVIDERS, RESOURCE_LABELS
from backend.team_mapping import resolve_team
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _jetbrains_summary(params: dict) -> str:
    return f"onboard {params['email']} to JetBrains team {params['team_name']}"


def _jetbrains_validate(params: dict, ctx: ExtendedContext) -> str | None:
    email = extract_email(ctx, params['email'])
    if not email:
        return f"'{params['email']}' is not a valid email address."
    params['email'] = email

    account = get_account_by_email(email)
    existing = get_provision(account.id, 'jetbrains') if account else None
    if existing and existing.status in LIVE_STATUSES:
        return f"{email} already has a JetBrains licence (team: {existing.data.get('team_name', 'unknown')})."

    # The argument is a core team (via config/team_mapping.yml) or else a JetBrains team name/slug/id
    requested = params['team_name']
    api = JetBrainsApi()
    mapped = resolve_team('jetbrains', requested)
    try:
        team = api.find_team(mapped or requested)
    except ValueError as first_error:
        if not mapped:
            return str(first_error)
        try:
            team = api.find_team(requested)
        except ValueError:
            return str(first_error)
    if team.unassigned_licenses < 1:
        return f"JetBrains team {team.name} has no free licences left."
    params['team_name'] = team.name  # stored in the request, so the approver sees the real team
    return None


@click.command('jetbrains')
@click.argument('email')
@click.argument('team_name')
@click.pass_context
@requires_approval(summarize=_jetbrains_summary, validate=_jetbrains_validate)
def onboard_jetbrains(ctx: ExtendedContext, email: str, team_name: str):
    """Onboard a colleague for JetBrains IntelliJ IDEA.

    TEAM_NAME is a core team (mapped through config/team_mapping.yml) or a JetBrains team name, slug or id.

    USAGE: bot onboard jetbrains <email> <team_name>
    """
    account_obj = ProvisionRequest(name=email, email=email, userid=email, team=team_name)
    message = PROVIDERS['jetbrains'].provision(ctx, account_obj)

    provision_data = {'email': email, 'team_name': team_name, **account_obj.provision_data}
    account = get_or_create_account(primary_email=email, name=email)
    set_provision_status(account.id, 'jetbrains', 'active', provision_data)

    result = [{'Resource': RESOURCE_LABELS['jetbrains'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {email}', table=result)
    return f"{RESOURCE_LABELS['jetbrains']}: {message}"
