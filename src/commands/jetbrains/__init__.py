import os

import click

from backend.jetbrains_api import JetBrainsApi

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext

if 'JETBRAINS_TOKEN' not in os.environ:
    raise ImportError('JETBRAINS_TOKEN not found in environment')

if 'JETBRAINS_CUSTOMER_CODE' not in os.environ:
    raise ImportError('JETBRAINS_CUSTOMER_CODE not found in environment')


@gyrobot.group('jetbrains', cls=DefaultCommandGroup)
def jetbrains():
    pass


@jetbrains.command('teams')
@click.pass_context
def jetbrains_teams(ctx: ExtendedContext):
    """Display JetBrains Teams"""
    teams = JetBrainsApi().get_teams()
    ctx.chat.send_table(title='JetBrains Teams', table=[
        {'Team ID': team.id, 'Team Name': team.name, 'Team Slug': team.slug}
        for team in teams])
