PLUGIN = {'requires': ['JETBRAINS_TOKEN', 'JETBRAINS_CUSTOMER_CODE']}

import os

import click

from backend.constants import TableFormat
from backend.jetbrains_api import JetBrainsApi
from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext

if 'JETBRAINS_TOKEN' not in os.environ:
    raise ImportError('JETBRAINS_TOKEN not found in environment')

if 'JETBRAINS_CUSTOMER_CODE' not in os.environ:
    raise ImportError('JETBRAINS_CUSTOMER_CODE not found in environment')


@gyrobot.group('jetbrains', cls=DefaultCommandGroup)
def jetbrains():
    """Inspect JetBrains licence teams and their holders (there are no invitations).

    To onboard someone use "onboard jetbrains" instead.
    """


@jetbrains.command('teams')
@click.pass_context
def jetbrains_teams(ctx: ExtendedContext):
    """Display JetBrains Teams"""
    teams = JetBrainsApi().get_teams()
    ctx.chat.send_table(title='JetBrains Teams', table=[{
        'Team ID': team.id,
        'Team Name': team.name,
        'Team Slug': team.slug}
        for team in teams])
        #'Total Licenses': team.total_licenses,
        #'Free Licenses': team.unassigned_licenses}


@jetbrains.command('members')
@click.argument('team', required=False)
@click.option('-x', '--excel', 'as_excel', is_flag=True, help='Send the result as an Excel file')
@click.pass_context
def jetbrains_members(ctx: ExtendedContext, team: str | None, as_excel: bool):
    """Display the licences (assigned and free) of a JetBrains team, or of all teams without TEAM.

    TEAM is a JetBrains team name, slug or id.
    """
    api = JetBrainsApi()
    try:
        if team:
            team_id = api.find_team(team).id
            licenses = api.get_team_licenses(team_id)
        else:
            licenses = api.get_all_licenses()
    except ValueError as e:
        ctx.chat.send_text(str(e), is_error=True)
        return

    if not licenses:
        ctx.chat.send_text("No licences found.")
        return

    table = []
    for lic in licenses:
        assignee = lic.get('assignee') or {}
        if lic.get('isAvailableToAssign') and not assignee:
            status = 'free'
        else:
            status = 'suspended' if lic.get('isSuspended') else 'assigned'
        # Licences may also be held by a licence server or key rather than a person
        holder = assignee.get('email') or assignee.get('registrationName') or assignee.get('uid') or ''
        table.append({'Team': (lic.get('team') or {}).get('name', ''), 'Status': status, 'Email': holder,
                      'Name': assignee.get('name', ''), 'Licence': lic.get('licenseId', ''),
                      'Valid until': ((lic.get('subscription') or {}).get('validUntilDate') or '')[:10]})
    table.sort(key=lambda row: (row['Team'].lower(), row['Status'] != 'assigned', row['Email'].lower()))

    title = f'JetBrains licences of {team}' if team else 'JetBrains licences'
    ctx.chat.send_table(title=title, table=table,
                        table_format=TableFormat.EXCEL if as_excel else TableFormat.TABLE)
