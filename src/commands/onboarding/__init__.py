"""Onboard / offboard commands.

Both are gated behind the generic approval queue (see ``backend.approval``): issuing
them enqueues a request that a designated approver must approve before the actual
provisioning runs. Provisioning itself is delegated to the provider stubs in
``backend.providers``.

Account metadata and provisioning state are persisted to PostgreSQL via account_storage
for tracking and deprovisioning workflows.
"""
PLUGIN = {'requires_files': ['config/github.yml'], 'dependencies': ['treelib>=1.8.0']}

import copy
import datetime
import json
import pathlib

import click

from backend.account_storage import (
    find_account_by_any_email, get_account_provisions, get_provision_history,
    get_or_create_account, get_account_by_email, set_provision_status, get_active_provisions
)
from backend.accounts import Provision
from backend.approval import requires_approval
from backend.arguments import extract_email
from backend.providers import PROVIDERS, RESOURCE_LABELS
from backend.providers import slack_provision
from backend.providers.base import ProvisionRequest
from commands import gyrobot
from commands.extended_context import ExtendedContext

from commands.onboarding import crowd,github,jetbrains,team


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

    account_obj = ProvisionRequest(name=email, email=email)
    message = PROVIDERS['slack'].provision(ctx, account_obj)

    account = get_or_create_account(primary_email=email, name=email)
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
    Only resources that were removed successfully are marked 'deprovisioned' (their stored data is kept);
    a failed one stays live, so the command can simply be run again after fixing the cause.
    """
    email = extract_email(ctx, email) or email.strip()
    account = get_account_by_email(email)
    if not account:
        ctx.chat.send_text(f"No account found for {email}", is_error=True)
        return f"Error: No account found for {email}"

    results = []
    done: list[Provision] = []
    provisions = [p for p in get_active_provisions(account.id) if p.resource in PROVIDERS]
    for unknown in {p.resource for p in get_active_provisions(account.id)} - set(PROVIDERS):
        ctx.logger.warning(f"Unknown resource type: {unknown}")

    for provision in provisions:
        if provision.resource == 'slack':
            continue  # handled below, together with Slack accounts that have no provision
        label = RESOURCE_LABELS[provision.resource]
        try:
            message = PROVIDERS[provision.resource].deprovision(ctx, provision)
            results.append({'Resource': label, 'Result': message})
            done.append(provision)
        except Exception as e:
            ctx.logger.exception(f"Error deprovisioning {provision.resource} for {email}")
            results.append({'Resource': label, 'Result': f"FAILED: {e}"})

    # Slack is always attempted. A person can have several Slack accounts, so use every email and member id known.
    slack_provisions = [p for p in provisions if p.resource == 'slack']
    emails = sorted({email, account.primary_email or email,
                     *(p.data['email'] for p in provisions if p.data.get('email'))}, key=str.lower)
    member_ids = sorted({m for p in slack_provisions for m in p.data.get('member_ids', [])})
    try:
        results.append({'Resource': 'Slack account',
                        'Result': slack_provision.deactivate(ctx, emails, member_ids)})
        done.extend(slack_provisions)
    except Exception as e:
        ctx.logger.exception(f"Error deactivating Slack for {email}")
        results.append({'Resource': 'Slack account', 'Result': f"FAILED: {e}"})

    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    for provision in done:
        data = {**provision.data, 'deprovisioned_at': now, 'deprovisioned_by': ctx.chat.user_id}
        set_provision_status(provision.account_id, provision.resource, 'deprovisioned', data)

    ctx.chat.send_table(title=f'Offboarded {email}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)


@onboard.command('whois')
@click.argument('email')
@click.pass_context
def onboard_whois(ctx: ExtendedContext, email: str):
    """Show everything stored about a person: account, every provision and the status history.

    EMAIL is the primary or an additional email address. Read-only, not gated by approval.
    Aliases: info, show, lookup.

    USAGE: bot onboard whois <email>
    """
    email = extract_email(ctx, email) or email.strip()
    account = find_account_by_any_email(email)
    if not account:
        ctx.chat.send_text(f"No account found for {email}", is_error=True)
        return

    metadata = dict(account.metadata)
    additional = metadata.pop('additional_emails', [])
    fields = [
        {'Field': 'Name', 'Value': account.name or ''},
        {'Field': 'Primary email', 'Value': account.primary_email or ''},
        {'Field': 'Additional emails', 'Value': ', '.join(additional)},
        {'Field': 'Canonical team', 'Value': account.team or ''},
        {'Field': 'Created', 'Value': f"{account.created_at:%Y-%m-%d %H:%M}"},
        {'Field': 'Updated', 'Value': f"{account.updated_at:%Y-%m-%d %H:%M}"},
        {'Field': 'Account id', 'Value': str(account.id)},
    ]
    if metadata:
        fields.append({'Field': 'Other metadata', 'Value': json.dumps(metadata, ensure_ascii=False, default=str)})
    ctx.chat.send_table(title=f'Account of {email}', table=fields)

    provisions = get_account_provisions(account.id)
    if provisions:
        ctx.chat.send_table(title='Provisions', table=[
            {'Resource': RESOURCE_LABELS.get(p.resource, p.resource), 'Status': p.status,
             'Created': f"{p.created_at:%Y-%m-%d %H:%M}", 'Updated': f"{p.updated_at:%Y-%m-%d %H:%M}",
             'Data': json.dumps(p.data, ensure_ascii=False, default=str), 'Provision id': str(p.id)}
            for p in provisions])
    else:
        ctx.chat.send_text("No provisions.")

    history = get_provision_history(account.id)
    if history:
        ctx.chat.send_table(title='Status history', table=[
            {'When': f"{h['recorded_at']:%Y-%m-%d %H:%M}", 'Resource': RESOURCE_LABELS.get(h['resource'], h['resource']),
             'From': h['previous_status'] or '', 'To': h['status']}
            for h in history])


onboard.add_command(github.github_group)
for _alias_name in ('info', 'show', 'lookup'):
    _alias = copy.copy(onboard_whois)
    _alias.hidden = True
    onboard.add_command(_alias, _alias_name)
# Old top-level names, kept (hidden) for existing habits and scripts
for _old_name, _command in (('github_check', github.github_check), ('github_cancel', github.github_cancel)):
    _alias = copy.copy(_command)
    _alias.hidden = True
    onboard.add_command(_alias, _old_name)
if pathlib.Path('config/azdo.yml').exists():
    from commands.onboarding import azdo
    onboard.add_command(azdo.azdo)
    for _alias_name in ('devops', 'azuredevops'):
        _alias = copy.copy(azdo.azdo)
        _alias.hidden = True
        onboard.add_command(_alias, _alias_name)
    onboard.add_command(azdo.ado)
onboard.add_command(team.onboard_move)
onboard.add_command(crowd.onboard_crowd)
onboard.add_command(jetbrains.onboard_jetbrains)