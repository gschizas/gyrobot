import os

import click

from backend.account_storage import create_account, set_provision_status
from backend.approval import requires_approval
from backend.providers import Account as ProviderAccount, PROVIDERS, RESOURCE_LABELS
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _crowd_summary(params: dict) -> str:
    return f"onboard {params['username']} to Crowd team {params['team']}"


@click.command('crowd')
@click.argument('username')
@click.argument('team')
@click.pass_context
@requires_approval(summarize=_crowd_summary)
def onboard_crowd(ctx: ExtendedContext, username: str, team: str):
    """Onboard a colleague for Crowd entry.

    USAGE: bot onboard crowd <username> <team>
    """
    provision_data = {'username': username, 'team': team}

    account_obj = ProviderAccount(name=username, email=username)
    message = PROVIDERS['crowd'].provision(ctx, account_obj)

    account = create_account(name=username, primary_email=username)
    set_provision_status(account.id, 'crowd', 'active', provision_data)

    result = [{'Resource': RESOURCE_LABELS['crowd'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {username}', table=result)
    return f"{RESOURCE_LABELS['crowd']}: {message}"
