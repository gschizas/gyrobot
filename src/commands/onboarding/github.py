import os

import click

from backend.account_storage import create_account, set_provision_status
from backend.approval import requires_approval
from backend.github_provisioning import check_github_invitations
from backend.providers import Account as ProviderAccount, PROVIDERS, RESOURCE_LABELS
from commands import gyrobot
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _github_summary(params: dict) -> str:
    return f"onboard {params['username']} to GitHub team {params['team']}"


def _github_validate(params: dict) -> str:
    # ensure GitHub username exists (stubbed for now)
    # ensure team is valid (stubbed for now)
    return f"Error: Not Implemented : {params!r}"


@click.command('github')
@click.argument('username')
@click.argument('team')
@click.pass_context
@requires_approval(summarize=_github_summary, validate=_github_validate)
def onboard_github(ctx: ExtendedContext, username: str, team: str):
    """Onboard a colleague for GitHub Copilot.

    USAGE: bot onboard github <username> <team>
    """
    provision_data = {'username': username, 'team': team}

    # For now, provision via the stub (using email for ProviderAccount)
    # In real integration, the provider will populate node_id, login, enterprise_user_id
    account_obj = ProviderAccount(name=username, email=username)
    message = PROVIDERS['github'].provision(ctx, account_obj)

    # Store account and provision status
    account = create_account(name=username, primary_email=username)
    set_provision_status(account.id, 'github', 'invited', provision_data)

    result = [{'Resource': RESOURCE_LABELS['github'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {username}', table=result)
    return f"{RESOURCE_LABELS['github']}: {message}"


@click.command('github_check')
@click.pass_context
def github_check(ctx: ExtendedContext):
    """Manually check pending GitHub invitations and auto-assign accepted users.

    This checks all pending GitHub provisioning invitations and attempts to assign
    users to their teams if their invitations have been accepted.

    USAGE: bot github_check
    """
    results = check_github_invitations()

    summary_lines = [
        f"Total pending: {results['total_pending']}",
        f"Accepted & assigned: {len(results['accepted_and_assigned'])}",
        f"Failed: {len(results['failed'])}",
        f"Errors: {len(results['errors'])}",
    ]

    if results['accepted_and_assigned']:
        summary_lines.append(f"✓ Assigned: {', '.join(results['accepted_and_assigned'])}")

    if results['failed']:
        summary_lines.append("✗ Failed:")
        for item in results['failed']:
            summary_lines.append(f"  - {item['username']}: {item['error']}")

    if results['errors']:
        summary_lines.append("⚠ Errors:")
        for error in results['errors']:
            summary_lines.append(f"  - {error}")

    message = '\n'.join(summary_lines)
    ctx.chat.send_text(message)
    return message
