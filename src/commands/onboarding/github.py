import os
import re

import click
import requests

from backend.account_storage import find_provisions_by_username, get_or_create_account, set_provision_status
from backend.approval import requires_approval
from backend.email_logging import send_email
from backend.github_api import GitHubApi
from backend.providers import Account as ProviderAccount, PROVIDERS, RESOURCE_LABELS
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _github_summary(params: dict) -> str:
    return f"onboard {params['username']} to GitHub team {params['team']}"


github_client: GitHubApi | None = None


def _send_invitation_email(ctx: ExtendedContext, username: str, email: str, team: str) -> str:
    """Email the invitee a bilingual note with the direct acceptance link.

    Never raises: the invitation was already sent, so a mail problem is only reported in the result text.
    """
    api = GitHubApi()
    if not api.send_invitation_email:
        return ''
    try:
        send_email(
            'github_invitation', to=email,
            subject='GitHub invitation / Πρόσκληση GitHub',
            bot_name=os.environ.get('BOT_NAME', 'Gyrobot').split()[0],
            username=username, team=team, expiry_days=api.invitation_expiry_days,
            invitation_url=f"https://github.com/enterprises/{api.enterprise}/member_invitation")
    except Exception as e:
        ctx.logger.warning(f"Could not send invitation email to {email}: {e!r}")
        return f" (invitation email to {email} FAILED: {e})"
    return f" (invitation email sent to {email})"

def _extract_email(email: str) -> str | None:
    if match := re.match(r'<mailto:(?P<email>[-._\w]+@(?:\w+\.?)*)\|\1>', email):
        return match.group('email')
    return None

def _github_validate(params: dict) -> str | None:
    # ensure GitHub username exists
    # ensure team is valid
    global github_client
    if github_client is None:
        github_client = GitHubApi()

    username = params['username']
    team = 'ent:' + params['team'].lower()

    try:
        user = github_client.get_user_details(username)
    except requests.exceptions.HTTPError as r:
        return f"User {username} not found.\n" + r.args[0]

    # Use the correct casing from the GitHub API response
    if 'login' in user:
        params['username'] = user['login']

    if existing := find_provisions_by_username('github', [params['username']]):
        current = existing[0]
        return (f"User {params['username']} is already onboarded to GitHub "
                f"(status: {current.status}, email: {current.data.get('email', 'unknown')}).")

    teams = github_client.get_ent_teams()
    if team not in [t['slug'] for t in teams]:
        raise RuntimeError(f"Team {team} not found.")

    email = params['email']
    if extracted_email := _extract_email(email):
        params['email'] = email = extracted_email

    if '@' in email:
        domain = email.split('@')[1]
        allowed_domains = github_client.allowed_email_domains
        if allowed_domains and domain not in allowed_domains:
            raise RuntimeError(f"Invalid Email Domain {domain}.")
        if domain in github_client.ad_check_email_domains:
            # check email with active directory
            pass

    return None


@click.command('github')
@click.argument('username')
@click.argument('email')
@click.argument('team')
@click.pass_context
@requires_approval(summarize=_github_summary, validate=_github_validate)
def onboard_github(ctx: ExtendedContext, username: str, email: str, team: str):
    """Onboard a colleague for GitHub Copilot.

    USAGE: bot onboard github <username> <email> <team>
    """
    provision_data = {'username': username, 'email': email, 'team': team}

    # For now, provision via the stub (using email for ProviderAccount)
    # In real integration, the provider will populate node_id, login, enterprise_user_id
    account_obj = ProviderAccount(name=email.split('@')[0], userid=username, email=email, team=team)
    message = PROVIDERS['github'].provision(ctx, account_obj)

    # Store account and provision status
    account = get_or_create_account(primary_email=email, name=username)
    set_provision_status(account.id, 'github', 'invited', provision_data)

    message += _send_invitation_email(ctx, username, email, team)

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
    results = GitHubApi().check_github_invitations()

    summary_lines = [
        f"Total pending: {results['total_pending']}",
        f"Accepted & assigned: {len(results['accepted_and_assigned'])}",
        f"Expired: {len(results['expired'])}",
        f"Failed: {len(results['failed'])}",
        f"Errors: {len(results['errors'])}",
    ]

    if results['accepted_and_assigned']:
        summary_lines.append(f"✓ Assigned: {', '.join(results['accepted_and_assigned'])}")

    if results['expired']:
        summary_lines.append(f"⌛ Expired: {', '.join(results['expired'])}")

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
