"""Azure DevOps reporting: how many users each canonical team has, and at which access level.

Users come from Entra ID, so there is nothing to onboard or offboard; the commands only read Azure DevOps
(see ``backend.azdo_api``), match people to accounts by email and keep a snapshot of each person's access level
(``backend.azdo_sync``). See docs/AZURE_DEVOPS.md.
"""
PLUGIN = {'requires_files': ['config/azdo.yml']}

import os
from collections import Counter

import click

from backend.account_storage import add_additional_email, find_account_by_any_email, get_provision_history
from backend.approval import requires_approval
from backend.arguments import extract_email
from backend.azdo_api import AzdoApi
from backend.azdo_sync import NO_TEAM, UNKNOWN_TEAM, sync_members
from backend.constants import TableFormat
from backend.team_mapping import normalize
from commands import gyrobot, ClickAliasedGroup
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

ADO_MESSAGE = """\
*ADO* stands for *ActiveX Data Object*, Microsoft's data-access library from 1996. It is what let VBScript and \
Classic ASP pages talk to a database: you `Server.CreateObject("ADODB.Connection")`, open a `Recordset`, loop with \
`Do While Not rs.EOF`, and pray that every error was swallowed by `On Error Resume Next`. It brought the world \
`Connection`, `Command` and `Recordset` objects, string-concatenated SQL, and a generation of SQL injection holes \
that are probably still running on a server in a cupboard somewhere.

It was replaced by *ADO.NET* in 2002, which shares nothing with ADO except three letters and the trauma, and then \
by everything else. Please do not confuse it with Azure DevOps, which is a different product with a different \
(and, one hopes, lower) body count.

If you meant Azure DevOps, the command is `azdo` (or `devops`). Try `azdo report`."""


@gyrobot.command('ado', context_settings={'ignore_unknown_options': True})
@click.argument('ignored', nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ado(ctx: ExtendedContext, ignored: tuple):
    """Not what you think. Use azdo for Azure DevOps."""
    ctx.chat.send_text(ADO_MESSAGE)


@gyrobot.group('azdo', cls=ClickAliasedGroup, aliases=['devops', 'azuredevops'])
@click.pass_context
def azdo(ctx: ExtendedContext):
    """Report on Azure DevOps users per canonical team and access level (read-only, except "link")"""
    ctx.ensure_object(dict)


def _members(ctx: ExtendedContext, max_age: float = 300) -> list[dict] | None:
    try:
        return sync_members(max_age)
    except Exception as ex:
        ctx.logger.exception("Could not read Azure DevOps")
        ctx.chat.send_text(f"Could not read Azure DevOps: {ex}", is_error=True)
        return None


def _format(as_excel: bool) -> TableFormat:
    return TableFormat.EXCEL if as_excel else TableFormat.TABLE


def _team_order(team: str) -> tuple:
    return team in (UNKNOWN_TEAM, NO_TEAM), team == UNKNOWN_TEAM, team.lower()


@azdo.command('report')
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def azdo_report(ctx: ExtendedContext, as_excel: bool):
    """Users per canonical team and access level, with the monthly cost if config/azdo.yml has prices.

    Users whose email matches no account are counted under "unknown" and listed separately;
    attach them to a person with "azdo link". Also records each person's access level for the history.

    USAGE: bot azdo report [-x]
    """
    members = _members(ctx)
    if members is None:
        return
    costs = AzdoApi().costs

    levels = sorted({m['access_level'] for m in members},
                    key=lambda level: (-costs.get(level.lower(), 0), level.lower()))
    per_team: dict[str, Counter] = {}
    for member in members:
        per_team.setdefault(member['team'], Counter())[member['access_level']] += 1

    def row(label: str, counts: Counter) -> dict:
        result = {'Team': label, **{level: counts[level] for level in levels}, 'Total': sum(counts.values())}
        if costs:
            result['Cost/month'] = round(sum(n * costs.get(level.lower(), 0) for level, n in counts.items()), 2)
        return result

    table = [row(team, per_team[team]) for team in sorted(per_team, key=_team_order)]
    table.append(row('TOTAL', sum(per_team.values(), Counter())))

    unknown = [{'Email': m['email'], 'Name': m['name'], 'Access level': m['access_level'], 'Status': m['status'],
                'Last accessed': m['last_accessed'] or 'never'}
               for m in sorted(members, key=lambda m: m['email']) if m['team'] == UNKNOWN_TEAM]

    title = 'Azure DevOps users per canonical team'
    notes = []
    if costs:
        unpriced = [level for level in levels if level.lower() not in costs]
        if unpriced:
            notes.append(f"No price is configured for: {', '.join(unpriced)} (counted as 0).")
    if unknown:
        notes.append("Attach unknown users to a person with `azdo link <azdo email> <account email>`.")

    if as_excel:
        ctx.chat.send_tables(title, {'Report': table, **({'Unknown users': unknown} if unknown else {})},
                             table_format=TableFormat.EXCEL)
    else:
        ctx.chat.send_table(title, table)
        if unknown:
            ctx.chat.send_table('Azure DevOps users matching no account', unknown)
    if notes:
        ctx.chat.send_text('\n'.join(notes))


@azdo.command('users')
@click.argument('team', required=False)
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def azdo_users(ctx: ExtendedContext, team: str | None, as_excel: bool):
    """List the Azure DevOps users of the canonical teams starting with TEAM, or of all teams.

    TEAM may be "unknown" for users matching no account.

    USAGE: bot azdo users [team] [-x]
    """
    members = _members(ctx)
    if members is None:
        return
    prefix = normalize(team) if team else ''
    selected = [m for m in members if m['team'].lower().startswith(prefix)]
    if not selected:
        ctx.chat.send_text("No Azure DevOps users found.")
        return
    selected.sort(key=lambda m: (_team_order(m['team']), m['email']))
    ctx.chat.send_table(
        title=f'Azure DevOps users of teams starting with {prefix}' if prefix else 'Azure DevOps users',
        table=[{'Email': m['email'], 'Name': m['name'], 'Team': m['team'], 'Access level': m['access_level'],
                'Licensing source': m['licensing_source'], 'Status': m['status'],
                'Last accessed': m['last_accessed'] or 'never'} for m in selected],
        table_format=_format(as_excel))


@azdo.command('whois')
@click.argument('email')
@click.pass_context
def azdo_whois(ctx: ExtendedContext, email: str):
    """Show a person's Azure DevOps access level and how it changed over time.

    EMAIL is the Azure DevOps email, or the primary or an additional email of the person's account.

    USAGE: bot azdo whois <email>
    """
    email = extract_email(ctx, email) or email.strip()
    members = _members(ctx)
    if members is None:
        return

    account = find_account_by_any_email(email)
    wanted = {email.lower()}
    if account:
        wanted |= {e.lower() for e in (account.primary_email, *account.metadata.get('additional_emails', [])) if e}
    member = next((m for m in members if {m['email'], m['principal_name']} & wanted), None)
    if member is None:
        ctx.chat.send_text(f"{email} is not in Azure DevOps.", is_error=True)
        return

    ctx.chat.send_table(f"Azure DevOps access of {email}", [
        {'Field': 'Name', 'Value': member['name']},
        {'Field': 'Email', 'Value': member['email']},
        {'Field': 'Principal name', 'Value': member['principal_name']},
        {'Field': 'Account', 'Value': account.primary_email if account else '(no account has this email)'},
        {'Field': 'Canonical team', 'Value': member['team']},
        {'Field': 'Access level', 'Value': member['access_level']},
        {'Field': 'Licence type', 'Value': member['license_type']},
        {'Field': 'Licensing source', 'Value': member['licensing_source']},
        {'Field': 'Assignment source', 'Value': member['assignment_source']},
        {'Field': 'Status', 'Value': member['status']},
        {'Field': 'Last accessed', 'Value': member['last_accessed'] or 'never'},
    ])
    if not account:
        ctx.chat.send_text("Attach this user to a person with `azdo link`.")
        return

    changes, last = [], None
    for entry in get_provision_history(account.id, 'azdo'):
        state = (entry['status'], (entry['data'] or {}).get('access_level'))
        if state != last:
            changes.append({'When': f"{entry['recorded_at']:%Y-%m-%d %H:%M}", 'Status': state[0],
                            'Access level': state[1] or ''})
            last = state
    if changes:
        ctx.chat.send_table('Access level history', changes)


def _link_summary(params: dict) -> str:
    return f"record {params['azdo_email']} as an additional email of {params['account_email']} (Azure DevOps)"


def _link_validate(params: dict, ctx: ExtendedContext) -> str | None:
    azdo_email = extract_email(ctx, params['azdo_email'])
    account_email = extract_email(ctx, params['account_email'])
    if not azdo_email:
        return f"'{params['azdo_email']}' is not a valid email address."
    if not account_email:
        return f"'{params['account_email']}' is not a valid email address."

    if owner := find_account_by_any_email(azdo_email):
        return f"{azdo_email} already belongs to the account of {owner.primary_email}."
    account = find_account_by_any_email(account_email)
    if not account:
        return f"No account found for {account_email}."
    try:
        members = AzdoApi().get_members()
    except Exception as ex:
        return f"Could not read Azure DevOps: {ex}"
    if not any(azdo_email.lower() in (m['email'], m['principal_name']) for m in members):
        return f"{azdo_email} is not an Azure DevOps user."

    params['azdo_email'] = azdo_email.lower()
    params['account_email'] = account.primary_email  # stored, so the approver sees the real account
    return None


@azdo.command('link')
@click.argument('azdo_email')
@click.argument('account_email')
@click.pass_context
@requires_approval(summarize=_link_summary, validate=_link_validate)
def azdo_link(ctx: ExtendedContext, azdo_email: str, account_email: str):
    """Attach an Azure DevOps user that matches no account to a person, as an additional email.

    AZDO_EMAIL is the user's email in Azure DevOps (see "unknown" in "azdo report"); ACCOUNT_EMAIL is the
    primary or an additional email of the person. Queued for approval.

    USAGE: bot azdo link <azdo_email> <account_email>
    """
    account = find_account_by_any_email(account_email)
    if not account:
        return f"Error: No account found for {account_email}"
    add_additional_email(account.id, azdo_email)
    sync_members(max_age=0)  # records the person's access level right away
    message = f"{azdo_email} is now an additional email of {account.primary_email}"
    ctx.chat.send_text(message)
    return message
