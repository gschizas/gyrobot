"""Onboard / offboard commands.

Both are gated behind the generic approval queue (see ``backend.approval``): issuing
them enqueues a request that a designated approver must approve before the actual
provisioning runs. Provisioning itself is delegated to the provider stubs in
``backend.providers``.

Account metadata and provisioning state are persisted to PostgreSQL via account_storage
for tracking and deprovisioning workflows.
"""
import os

import click

from backend.account_storage import (
    create_account, get_account_by_email, set_provision_status, get_active_provisions
)
from backend.approval import requires_approval
from backend.github_provisioning import check_github_invitations
from backend.providers import PROVIDERS, RESOURCE_LABELS
from backend.providers import slack_provision
from backend.providers.base import Account as ProviderAccount
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


def _crowd_summary(params: dict) -> str:
    return f"onboard {params['username']} to Crowd team {params['team']}"


def _jetbrains_summary(params: dict) -> str:
    return f"onboard {params['email']} to JetBrains team {params['team_name']}"


def _slack_summary(params: dict) -> str:
    member_ids = ', '.join(params.get('member_ids', []))
    return f"onboard {params['email']} to Slack (member IDs: {member_ids})"


def _offboard_summary(params: dict) -> str:
    return f"offboard {params['email']} (all resources + Slack)"


@gyrobot.group('onboard')
@click.pass_context
def onboard(ctx: ExtendedContext):
    """Onboard a colleague for specific resources (queued for approval)"""
    ctx.ensure_object(dict)


@onboard.command('github')
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


@onboard.command('crowd')
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


@onboard.command('jetbrains')
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


@onboard.command('slack')
@click.argument('email')
@click.argument('member_ids', nargs=-1, required=True)
@click.pass_context
@requires_approval(summarize=_slack_summary)
def onboard_slack(ctx: ExtendedContext, email: str, member_ids: tuple):
    """Onboard a colleague for Slack.
    
    USAGE: bot onboard slack <email> <member_id> [<member_id> ...]
    """
    provision_data = {'email': email, 'member_ids': list(member_ids)}

    account_obj = ProviderAccount(name=email, email=email)
    message = PROVIDERS['slack'].provision(ctx, account_obj)

    account = create_account(name=email, primary_email=email)
    set_provision_status(account.id, 'slack', 'active', provision_data)

    result = [{'Resource': RESOURCE_LABELS['slack'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {email}', table=result)
    return f"{RESOURCE_LABELS['slack']}: {message}"


@gyrobot.command('offboard')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_offboard_summary)
def offboard(ctx: ExtendedContext, email: str):
    """Offboard a colleague: remove all licenses/entries and deactivate Slack.
    
    USAGE: bot offboard <email>
    
    Reads all active provisions from storage and calls deprovision for each resource.
    Updates provision status to 'deprovisioned' on success.
    """
    # Look up account by email
    account = get_account_by_email(email)
    if not account:
        ctx.chat.send_text(f"No account found for {email}", is_error=True)
        return f"Error: No account found for {email}"

    results = []
    provision_updates = []

    # Get all active provisions for this account
    provisions = get_active_provisions(account.id)

    # Create a ProviderAccount for compatibility with deprovision stubs
    account_obj = ProviderAccount(name=account.name or email, email=email)

    # Deprovision each active resource
    for provision in provisions:
        if provision.resource not in PROVIDERS:
            ctx.logger.warning(f"Unknown resource type: {provision.resource}")
            continue

        try:
            # Call deprovision (provider can access provision.data for resource-specific info)
            message = PROVIDERS[provision.resource].deprovision(ctx, account_obj)
            results.append({'Resource': RESOURCE_LABELS[provision.resource], 'Result': message})

            # Mark as deprovisioned
            provision_updates.append((provision.account_id, provision.resource, 'deprovisioned'))

        except Exception as e:
            ctx.logger.exception(f"Error deprovisioning {provision.resource} for {email}")
            results.append({
                'Resource': RESOURCE_LABELS[provision.resource],
                'Result': f"Error: {str(e)}"
            })

    # Deactivate Slack (always attempt)
    try:
        slack_result = slack_provision.deactivate(ctx, account_obj)
        results.append({'Resource': 'Slack account', 'Result': slack_result})
    except Exception as e:
        ctx.logger.exception(f"Error deactivating Slack for {email}")
        results.append({'Resource': 'Slack account', 'Result': f"Error: {str(e)}"})

    # Update all successful deprovisions to 'deprovisioned' status
    for account_id, resource, status in provision_updates:
        set_provision_status(account_id, resource, status, {})

    ctx.chat.send_table(title=f'Offboarded {email}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)


@gyrobot.command('github_check')
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
