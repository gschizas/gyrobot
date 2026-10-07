import os
from typing import Callable

from chat.chat_wrapper import ChatWrapper


def get_notification_sender(bot_name: str) -> Callable[[str, str], None]:
    """Return ``sender(channel, text)`` for the active chat platform (no command context needed)."""
    if 'SLACK_APP_TOKEN' in os.environ and 'SLACK_BOT_TOKEN' in os.environ:
        from chat.slack import SlackConversation as conversation_class
    elif 'DISCORD_API_TOKEN' in os.environ:
        from chat.discord import DiscordConversation as conversation_class
    elif 'TELEGRAM_API_TOKEN' in os.environ:
        from chat.telegram import TelegramConversation as conversation_class
    elif 'TEAMS_APP_ID' in os.environ:
        from chat.teams import TeamsConversation as conversation_class
    elif 'MATTERMOST_API_TOKEN' in os.environ:
        from chat.mattermost import MattermostConversation as conversation_class
    else:
        raise NotImplementedError("Unknown chat protocol")

    def sender(channel: str, text: str) -> None:
        conversation_class(bot_name, channel, None, None).send_text(text, channel=channel)

    return sender


def get_chat_wrapper(logger, bot_name: str, message_handler: Callable) -> ChatWrapper:
    if 'SLACK_APP_TOKEN' in os.environ and 'SLACK_BOT_TOKEN' in os.environ:
        import chat.slack
        connect = chat.slack.chat_connect
        chat.slack.handle_message = message_handler
        chat.slack.logger = logger
    elif 'DISCORD_API_TOKEN' in os.environ:
        import chat.discord
        connect = chat.discord.chat_connect
        chat.discord.handle_message = message_handler
        chat.discord.logger = logger
    elif 'TEAMS_APP_ID' in os.environ:
        import chat.teams
        connect = chat.teams.chat_connect
        chat.teams.handle_message = message_handler
        chat.teams.logger = logger
    elif 'TELEGRAM_API_TOKEN' in os.environ:
        import chat.telegram
        connect = chat.telegram.chat_connect
        chat.telegram.handle_message = message_handler
        chat.telegram.logger = logger
    elif 'MATTERMOST_API_TOKEN' in os.environ:
        import chat.mattermost
        connect = chat.mattermost.chat_connect
        chat.mattermost.handle_message = message_handler
        chat.mattermost.logger = logger
    else:
        raise NotImplementedError("Unknown chat protocol")
    return ChatWrapper(bot_name, message_handler, connect, logger)
