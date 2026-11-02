import datetime

import click
import requests
from treelib import Tree

from backend import bot_identity
from backend.account_storage import (find_provisions_by_any_username, find_provisions_by_github_id,
                                     find_provisions_by_username, get_last_status_times, get_or_create_account, get_pending_provisions,
                                     get_provisions, set_provision_status)
from backend.accounts import Provision
from backend.approval import requires_approval
from backend.arguments import extract_email
from backend.constants import TableFormat
from backend.email_domains import domain_in, is_allowed_email
from backend.email_logging import send_email
from backend.github_api import GitHubApi
from backend.providers import ProvisionRequest, PROVIDERS, RESOURCE_LABELS
from commands import DefaultCommandGroup
from commands.extended_context import ExtendedContext
from commands.team_columns import team_level_columns


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

def _github_validate(params: dict, ctx: ExtendedContext) -> str | None:
    # ensure GitHub username exists
    # ensure team is valid
    global github_client
    if github_client is None:
        github_client = GitHubApi()

    username = params['username']
    params['team'] = params['team'].strip().lower().removeprefix('ent:')
    team = 'ent:' + params['team']

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
    if extracted_email := extract_email(ctx, email):
        params['email'] = email = extracted_email

    if '@' in email:
        domain = email.split('@')[1]
        if not is_allowed_email(email, github_client.allowed_email_domains):
            raise RuntimeError(f"Invalid Email Domain {domain}.")
        if domain_in(email, github_client.ad_check_email_domains):
            # check email with active directory
            pass

    return None


@click.group('github', cls=DefaultCommandGroup)
def github_group():
    """Onboard a colleague for GitHub Copilot, check/cancel invitations, and inspect the GitHub enterprise.

    Without a subcommand this is "add": bot onboard github <username> <email> <team>

    Read-only lookups (not gated by approval): teams, members, pending-invitations, expired.
    """


@github_group.command('teams')
@click.argument('team_prefix', required=False)
@click.option('-f', '--flat', is_flag=True, help='List the real teams (slugs) as a flat list, not a tree')
@click.pass_context
def github_teams(ctx: ExtendedContext, team_prefix: str | None, flat: bool):
    """Display the GitHub enterprise teams as a tree, optionally only those starting with TEAM_PREFIX.

    The parents of matching teams are shown too, to keep the tree readable.
    With --flat, only the real teams are listed, sorted, one slug per line.
    """

    def generate_tree(node_name, parent_node=None):
        # Check if this node is a leaf (has no children)
        is_leaf = node_name not in connections or len(connections[node_name]) == 0

        # Use different display based on whether it's a leaf
        display_name = f"📄 {node_name}" if is_leaf else f"📁 {node_name}"

        parent = tree.create_node(display_name, node_name.lower(), parent=parent_node)
        for branch_name in sorted(connections.get(node_name, []), key=lambda x: x.lower()):
            generate_tree(branch_name, parent)

    teams = GitHubApi().get_ent_teams()
    if team_prefix:
        prefix = team_prefix.lower().removeprefix('ent:')
        teams = [t for t in teams if t['slug'].lower().removeprefix('ent:').startswith(prefix)]
        if not teams:
            ctx.chat.send_text(f"No teams found starting with {team_prefix}.")
            return
    if flat:
        slugs = (t['slug'].removeprefix('ent:') for t in teams)
        ctx.chat.send_code('\n'.join(sorted(slugs, key=str.lower)))
        return
    connections, root_item, _slug_set = GitHubApi().build_team_connections(teams)

    tree = Tree()
    generate_tree(root_item)
    text = tree.show(key=lambda x: x.identifier, line_type='ascii-ex', stdout=False)

    ctx.chat.send_code(text)


@github_group.command("members")
@click.argument("team_slug")
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def github_team_members(ctx: ExtendedContext, team_slug: str, as_excel: bool):
    """Display members (login, email, team) of enterprise teams whose slug starts with TEAM_SLUG"""
    members = GitHubApi().get_ent_team_members_by_prefix(team_slug)

    if not members:
        ctx.chat.send_text(f"No members found for teams starting with {team_slug}.")
        return

    # Fall back to the email recorded when the bot onboarded the user
    missing = {m['login'] for m in members if not m['emails']}
    fallback: dict[str, str] = {}
    if missing:
        try:
            # Ordered by creation, so the most recent provision wins
            for provision in find_provisions_by_username('github', list(missing)):
                email = provision.data.get('email')
                if email:
                    fallback[provision.data['username'].lower()] = email
        except Exception:
            ctx.logger.warning('Could not look up fallback emails in the database', exc_info=True)

    table = []
    for m in sorted(members, key=lambda m: (m['team'], m['login'].lower())):
        if m['emails']:
            email, source = ', '.join(m['emails']), 'github'
        elif m['login'].lower() in fallback:
            email, source = fallback[m['login'].lower()], bot_identity.bot_name()
        else:
            email, source = '', ''
        table.append({'Username': m['login'], 'Email': email, 'Email source': source, 'Team': m['team']})
    ctx.chat.send_table(title=f'Members of teams starting with {team_slug}', table=table,
                        table_format=TableFormat.EXCEL if as_excel else TableFormat.TABLE,
                        formula_columns=team_level_columns)


@github_group.command("pending-invitations")
@click.argument("team_prefix", required=False)
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def github_pending_invitations(ctx: ExtendedContext, team_prefix: str | None, as_excel: bool):
    """Display pending invitations, optionally only for teams starting with TEAM_PREFIX"""
    invitations = GitHubApi().get_pending_invitations()

    if not invitations:
        ctx.chat.send_text("No pending invitations found.")
        return

    usernames = [invite['login'] for invite in invitations]

    db_rows = find_provisions_by_any_username(usernames)

    users_by_username = {p.data['username']: p for p in db_rows}
    for inv in invitations:
        user = users_by_username.get(inv['login'])
        if not user:
            continue
        inv['email'] = user.data['email']
        inv['team'] = user.data['team']

    if team_prefix:
        prefix = team_prefix.lower().removeprefix('ent:')
        # Only invitations made through the bot have a team on record
        invitations = [inv for inv in invitations if inv.get('team', '').lower().removeprefix('ent:').startswith(prefix)]
        if not invitations:
            ctx.chat.send_text(f"No pending invitations found for teams starting with {team_prefix}.")
            return

    title = 'Pending Invitations' + (f' (teams starting with {team_prefix})' if team_prefix else '')
    ctx.chat.send_table(title=title, table=invitations,
                        table_format=TableFormat.EXCEL if as_excel else TableFormat.TABLE,
                        formula_columns=team_level_columns)


@github_group.command('add', default_command=True)
@click.argument('username')
@click.argument('email')
@click.argument('team')
@click.pass_context
@requires_approval(summarize=_github_summary, validate=_github_validate)
def onboard_github(ctx: ExtendedContext, username: str, email: str, team: str):
    """Onboard a colleague for GitHub Copilot.

    USAGE: bot onboard github [add] <username> <email> <team>
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
    account = get_or_create_account(primary_email=email, name=username, team=team)
    set_provision_status(account.id, 'github', 'invited', provision_data)

    message += _send_invitation_email(ctx, username, email, team)

    result = [{'Resource': RESOURCE_LABELS['github'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {username}', table=result)
    return f"{RESOURCE_LABELS['github']}: {message}"


def _github_cancel_summary(params: dict) -> str:
    return f"cancel the GitHub invitation of {params['identifier']}"


def _resolve_cancellation(ctx: ExtendedContext, identifier: str) -> tuple[dict | None, Provision | None, str | None]:
    """Find what ``identifier`` (GitHub login, email or invitation id) refers to.

    Returns (pending GitHub invitation, invited provision in the database, error). Either of the first two may be
    missing (for example an invitation sent outside the bot, or one already withdrawn on GitHub).
    """
    wanted = (extract_email(ctx, identifier) or identifier).strip()
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


def _github_cancel_validate(params: dict, ctx: ExtendedContext) -> str | None:
    return _resolve_cancellation(ctx, params['identifier'])[2]


@github_group.command('cancel')
@click.argument('identifier')
@click.pass_context
@requires_approval(summarize=_github_cancel_summary, validate=_github_cancel_validate)
def github_cancel(ctx: ExtendedContext, identifier: str):
    """Cancel a pending GitHub invitation.

    IDENTIFIER is the GitHub login, the email address or the invitation id.

    USAGE: bot onboard github cancel <login|email|invitation_id>
    """
    invitation, provision, error = _resolve_cancellation(ctx, identifier)
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


@github_group.command('check')
@click.pass_context
def github_check(ctx: ExtendedContext):
    """Manually check pending GitHub invitations and auto-assign accepted users.

    This checks all pending GitHub provisioning invitations and attempts to assign
    users to their teams if their invitations have been accepted.

    USAGE: bot onboard github check
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


@github_group.command('expired')
@click.argument('team_prefix', required=False)
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def github_expired(ctx: ExtendedContext, team_prefix: str | None, as_excel: bool):
    """List GitHub invitations that expired without being accepted.

    Expired invitations no longer exist on GitHub, so they come from the bot's database.
    Optionally only for teams starting with TEAM_PREFIX.

    USAGE: bot onboard github expired [team_prefix] [-x]
    """
    prefix = team_prefix.lower().removeprefix('ent:') if team_prefix else ''
    invited_at = get_last_status_times('github', 'invited')
    expired_at = get_last_status_times('github', 'expired')

    def local_time(moment: datetime.datetime | None):
        # Excel has no time zones: use the server's local time, and real datetimes so that Excel sorts them as such
        if moment is None:
            return None
        moment = moment.astimezone().replace(tzinfo=None, microsecond=0)
        return moment if as_excel else moment.strftime('%Y-%m-%d %H:%M')

    table = []
    for provision in get_provisions('github'):
        data = provision.data
        team = data.get('team', '')
        if provision.status != 'expired' or not team.lower().removeprefix('ent:').startswith(prefix):
            continue
        # History first; accounts imported without history fall back to what the provision itself recorded
        stored_expiry = data.get('expired_at')
        table.append({'Username': data.get('username', ''), 'Email': data.get('email', ''), 'Team': team,
                      'Invited': local_time(invited_at.get(provision.account_id) or provision.created_at),
                      'Expired': local_time(expired_at.get(provision.account_id) or
                                            (datetime.datetime.fromisoformat(stored_expiry) if stored_expiry else None)),
                      '_sort': expired_at.get(provision.account_id)
                               or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)})

    if not table:
        suffix = f' for teams starting with {team_prefix}' if team_prefix else ''
        ctx.chat.send_text(f"No expired invitations found{suffix}.")
        return

    table.sort(key=lambda row: row['_sort'], reverse=True)
    for row in table:
        del row['_sort']
    title = 'Expired Invitations' + (f' (teams starting with {team_prefix})' if team_prefix else '')
    ctx.chat.send_table(title=title, table=table,
                        table_format=TableFormat.EXCEL if as_excel else TableFormat.TABLE,
                        formula_columns=team_level_columns)
