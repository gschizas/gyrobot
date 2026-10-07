"""Discord chat platform (skeleton), selected with ``DISCORD_API_TOKEN``.

Built on ``discord.py``. The client runs its own asyncio loop (blocking in
:func:`chat_connect`), while commands run in worker threads, so all outgoing
calls go through :func:`_run`, which schedules the coroutine on the client loop.
Never call :func:`_run` from the loop thread itself (it would deadlock).

Requires the *Message Content* privileged intent to be enabled for the bot.
Channel ids are Discord snowflakes, kept as strings; ``team_id`` is the guild id.

Not implemented yet: see ``TODO.md``.
"""
import asyncio
import datetime
import io
import logging
import os
from typing import Dict, List

import discord
from tabulate import tabulate

from backend.constants import TableFormat
from chat.chat_wrapper import Conversation, Message

MAX_MESSAGE_LENGTH = 2000

bot_name: str
handle_message: callable
logger: logging.Logger = logging.getLogger(__name__)
_client: discord.Client | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _run(coro, timeout: float = 30):
    if _loop is None:
        raise RuntimeError("Discord client is not connected yet")
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


def _chunks(text: str, size: int = MAX_MESSAGE_LENGTH):
    for start in range(0, len(text), size):
        yield text[start:start + size]


async def _get_channel(channel_id: str):
    channel_id = int(channel_id)
    return _client.get_channel(channel_id) or await _client.fetch_channel(channel_id)


async def _send(channel_id: str, text: str = None, **kwargs) -> None:
    channel = await _get_channel(channel_id)
    if text is None:
        await channel.send(**kwargs)
        return
    parts = list(_chunks(text))
    for index, part in enumerate(parts):
        await channel.send(part, **(kwargs if index == len(parts) - 1 else {}))


def _code_block(text: str) -> str:
    return f"```\n{text}\n```"


class DiscordConversation(Conversation):
    @property
    def channel_name(self) -> str | None:
        channel = _client.get_channel(int(self.channel_id)) if _client else None
        if isinstance(channel, discord.DMChannel):
            recipient = channel.recipient
            return f"🧑{recipient.display_name} <{recipient.name}@{recipient.id}>" if recipient else '🧑'
        if channel is None:
            return None
        permissions = channel.permissions_for(channel.guild.default_role)
        return ('#' if permissions.view_channel else '🔒') + channel.name

    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        if is_error:
            text = f":face_palm: {text}"
        _run(_send(channel or self.channel_id, text))

    def send_table(self, title: str, table: List[Dict], table_format: TableFormat = TableFormat.TABLE) -> None:
        # TODO: Excel / file output according to table_format
        if not table:
            self.send_text(f"**{title}**\n(no rows)")
            return
        _run(_send(self.channel_id, f"**{title}**"))
        # leave room for the code fence in each chunk
        for part in _chunks(tabulate(table, headers='keys', tablefmt='simple'), MAX_MESSAGE_LENGTH - 10):
            _run(_send(self.channel_id, _code_block(part)))

    def send_tables(self, title: str, tables: Dict[str, List[Dict]],
                    table_format: TableFormat = TableFormat.TABLE) -> None:
        for table_title, table in tables.items():
            self.send_table(f"{title} - {table_title}", table, table_format)

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        # Discord has no ephemeral messages outside slash-command interactions: DM the user instead.
        async def dm():
            user = await _client.fetch_user(int(self.user_id))
            await user.send(text or '')

        _run(dm())

    def send_file(self, file_data, title=None, filename=None, channel=None):
        _run(_send(channel or self.channel_id, title,
                   file=discord.File(io.BytesIO(file_data), filename=filename or 'file.txt')))

    def send_fields(self, text, fields):
        embeds = [discord.Embed(description=field.get('text', ''),
                                colour=discord.Colour.from_str(field['color']) if field.get('color')
                                else discord.Colour.default())
                  for field in fields]
        # Discord allows up to 10 embeds per message
        for start in range(0, len(embeds), 10):
            _run(_send(self.channel_id, text if start == 0 else None, embeds=embeds[start:start + 10]))

    def send_blocks(self, blocks):
        raise NotImplementedError("Slack blocks have no Discord equivalent yet")

    def get_user_info(self, user_id) -> Dict:
        async def fetch():
            user = _client.get_user(int(user_id)) or await _client.fetch_user(int(user_id))
            return {'id': str(user.id), 'name': user.name, 'real_name': user.display_name}

        return _run(fetch())

    def get_team_info(self) -> Dict:
        guild = _client.get_guild(int(self.team_id)) if self.team_id else None
        return {'id': self.team_id, 'name': guild.name if guild else 'Discord'}


class _BotClient(discord.Client):
    async def setup_hook(self):
        global _loop
        _loop = asyncio.get_running_loop()

    async def on_ready(self):
        logger.info(f"Connected to Discord as {self.user}")

    async def on_message(self, message: discord.Message):
        if message.author == self.user or message.author.bot:
            return
        conversation = DiscordConversation(
            bot_name, str(message.channel.id), str(message.author.id), str(message.guild.id) if message.guild else '')
        timestamp = message.created_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        handle_message(Message(conversation, timestamp, message.jump_url, message.content))


def chat_connect(a_bot_name, a_line_handler):
    global bot_name, _client
    bot_name = a_bot_name
    intents = discord.Intents.default()
    intents.message_content = True
    _client = _BotClient(intents=intents)
    _client.run(os.environ['DISCORD_API_TOKEN'])
