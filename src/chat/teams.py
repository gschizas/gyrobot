"""Microsoft Teams chat platform (skeleton), selected with ``TEAMS_APP_ID``.

Unlike the other platforms, Teams does not let a bot connect out: Azure Bot
Service POSTs activities to a public HTTPS endpoint. :func:`chat_connect` starts
an ``aiohttp`` server (``POST /api/messages`` on ``TEAMS_PORT``, default 3978)
that must be reachable from the Bot Service (reverse proxy / tunnel).

Environment: ``TEAMS_APP_ID``, ``TEAMS_APP_PASSWORD``, optional ``TEAMS_APP_TENANT_ID``
and ``TEAMS_APP_TYPE`` (``MultiTenant`` default, ``SingleTenant``, ``UserAssignedMSI``).

Commands run in worker threads, so outgoing calls are scheduled on the server's
event loop through :func:`_run` (never call it from the loop thread itself).
Proactive messages need a ``ConversationReference``: they are remembered from
incoming messages and persisted in ``data/teams_conversations-<LOG_NAME>.yml``, so a
notification channel only needs to have been addressed (e.g. by ``@mention``) once.
``channel_id`` is the Teams conversation id.

Not implemented yet: see ``TODO.md``.
"""
import asyncio
import logging
import os
from typing import Dict, List

from aiohttp import web
from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.schema import ConversationReference
from tabulate import tabulate

from backend.constants import TableFormat
from chat.chat_wrapper import Conversation, Message
from state_file import state_file

bot_name: str
handle_message: callable
logger: logging.Logger = logging.getLogger(__name__)
_loop: asyncio.AbstractEventLoop | None = None

channels_cache: dict = {}  # conversation id -> display name
teams_cache: dict = {}  # team id -> team info
users_cache: dict = {}  # user id -> user info
_references: dict = {}  # conversation id -> serialized ConversationReference
_REFERENCES_STATE = 'teams_conversations'


class _Config:
    APP_ID = os.environ.get('TEAMS_APP_ID', '')
    APP_PASSWORD = os.environ.get('TEAMS_APP_PASSWORD', '')
    APP_TYPE = os.environ.get('TEAMS_APP_TYPE', 'MultiTenant')
    APP_TENANTID = os.environ.get('TEAMS_APP_TENANT_ID', '')


adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(_Config()))


def _run(coro, timeout: float = 30):
    if _loop is None:
        raise RuntimeError("Teams server is not running yet")
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=timeout)


def _load_references() -> None:
    with state_file(_REFERENCES_STATE) as data:
        _references.update(data)


def _remember_reference(conversation_id: str, reference: ConversationReference) -> None:
    serialized = reference.serialize()
    if _references.get(conversation_id) != serialized:
        _references[conversation_id] = serialized
        with state_file(_REFERENCES_STATE) as data:
            data[conversation_id] = serialized


async def _send_activity(conversation_id: str, activity) -> None:
    if conversation_id not in _references:
        raise RuntimeError(f"No conversation reference for {conversation_id!r}; "
                           f"address the bot in that conversation first")
    reference = ConversationReference().deserialize(_references[conversation_id])

    async def callback(turn_context: TurnContext):
        await turn_context.send_activity(activity)

    await adapter.continue_conversation(reference, callback, _Config.APP_ID)


def _send(conversation_id: str, text: str) -> None:
    _run(_send_activity(conversation_id, MessageFactory.text(text)))


def _channel_display_name(activity) -> str:
    conversation = activity.conversation
    channel_data = activity.channel_data or {}
    if conversation.conversation_type == 'personal':
        return f"🧑{activity.from_property.name} <{activity.from_property.aad_object_id or 'unknown'}" \
               f"@{activity.from_property.id}>"
    if conversation.conversation_type == 'groupChat':
        return f"🔒{conversation.name or conversation.id}"
    return '#' + (channel_data.get('channel', {}).get('name') or conversation.name or 'General')


class TeamsConversation(Conversation):
    @property
    def channel_name(self) -> str | None:
        return channels_cache.get(self.channel_id)

    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        if is_error:
            text = f"🤦 {text}"
        _send(channel or self.channel_id, text)

    def send_table(self, title: str, table: List[Dict], table_format: TableFormat = TableFormat.TABLE) -> None:
        # TODO: Adaptive Card table / Excel upload according to table_format
        if not table:
            self.send_text(f"**{title}**\n\n(no rows)")
            return
        self.send_text(f"**{title}**\n\n```\n{tabulate(table, headers='keys', tablefmt='simple')}\n```")

    def send_tables(self, title: str, tables: Dict[str, List[Dict]],
                    table_format: TableFormat = TableFormat.TABLE) -> None:
        for table_title, table in tables.items():
            self.send_table(f"{title} - {table_title}", table, table_format)

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        # TODO: no ephemeral messages in Teams; this just replies in the conversation (visible to everyone)
        self.send_text(text or '', is_error=is_error)

    def send_file(self, file_data, title=None, filename=None, channel=None):
        raise NotImplementedError("File upload needs the Teams file-consent flow or SharePoint/OneDrive")

    def send_fields(self, text, fields):
        self.send_text('\n\n'.join([text or ''] + [field.get('text', '') for field in fields]))

    def send_blocks(self, blocks):
        raise NotImplementedError("Slack blocks have no Teams equivalent yet (use Adaptive Cards)")

    def get_user_info(self, user_id) -> Dict:
        return users_cache.get(user_id, {'id': user_id, 'name': user_id, 'real_name': user_id})

    def get_team_info(self) -> Dict:
        return teams_cache.get(self.team_id, {'id': self.team_id, 'name': 'Teams'})


class _Bot(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext):
        activity = turn_context.activity
        if not activity.text:
            return
        conversation_id = activity.conversation.id
        channel_data = activity.channel_data or {}
        team = channel_data.get('team') or {}
        team_id = team.get('id') or (channel_data.get('tenant') or {}).get('id', '')
        user = activity.from_property

        channels_cache[conversation_id] = _channel_display_name(activity)
        teams_cache[team_id] = {'id': team_id, 'name': team.get('name') or 'Teams'}
        users_cache[user.id] = {'id': user.id, 'name': user.aad_object_id or user.id, 'real_name': user.name}
        _remember_reference(conversation_id, TurnContext.get_conversation_reference(activity))

        text = TurnContext.remove_recipient_mention(activity) or activity.text
        conversation = TeamsConversation(bot_name, conversation_id, user.id, team_id)
        timestamp = activity.timestamp.replace(tzinfo=None) if activity.timestamp else None
        # run in the default executor: handle_message blocks and would stall the server loop
        await asyncio.get_running_loop().run_in_executor(
            None, handle_message, Message(conversation, timestamp, '', text.strip()))


async def _messages(request: web.Request) -> web.Response:
    return await adapter.process(request, _Bot())


async def _on_startup(app: web.Application) -> None:
    global _loop
    _loop = asyncio.get_running_loop()


def chat_connect(a_bot_name, a_line_handler):
    global bot_name
    bot_name = a_bot_name
    _load_references()
    app = web.Application()
    app.router.add_post('/api/messages', _messages)
    app.on_startup.append(_on_startup)
    web.run_app(app, host='0.0.0.0', port=int(os.environ.get('TEAMS_PORT', 3978)))
