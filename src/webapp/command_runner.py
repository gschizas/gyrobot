"""Drives ``commands.gyrobot`` (the same Click command tree chat messages use)
programmatically, using a :class:`~webapp.chat_adapter.HeadlessConversation`
in place of a real chat conversation.

This is intentionally the same mechanism ``src/__main__.py``'s ``run_command``
uses for chat-triggered commands (``click.testing.CliRunner.invoke``), so
permission checks, the approval queue, and command behaviour are identical
regardless of whether the command came from chat, the Web UI, or the REST API.
"""
import dataclasses
import datetime
import logging
from typing import List, Optional

import click.testing

import commands  # noqa: F401 - ensures commands.gyrobot exists
from chat.chat_wrapper import Message
from webapp.bootstrap import ensure_commands_imported
from webapp.chat_adapter import HeadlessConversation

logger = logging.getLogger('webapp.command_runner')

_runner = click.testing.CliRunner()


@dataclasses.dataclass
class CommandRunResult:
    success: bool
    exit_code: int
    output: str
    messages: List[dict]
    error: Optional[str] = None


def run_bot_command(args: List[str], *, user_id: str, channel_name: str, team_name: str,
                    bot_name: str = 'bot') -> CommandRunResult:
    """Invoke ``commands.gyrobot`` with ``args`` (e.g. ``['onboard', 'github', ...]``)
    as if it had been typed in chat by ``user_id`` in ``channel_name``.

    ``ensure_commands_imported`` is called first so this also works if the
    caller (e.g. a test) imports this module before the FastAPI app has
    initialized.
    """
    ensure_commands_imported()

    conversation = HeadlessConversation(
        bot_name=bot_name, user_id=user_id, channel_name=channel_name, team_name=team_name)
    message = Message(conversation=conversation, timestamp=datetime.datetime.now(datetime.timezone.utc),
                      permalink='', text=' '.join(args))
    context_obj = {
        'chat_wrapper': None,
        'logger': logger,
        'subreddit': None,
        'reddit_session': None,
        'bot_reddit_session': None,
        'message': message,
    }

    result = _runner.invoke(commands.gyrobot, args=args, obj=context_obj, catch_exceptions=True)

    return CommandRunResult(
        success=result.exit_code == 0 and result.exception is None,
        exit_code=result.exit_code,
        output=result.output,
        messages=conversation.messages,
        error=repr(result.exception) if result.exception else None,
    )
