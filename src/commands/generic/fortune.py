import os
import subprocess

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('fortune')
@click.pass_context
def fortune(ctx: ExtendedContext):
    """Like a Chinese fortune cookie, but less yummy"""
    ctx.chat.send_text(subprocess.check_output(['/usr/games/fortune']).decode())


@gyrobot.command('joke')
@click.option('-x', '--extended', 'extended', is_flag=True, default=False)
@click.pass_context
def joke(ctx: ExtendedContext, extended):
    """Tell a joke"""
    proxies = {'http': os.environ['ALT_PROXY'], 'https': os.environ['ALT_PROXY']} if 'ALT_PROXY' in os.environ else {}
    joke_page = requests.get(
        'https://icanhazdadjoke.com/',
        headers={
            'Accept': 'application/json',
            'User-Agent': 'Slack Bot for Reddit (https://github.com/gschizas/slack-bot)'},
        proxies=proxies)
    joke_obj = joke_page.json()
    if extended:
        blocks = [
            {
                "type": "markdown",
                "text": f"[{joke_obj['joke']}](https://icanhazdadjoke.com/j/{joke_obj['id']})"
            }
        ]
        ctx.chat.send_blocks(blocks)
    else:
        ctx.chat.send_text(joke_obj['joke'])
