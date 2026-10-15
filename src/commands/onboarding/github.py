import datetime
import os
import re

import click
import requests

from backend import bot_identity
from backend.account_storage import (find_provisions_by_github_id, find_provisions_by_username,
                                     get_or_create_account, get_pending_provisions, set_provision_status)
from backend.accounts import Provision
from backend.approval import requires_approval
from backend.email_logging import send_email
from backend.github_api import GitHubApi
from backend.providers import ProvisionRequest, PROVIDERS, RESOURCE_LABELS
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
            bot_name=bot_identity.bot_name(),
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

    existing = find_provisions_by_username('github', [params['username']])
    if not existing and user.get('id'):
        # The account may have been onboarded under a previous username
        existing = find_provisions_by_github_id(user['id'])
    if existing:
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
    try:
        provision_data['github_id'] = GitHubApi().get_user_details(username)['id']
    except Exception as e:
        # Not fatal: scripts/backfill_github_ids.py can fill it in later
        ctx.logger.warning(f"Could not look up GitHub id of {username}: {e}")

    # For now, provision via the stub (using email for ProviderAccount)
    # In real integration, the provider will populate node_id, login, enterprise_user_id
    account_obj = ProvisionRequest(name=email.split('@')[0], userid=username, email=email, team=team)
    message = PROVIDERS['github'].provision(ctx, account_obj)

    provision_data.update(account_obj.provision_data)

    # Store account and provision status
    account = get_or_create_account(primary_email=email, name=username)
    set_provision_status(account.id, 'github', 'invited', provision_data)

    message += _send_invitation_email(ctx, username, email, team)

    result = [{'Resource': RESOURCE_LABELS['github'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {username}', table=result)
    return f"{RESOURCE_LABELS['github']}: {message}"


def _github_cancel_summary(params: dict) -> str:
    return f"cancel the GitHub invitation of {params['identifier']}"


def _resolve_cancellation(identifier: str) -> tuple[dict | None, Provision | None, str | None]:
    """Find what ``identifier`` (GitHub login, email or invitation id) refers to.

    Returns (pending GitHub invitation, invited provision in the database, error). Either of the first two may be
    missing (for example an invitation sent outside the bot, or one already withdrawn on GitHub).
    """
    wanted = (_extract_email(identifier) or identifier).strip()
    lowered = wanted.lower()
    api = GitHubApi()

    invitations = api.find_pending_invitations(wanted)
    provisions = [p for p in get_pending_provisions('github', 'invited')
                  if lowered in {str(p.data.get(key) or '').lower() for key in ('invitation_id', 'username', 'email')}]

    if len(provisions) > 1:
        names = ', '.join(p.data.get('username', '?') for p in provisions)
        return None, None, f"'{wanted}' matches several invitations ({names}); use the GitHub login or invitation id."
    provision = provisions[0] if provisions else None

    if provision and not invitations:
        # Found through the database only: look for the matching invitation on GitHub
        for key in (provision.data.get('invitation_id'), provision.data.get('username')):
            if key and (invitations := api.find_pending_invitations(key)):
                break
    if len(invitations) > 1:
        names = ', '.join((i.get('invitee') or {}).get('login') or i.get('email') or i['id'] for i in invitations)
        return None, None, f"'{wanted}' matches several invitations on GitHub ({names}); use the invitation id."
    invitation = invitations[0] if invitations else None

    if not invitation and not provision:
        return None, None, f"No pending GitHub invitation found for '{wanted}'."
    if not invitation:
        username = provision.data.get('username')
        if username and username in {u['login'] for u in api.get_ent_members()}:
            return None, None, (f"{username} has already accepted the invitation; "
                                f"use 'offboard {provision.data.get('email', '<email>')}' to remove access.")
    return invitation, provision, None


def _github_cancel_validate(params: dict) -> str | None:
    return _resolve_cancellation(params['identifier'])[2]


@click.command('github_cancel')
@click.argument('identifier')
@click.pass_context
@requires_approval(summarize=_github_cancel_summary, validate=_github_cancel_validate)
def github_cancel(ctx: ExtendedContext, identifier: str):
    """Cancel a pending GitHub invitation.

    IDENTIFIER is the GitHub login, the email address or the invitation id.

    USAGE: bot onboard github_cancel <login|email|invitation_id>
    """
    invitation, provision, error = _resolve_cancellation(identifier)
    if error:
        ctx.chat.send_text(error, is_error=True)
        return f"Error: {error}"

    lines = []
    if invitation:
        lines.append(f"GitHub: {GitHubApi().cancel_invitation(invitation['id'])}")
    else:
        lines.append("GitHub: no pending invitation (already withdrawn or expired)")
    if provision:
        provision.data['cancelled_at'] = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        provision.data['cancelled_by'] = ctx.chat.user_id
        set_provision_status(provision.account_id, 'github', 'cancelled', provision.data)
        lines.append(f"Database: provision of {provision.data.get('username')} marked as cancelled")
    else:
        lines.append("Database: no matching provision (invitation was not sent by the bot)")

    message = '\n'.join(lines)
    ctx.chat.send_text(message)
    return message


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
