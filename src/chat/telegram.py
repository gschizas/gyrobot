"""Telegram chat platform (skeleton), selected with ``TELEGRAM_API_TOKEN``.

Built on ``pyTelegramBotAPI`` (``telebot``), which is synchronous: handlers run in
its own worker threads and outgoing calls can be made directly from any thread.
``channel_id`` is the Telegram chat id (negative for groups), kept as a string.
Telegram has no workspace concept, so ``team_id`` is unused (empty).

Notes:
* In groups the bot only sees all messages if *privacy mode* is disabled in @BotFather.
* Outgoing text is sent as HTML: Slack-style ``` code blocks and ``*bold*`` are converted.

Not implemented yet: see ``TODO.md``.
"""
PLUGIN = {'requires': ['TELEGRAM_API_TOKEN'], 'dependencies': ['pyTelegramBotAPI>=4.14.0'], 'priority': 40}

import datetime
import html
import io
import logging
import os
import re
from typing import Dict, List

import telebot
from tabulate import tabulate

from backend.constants import TableFormat
from chat.chat_wrapper import Conversation, Message

MAX_MESSAGE_LENGTH = 3500  # Telegram's limit is 4096 *after* HTML escaping/tags are added

bot_name: str
handle_message: callable
logger: logging.Logger = logging.getLogger(__name__)
bot = telebot.TeleBot(os.environ.get('TELEGRAM_API_TOKEN', ''), threaded=True, parse_mode=None)

users_cache: dict = {}
channels_cache: dict = {}


def _to_html(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r'```(?:\w*\n)?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    return re.sub(r'(?<![\w*])\*(\S[^*\n]*?)\*(?![\w*])', r'<b>\1</b>', text)


def _chunks(text: str, size: int = MAX_MESSAGE_LENGTH):
    for start in range(0, len(text), size):
        yield text[start:start + size]


def _send(chat_id: str, text: str) -> None:
    for part in _chunks(text):
        bot.send_message(chat_id, _to_html(part), parse_mode='HTML')


class TelegramConversation(Conversation):
    @property
    def channel_name(self) -> str | None:
        if self.channel_id not in channels_cache:
            chat = bot.get_chat(self.channel_id)
            if chat.type == 'private':
                channels_cache[self.channel_id] = f"🧑{chat.first_name or ''} {chat.last_name or ''}".strip() \
                                                  + f" <{chat.username or 'unknown'}@{chat.id}>"
            else:
                prefix = '#' if chat.username else '🔒'
                channels_cache[self.channel_id] = prefix + (chat.title or str(chat.id))
        return channels_cache[self.channel_id]

    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        if is_error:
            text = f"🤦 {text}"
        _send(channel or self.channel_id, text)

    def send_table(self, title: str, table: List[Dict], table_format: TableFormat = TableFormat.TABLE) -> None:
        # TODO: Excel / file output according to table_format
        if not table:
            self.send_text(f"*{title}*\n(no rows)")
            return
        self.send_text(f"*{title}*")
        for part in _chunks(tabulate(table, headers='keys', tablefmt='simple')):
            self.send_text(f"```\n{part}\n```")

    def send_tables(self, title: str, tables: Dict[str, List[Dict]],
                    table_format: TableFormat = TableFormat.TABLE) -> None:
        for table_title, table in tables.items():
            self.send_table(f"{title} - {table_title}", table, table_format)

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        # No ephemeral messages on Telegram: DM the user (works only if they have started the bot).
        _send(self.user_id, text or '')

    def send_file(self, file_data, title=None, filename=None, channel=None):
        document = io.BytesIO(file_data)
        document.name = filename or 'file.txt'
        bot.send_document(channel or self.channel_id, document, caption=title)

    def send_fields(self, text, fields):
        self.send_text('\n'.join([text or ''] + [field.get('text', '') for field in fields]))

    def send_blocks(self, blocks):
        raise NotImplementedError("Slack blocks have no Telegram equivalent yet")

    def get_user_info(self, user_id) -> Dict:
        if user_id not in users_cache:
            user = bot.get_chat_member(self.channel_id, user_id).user
            users_cache[user_id] = {'id': str(user.id), 'name': user.username or str(user.id),
                                    'real_name': user.full_name}
        return users_cache[user_id]

    def get_team_info(self) -> Dict:
        return {'id': '', 'name': 'Telegram'}


@bot.message_handler(content_types=['text'])
def handle_telegram_message(message: telebot.types.Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    chat = message.chat
    if str(message.from_user.id) not in users_cache:
        users_cache[str(message.from_user.id)] = {
            'id': str(message.from_user.id), 'name': message.from_user.username or str(message.from_user.id),
            'real_name': message.from_user.full_name}
    permalink = f"https://t.me/{chat.username}/{message.message_id}" if chat.username else ''
    conversation = TelegramConversation(bot_name, str(chat.id), str(message.from_user.id), '')
    handle_message(Message(conversation, datetime.datetime.fromtimestamp(message.date), permalink, message.text))


def chat_connect(a_bot_name, a_line_handler):
    global bot_name
    bot_name = a_bot_name
    bot.infinity_polling()


def setup(a_logger, message_handler):
    """Plugin entry point (see ``plugins.py``): returns the blocking connect function."""
    global logger, handle_message
    logger = a_logger
    handle_message = message_handler
    return chat_connect


CONVERSATION_CLASS = TelegramConversation
