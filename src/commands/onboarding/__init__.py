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
from backend.providers import PROVIDERS, RESOURCE_LABELS
from backend.providers import slack_provision
from backend.providers.base import Account as ProviderAccount
from commands import gyrobot
from commands.extended_context import ExtendedContext


print("onboarding.__init__")

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

from commands.onboarding import crowd,github,jetbrains


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


onboard.add_command(github.onboard_github)
onboard.add_command(github.github_check)
onboard.add_command(crowd.onboard_crowd)
onboard.add_command(jetbrains.onboard_jetbrains)