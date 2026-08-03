import os

import click

from backend.account_storage import create_account, set_provision_status
from backend.approval import requires_approval
from backend.providers import Account as ProviderAccount, PROVIDERS, RESOURCE_LABELS
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _jetbrains_summary(params: dict) -> str:
    return f"onboard {params['email']} to JetBrains team {params['team_name']}"


@click.command('jetbrains')
@click.argument('email')
@click.argument('team_name')
@click.pass_context
@requires_approval(summarize=_jetbrains_summary)
def onboard_jetbrains(ctx: ExtendedContext, email: str, team_name: str):
    """Onboard a colleague for JetBrains IntelliJ IDEA.

    USAGE: bot onboard jetbrains <email> <team_name>
    """
    provision_data = {'email': email, 'team_name': team_name}

    account_obj = ProviderAccount(name=email, email=email)
    message = PROVIDERS['jetbrains'].provision(ctx, account_obj)

    account = create_account(name=email, primary_email=email)
    set_provision_status(account.id, 'jetbrains', 'active', provision_data)

    result = [{'Resource': RESOURCE_LABELS['jetbrains'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {email}', table=result)
    return f"{RESOURCE_LABELS['jetbrains']}: {message}"
